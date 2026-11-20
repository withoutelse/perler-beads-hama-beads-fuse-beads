from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from app.domain.cross_skeletons import CrossSkeleton
from app.domain.horizontal_plates import HorizontalPlate
from app.domain.joint import JointDirection, JointType
from app.domain.joint_candidates import JointCandidate, JointCandidateExtraction
from app.domain.plate_adjacency import PlateAdjacencyExtraction, PlateContactKind
from app.domain.vertical_plates import VerticalPlate
from app.domain.voxel import Coord2, Coord3

_DIRECTION_VECTORS: dict[JointDirection, Coord3] = {
    JointDirection.X_POS: (1, 0, 0),
    JointDirection.X_NEG: (-1, 0, 0),
    JointDirection.Y_POS: (0, 1, 0),
    JointDirection.Y_NEG: (0, -1, 0),
    JointDirection.Z_POS: (0, 0, 1),
    JointDirection.Z_NEG: (0, 0, -1),
}


class JointBooleanError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class JointBooleanSkipReason(str, Enum):
    """Why a joint candidate cannot be turned into a manufacturable boolean."""

    WALL_TOO_THIN = "wall_too_thin"
    SLOT_NOT_OPEN_TO_BOUNDARY = "slot_not_open_to_boundary"
    PLATE_INTERSECTION = "plate_intersection"
    TONGUE_ROOT_TOO_SHORT = "tongue_root_too_short"
    CLEARANCE_INSUFFICIENT = "clearance_insufficient"
    CONTACT_FRAME_INVALID = "contact_frame_invalid"
    UNSUPPORTED_PLATE = "unsupported_plate"


@dataclass(frozen=True, slots=True)
class JointBooleanConfig:
    """Manufacturability rules for M4-T2 boolean extraction.

    The tongue is a one-cell-thick prism rooted in plate A. The slot is the
    matching cavity in plate B. A load-bearing tongue needs at least two cells
    of material behind its root; a pin needs one. The wall depth must also be
    at least the full slot length so the tongue plus clearance has a continuous
    material path instead of being silently shortened.
    """

    min_root_depth_cells: int = 2
    pin_root_depth_cells: int = 1
    min_slot_opening_cells: int = 1
    require_wall_depth_cells: bool = True
    allow_slot_air_cells: bool = True

    def __post_init__(self) -> None:
        for name, value in (
            ("min_root_depth_cells", self.min_root_depth_cells),
            ("pin_root_depth_cells", self.pin_root_depth_cells),
            ("min_slot_opening_cells", self.min_slot_opening_cells),
        ):
            if not _is_non_negative_int(value):
                raise JointBooleanError(
                    "JOINT_BOOLEAN_INVALID_CONFIG",
                    f"{name} must be a non-negative integer",
                )
        if self.min_root_depth_cells < 2:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_CONFIG",
                "min_root_depth_cells must be at least 2",
            )
        if self.pin_root_depth_cells < 1:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_CONFIG",
                "pin_root_depth_cells must be at least 1",
            )
        if self.min_slot_opening_cells < 1:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_CONFIG",
                "min_slot_opening_cells must be at least 1",
            )
        if not isinstance(self.require_wall_depth_cells, bool):
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_CONFIG",
                "require_wall_depth_cells must be a boolean",
            )
        if not isinstance(self.allow_slot_air_cells, bool):
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_CONFIG",
                "allow_slot_air_cells must be a boolean",
            )


@dataclass(frozen=True, slots=True)
class JointBoolean:
    """The real tongue solid and slot cavity for one M4-T1 candidate.

    All cell sets are in world ``(x, y, z)`` coordinates. ``tongue_cells`` is
    the one-cell-thick solid tab attached to plate A. ``slot_cells`` is the
    cavity that must be removed from plate B; it may extend into air beyond the
    plate, which is how a through-wall opening is represented without inventing
    a fake second wall thickness. ``clearance_cells`` is ``slot_cells -
    tongue_cells`` and must contain at least one cell.
    """

    id: str
    candidate_id: str
    contact_edge_id: str
    plate_a: str
    plate_b: str
    contact_kind: PlateContactKind
    direction: JointDirection
    position: int
    width: int
    length: int
    joint_type: JointType
    slot_clearance_cells: int
    contact_length: int
    edge_margin_cells: int
    tongue_cells: frozenset[Coord3]
    slot_cells: frozenset[Coord3]
    tongue_root_cells: frozenset[Coord3]
    slot_opening_cells: frozenset[Coord3]
    slot_solid_cells: frozenset[Coord3]
    slot_air_cells: frozenset[Coord3]
    plate_b_remaining_cells: frozenset[Coord3]
    plate_intersection_cells: frozenset[Coord3]
    u_axis: Coord3
    v_axis: Coord3
    w_axis: Coord3
    contact_w: int
    v_origin: int
    slot_u_start: int
    wall_depth_cells: int
    root_depth_cells: int
    required_root_depth_cells: int

    def __post_init__(self) -> None:
        for name, value in (
            ("id", self.id),
            ("candidate_id", self.candidate_id),
            ("contact_edge_id", self.contact_edge_id),
            ("plate_a", self.plate_a),
            ("plate_b", self.plate_b),
        ):
            if not value:
                raise JointBooleanError(
                    "JOINT_BOOLEAN_INVALID_RECORD",
                    f"{name} is required",
                )
        if self.plate_a >= self.plate_b:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "boolean plates must be stored in canonical id order",
            )
        if not isinstance(self.contact_kind, PlateContactKind):
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "contact kind must be a PlateContactKind",
            )
        if not isinstance(self.direction, JointDirection):
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "direction must be a JointDirection",
            )
        if not isinstance(self.joint_type, JointType):
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "joint type must be a JointType",
            )
        int_fields: tuple[tuple[str, int], ...] = (
            ("position", self.position),
            ("width", self.width),
            ("length", self.length),
            ("slot_clearance_cells", self.slot_clearance_cells),
            ("contact_length", self.contact_length),
            ("edge_margin_cells", self.edge_margin_cells),
            ("contact_w", self.contact_w),
            ("v_origin", self.v_origin),
            ("slot_u_start", self.slot_u_start),
            ("wall_depth_cells", self.wall_depth_cells),
            ("root_depth_cells", self.root_depth_cells),
            ("required_root_depth_cells", self.required_root_depth_cells),
        )
        for field_name, field_value in int_fields:
            if not _is_int(field_value):
                raise JointBooleanError(
                    "JOINT_BOOLEAN_INVALID_RECORD",
                    f"{field_name} must be an integer",
                )
        if self.position < 0 or self.edge_margin_cells < 0:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "position and edge margin must be non-negative",
            )
        if self.width <= 0 or self.length <= 0:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "width and length must be positive",
            )
        if self.slot_clearance_cells <= 0:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "slot clearance must be positive",
            )
        if self.contact_length <= 0:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "contact length must be positive",
            )
        if self.slot_width <= self.width or self.slot_length <= self.length:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "slot must be larger than the tongue in both directions",
            )
        if not self.tongue_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "tongue cells are required",
            )
        if not self.slot_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "slot cells are required",
            )
        if not self.tongue_cells <= self.slot_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "tongue cells must be inside slot cells",
            )
        if not self.clearance_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "slot must include at least one clearance cell",
            )
        if not self.tongue_root_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "tongue root cells are required",
            )
        if not self.slot_opening_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "slot opening cells are required",
            )
        if not self.slot_solid_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "slot must remove at least one solid cell",
            )
        if not self.slot_opening_cells <= self.slot_solid_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "slot opening must be part of the removed solid cells",
            )
        if not self.slot_solid_cells <= self.slot_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "slot solid cells must be a subset of slot cells",
            )
        if self.plate_intersection_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "tongue and remaining plate B solid cells must not intersect",
            )
        if self.plate_intersection_cells != self.tongue_cells & self.plate_b_remaining_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "plate intersection cells must equal tongue ∩ remaining plate B",
            )
        if self.root_depth_cells > self.wall_depth_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "root depth cannot exceed wall depth",
            )
        if self.wall_depth_cells < self.required_root_depth_cells:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "wall is too thin for the required tongue root",
            )
        for name, axis in (
            ("u_axis", self.u_axis),
            ("v_axis", self.v_axis),
            ("w_axis", self.w_axis),
        ):
            if not _is_unit_axis(axis):
                raise JointBooleanError(
                    "JOINT_BOOLEAN_INVALID_RECORD",
                    f"{name} must be a signed world axis",
                )
        if _dot(self.u_axis, self.v_axis) != 0 or _dot(self.u_axis, self.w_axis) != 0:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "contact axes must be orthogonal",
            )
        if _cross(self.v_axis, self.u_axis) != self.w_axis:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "contact axes must form a right-handed frame",
            )

    @property
    def slot_width(self) -> int:
        return self.width + self.slot_clearance_cells

    @property
    def slot_length(self) -> int:
        return self.length + self.slot_clearance_cells

    @property
    def clearance_cells(self) -> frozenset[Coord3]:
        return self.slot_cells - self.tongue_cells

    @property
    def tongue_cell_count(self) -> int:
        return len(self.tongue_cells)

    @property
    def slot_cell_count(self) -> int:
        return len(self.slot_cells)

    @property
    def clearance_count(self) -> int:
        return len(self.clearance_cells)

    @property
    def is_complementary(self) -> bool:
        return bool(self.tongue_cells <= self.slot_cells and self.clearance_cells)


@dataclass(frozen=True, slots=True)
class SkippedJointBoolean:
    """A candidate that cannot be manufactured without shrinking its joint."""

    candidate_id: str
    contact_edge_id: str
    plate_a: str
    plate_b: str
    contact_kind: PlateContactKind
    direction: JointDirection
    contact_length: int
    joint_type: JointType
    reason: JointBooleanSkipReason
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.contact_edge_id:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "skipped boolean ids are required",
            )
        if not self.plate_a or not self.plate_b or self.plate_a >= self.plate_b:
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "skipped boolean plates must be canonical and non-empty",
            )
        if not isinstance(self.contact_kind, PlateContactKind):
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "contact kind must be a PlateContactKind",
            )
        if not isinstance(self.direction, JointDirection):
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "direction must be a JointDirection",
            )
        if not isinstance(self.joint_type, JointType):
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "joint type must be a JointType",
            )
        if not _is_positive_int(self.contact_length):
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "contact length must be positive",
            )
        if not isinstance(self.reason, JointBooleanSkipReason):
            raise JointBooleanError(
                "JOINT_BOOLEAN_INVALID_RECORD",
                "skip reason must be a JointBooleanSkipReason",
            )

    @property
    def id(self) -> str:
        return self.candidate_id


@dataclass(frozen=True, slots=True)
class JointBooleanExtraction:
    """M4-T2 boolean results together with the M4-T1 candidates they consume."""

    candidates: JointCandidateExtraction
    booleans: tuple[JointBoolean, ...] = ()
    skipped: tuple[SkippedJointBoolean, ...] = ()

    def __post_init__(self) -> None:
        candidate_by_id = {
            candidate.id: candidate for candidate in self.candidates.candidates
        }
        boolean_ids = [boolean.id for boolean in self.booleans]
        if len(boolean_ids) != len(set(boolean_ids)):
            raise JointBooleanError(
                "JOINT_BOOLEAN_DUPLICATE_ID",
                "joint boolean ids must be unique",
            )

        handled: set[str] = set()
        for boolean in self.booleans:
            candidate = candidate_by_id.get(boolean.candidate_id)
            if candidate is None:
                raise JointBooleanError(
                    "JOINT_BOOLEAN_UNKNOWN_CANDIDATE",
                    "boolean must reference an existing joint candidate",
                )
            if boolean.candidate_id in handled:
                raise JointBooleanError(
                    "JOINT_BOOLEAN_DUPLICATE_CANDIDATE",
                    "a candidate can produce at most one boolean",
                )
            handled.add(boolean.candidate_id)
            _validate_boolean_matches_candidate(boolean, candidate)

        for skipped in self.skipped:
            candidate = candidate_by_id.get(skipped.candidate_id)
            if candidate is None:
                raise JointBooleanError(
                    "JOINT_BOOLEAN_UNKNOWN_CANDIDATE",
                    "skipped boolean must reference an existing joint candidate",
                )
            if skipped.candidate_id in handled:
                raise JointBooleanError(
                    "JOINT_BOOLEAN_DUPLICATE_CANDIDATE",
                    "a candidate cannot be both emitted and skipped",
                )
            handled.add(skipped.candidate_id)
            _validate_skipped_matches_candidate(skipped, candidate)

    @property
    def graph(self):
        return self.candidates.graph

    @property
    def source(self) -> JointCandidateExtraction:
        return self.candidates

    @property
    def candidate_extraction(self) -> JointCandidateExtraction:
        return self.candidates

    @property
    def boolean_count(self) -> int:
        return len(self.booleans)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def unhandled_candidates(self) -> tuple[JointCandidate, ...]:
        handled = {boolean.candidate_id for boolean in self.booleans}
        handled |= {skipped.candidate_id for skipped in self.skipped}
        return tuple(
            candidate
            for candidate in self.candidates.candidates
            if candidate.id not in handled
        )

    def candidate_by_id(self, candidate_id: str) -> JointCandidate:
        return self.candidates.candidate_by_id(candidate_id)

    def boolean_by_id(self, boolean_id: str) -> JointBoolean:
        for boolean in self.booleans:
            if boolean.id == boolean_id:
                return boolean
        raise KeyError(boolean_id)

    def booleans_for_edge(self, contact_edge_id: str) -> tuple[JointBoolean, ...]:
        return tuple(
            boolean
            for boolean in self.booleans
            if boolean.contact_edge_id == contact_edge_id
        )

    def skipped_for_edge(
        self,
        contact_edge_id: str,
    ) -> tuple[SkippedJointBoolean, ...]:
        return tuple(
            skipped
            for skipped in self.skipped
            if skipped.contact_edge_id == contact_edge_id
        )

    def booleans_for_plate(self, plate_id: str) -> tuple[JointBoolean, ...]:
        if plate_id not in self.graph.nodes:
            raise JointBooleanError(
                "JOINT_BOOLEAN_UNKNOWN_PLATE",
                f"unknown plate {plate_id}",
            )
        return tuple(
            boolean
            for boolean in self.booleans
            if plate_id in (boolean.plate_a, boolean.plate_b)
        )


def generate_joint_booleans(
    candidates: JointCandidateExtraction,
    config: JointBooleanConfig | None = None,
) -> JointBooleanExtraction:
    """Turn M4-T1 descriptors into real tongue/slot cell sets.

    Every candidate is either emitted as a complete boolean or recorded in
    ``skipped`` with a stable reason. M4-T2 never silently shrinks a tongue or
    downgrades a load-bearing joint to a pin. The light-iron zone is deliberately
    left to M4-T5, so this module does not construct the final ``Joint`` type.
    """

    settings = config or JointBooleanConfig()
    cache: dict[str, frozenset[Coord3]] = {}
    booleans: list[JointBoolean] = []
    skipped: list[SkippedJointBoolean] = []

    for candidate in candidates.candidates:
        try:
            boolean = _build_joint_boolean(
                candidate,
                candidates.adjacency,
                cache,
                settings,
            )
        except _BooleanSkip as skip:
            skipped.append(_make_skipped(candidate, skip.reason, skip.detail))
        else:
            booleans.append(boolean)

    return JointBooleanExtraction(
        candidates=candidates,
        booleans=tuple(booleans),
        skipped=tuple(skipped),
    )


class _BooleanSkip(Exception):
    def __init__(self, reason: JointBooleanSkipReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(detail)


def _build_joint_boolean(
    candidate: JointCandidate,
    adjacency: PlateAdjacencyExtraction,
    cache: dict[str, frozenset[Coord3]],
    config: JointBooleanConfig,
) -> JointBoolean:
    plate_a = _world_cells(candidate.plate_a, adjacency, cache)
    plate_b = _world_cells(candidate.plate_b, adjacency, cache)
    u_axis, v_axis, w_axis = _contact_axes(candidate)
    a_contact = {_to_contact(cell, u_axis, v_axis, w_axis) for cell in plate_a}
    b_contact = {_to_contact(cell, u_axis, v_axis, w_axis) for cell in plate_b}

    contact_cells = _contact_interface(a_contact, b_contact)
    if len(contact_cells) != candidate.contact_length:
        raise _BooleanSkip(
            JointBooleanSkipReason.CONTACT_FRAME_INVALID,
            "contact interface does not match the candidate contact length",
        )
    u_offset = min(u for u, _, _, _ in contact_cells)
    contact_cells = tuple(
        (u - u_offset, w, va, vb) for u, w, va, vb in contact_cells
    )
    a_contact = {(u - u_offset, v, w) for u, v, w in a_contact}
    b_contact = {(u - u_offset, v, w) for u, v, w in b_contact}

    rows: dict[int, set[int]] = defaultdict(set)
    for u, w, _, _ in contact_cells:
        rows[w].add(u)
    tongue_u = set(range(candidate.position, candidate.position + candidate.width))
    row_candidates = sorted(w for w, us in rows.items() if tongue_u <= us)
    if not row_candidates:
        raise _BooleanSkip(
            JointBooleanSkipReason.CONTACT_FRAME_INVALID,
            "candidate position does not fit any contact row",
        )
    contact_w = row_candidates[0]

    tongue_contact_cells = {
        (u, w, va, vb)
        for u, w, va, vb in contact_cells
        if w == contact_w and u in tongue_u
    }
    if len(tongue_contact_cells) != len(tongue_u):
        raise _BooleanSkip(
            JointBooleanSkipReason.CONTACT_FRAME_INVALID,
            "contact row is not continuous under the tongue",
        )
    v_origin_values = {vb for _, _, _, vb in tongue_contact_cells}
    v_a_values = {va for _, _, va, _ in tongue_contact_cells}
    if len(v_origin_values) != 1 or len(v_a_values) != 1:
        raise _BooleanSkip(
            JointBooleanSkipReason.CONTACT_FRAME_INVALID,
            "contact row has inconsistent depth coordinates",
        )
    v_origin = v_origin_values.pop()
    v_a = v_a_values.pop()

    if candidate.slot_width <= candidate.width or candidate.slot_length <= candidate.length:
        raise _BooleanSkip(
            JointBooleanSkipReason.CLEARANCE_INSUFFICIENT,
            "slot is not larger than the tongue",
        )
    slot_u_start = _choose_slot_start(
        rows[contact_w],
        candidate.position,
        candidate.width,
        candidate.slot_width,
    )
    if slot_u_start is None:
        raise _BooleanSkip(
            JointBooleanSkipReason.CONTACT_FRAME_INVALID,
            "slot footprint does not fit the contact row",
        )

    tongue_contact = frozenset(
        (u, v_origin + dv, contact_w)
        for u in tongue_u
        for dv in range(candidate.length)
    )
    slot_contact = frozenset(
        (u, v_origin + dv, contact_w)
        for u in range(slot_u_start, slot_u_start + candidate.slot_width)
        for dv in range(candidate.slot_length)
    )
    if not tongue_contact <= slot_contact:
        raise _BooleanSkip(
            JointBooleanSkipReason.PLATE_INTERSECTION,
            "tongue footprint is not contained by the slot cavity",
        )

    root_contact, wall_depth = _root_cells(
        a_contact,
        tongue_u,
        contact_w,
        v_a,
    )
    required_root = (
        config.min_root_depth_cells
        if candidate.joint_type is JointType.LOAD_BEARING
        else config.pin_root_depth_cells
    )
    if config.require_wall_depth_cells and wall_depth < candidate.slot_length:
        raise _BooleanSkip(
            JointBooleanSkipReason.WALL_TOO_THIN,
            f"wall depth {wall_depth} < slot length {candidate.slot_length}",
        )
    if wall_depth < required_root:
        raise _BooleanSkip(
            JointBooleanSkipReason.TONGUE_ROOT_TOO_SHORT,
            f"root depth {wall_depth} < required {required_root}",
        )

    slot_solid_contact = slot_contact & b_contact
    slot_air_contact = slot_contact - b_contact
    opening_contact = {
        cell for cell in slot_solid_contact if cell[1] == v_origin
    }
    remaining_b_contact = b_contact - slot_contact
    intersection_contact = tongue_contact & remaining_b_contact
    if (
        not slot_solid_contact
        or len(opening_contact) < config.min_slot_opening_cells
    ):
        raise _BooleanSkip(
            JointBooleanSkipReason.SLOT_NOT_OPEN_TO_BOUNDARY,
            "slot has no opening in plate B at the contact boundary",
        )
    if not config.allow_slot_air_cells and slot_air_contact:
        raise _BooleanSkip(
            JointBooleanSkipReason.SLOT_NOT_OPEN_TO_BOUNDARY,
            "slot extends beyond plate B solid cells",
        )
    if intersection_contact:
        raise _BooleanSkip(
            JointBooleanSkipReason.PLATE_INTERSECTION,
            "tongue intersects remaining plate B solid cells",
        )

    return JointBoolean(
        id=candidate.id,
        candidate_id=candidate.id,
        contact_edge_id=candidate.contact_edge_id,
        plate_a=candidate.plate_a,
        plate_b=candidate.plate_b,
        contact_kind=candidate.contact_kind,
        direction=candidate.direction,
        position=candidate.position,
        width=candidate.width,
        length=candidate.length,
        joint_type=candidate.joint_type,
        slot_clearance_cells=candidate.slot_clearance_cells,
        contact_length=candidate.contact_length,
        edge_margin_cells=candidate.edge_margin_cells,
        tongue_cells=frozenset(
            _from_contact((cell[0] + u_offset, cell[1], cell[2]), u_axis, v_axis, w_axis)
            for cell in tongue_contact
        ),
        slot_cells=frozenset(
            _from_contact((cell[0] + u_offset, cell[1], cell[2]), u_axis, v_axis, w_axis)
            for cell in slot_contact
        ),
        tongue_root_cells=frozenset(
            _from_contact((cell[0] + u_offset, cell[1], cell[2]), u_axis, v_axis, w_axis)
            for cell in root_contact
        ),
        slot_opening_cells=frozenset(
            _from_contact((cell[0] + u_offset, cell[1], cell[2]), u_axis, v_axis, w_axis)
            for cell in opening_contact
        ),
        slot_solid_cells=frozenset(
            _from_contact((cell[0] + u_offset, cell[1], cell[2]), u_axis, v_axis, w_axis)
            for cell in slot_solid_contact
        ),
        slot_air_cells=frozenset(
            _from_contact((cell[0] + u_offset, cell[1], cell[2]), u_axis, v_axis, w_axis)
            for cell in slot_air_contact
        ),
        plate_b_remaining_cells=frozenset(
            _from_contact((cell[0] + u_offset, cell[1], cell[2]), u_axis, v_axis, w_axis)
            for cell in remaining_b_contact
        ),
        plate_intersection_cells=frozenset(
            _from_contact((cell[0] + u_offset, cell[1], cell[2]), u_axis, v_axis, w_axis)
            for cell in intersection_contact
        ),
        u_axis=u_axis,
        v_axis=v_axis,
        w_axis=w_axis,
        contact_w=contact_w,
        v_origin=v_origin,
        slot_u_start=slot_u_start,
        wall_depth_cells=wall_depth,
        root_depth_cells=wall_depth,
        required_root_depth_cells=required_root,
    )


def _world_cells(
    plate_id: str,
    adjacency: PlateAdjacencyExtraction,
    cache: dict[str, frozenset[Coord3]],
) -> frozenset[Coord3]:
    cached = cache.get(plate_id)
    if cached is not None:
        return cached

    horizontal = next(
        (record for record in adjacency.horizontal.plates if record.plate.id == plate_id),
        None,
    )
    if horizontal is not None:
        cells = _horizontal_world_cells(horizontal)
    else:
        vertical = next(
            (record for record in adjacency.vertical.plates if record.plate.id == plate_id),
            None,
        )
        if vertical is not None:
            cells = _vertical_world_cells(vertical)
        else:
            cross = None
            if adjacency.cross_skeletons is not None:
                cross = next(
                    (
                        record
                        for record in adjacency.cross_skeletons.plates
                        if record.plate.id == plate_id
                    ),
                    None,
                )
            if cross is None:
                raise JointBooleanError(
                    "JOINT_BOOLEAN_UNKNOWN_PLATE",
                    f"unknown plate {plate_id}",
                )
            cells = _cross_world_cells(cross)

    cache[plate_id] = cells
    return cells


def _horizontal_world_cells(record: HorizontalPlate) -> frozenset[Coord3]:
    return frozenset((u, v, record.z) for u, v in record.plate.cells)


def _vertical_world_cells(record: VerticalPlate) -> frozenset[Coord3]:
    source_cells = record.source_cells
    if not source_cells:
        source_cells = _fallback_vertical_source_cells(record)
    return frozenset(
        (source_cells[u][0], source_cells[u][1], record.source_z + v)
        for u, v in record.plate.cells
    )


def _fallback_vertical_source_cells(record: VerticalPlate) -> tuple[Coord2, ...]:
    start = record.start_vertex
    end = record.end_vertex
    dx = (end[0] > start[0]) - (end[0] < start[0])
    dy = (end[1] > start[1]) - (end[1] < start[1])
    if (dx == 0) == (dy == 0):
        raise _BooleanSkip(
            JointBooleanSkipReason.UNSUPPORTED_PLATE,
            "vertical plate source cells are unavailable for a multi-edge span",
        )
    length = abs(end[0] - start[0]) + abs(end[1] - start[1])
    if length != record.plate.width():
        raise _BooleanSkip(
            JointBooleanSkipReason.UNSUPPORTED_PLATE,
            "vertical plate span is not a single straight source edge",
        )
    cells: list[Coord2] = []
    for offset in range(length):
        boundary = (start[0] + dx * offset, start[1] + dy * offset)
        cells.append(
            (
                boundary[0] + (dx - dy) // 2,
                boundary[1] + (dy + dx) // 2,
            )
        )
    return tuple(cells)


def _cross_world_cells(record: CrossSkeleton) -> frozenset[Coord3]:
    if not record.source_cells or not record.plate.cells:
        raise _BooleanSkip(
            JointBooleanSkipReason.UNSUPPORTED_PLATE,
            "cross skeleton source cells are unavailable",
        )
    local_min_u = min(u for u, _ in record.plate.cells)
    local_min_v = min(v for _, v in record.plate.cells)
    source_min_u = min(u for u, _ in record.source_cells)
    source_min_v = min(v for _, v in record.source_cells)
    offset_u = source_min_u - local_min_u
    offset_v = source_min_v - local_min_v
    return frozenset(
        (u + offset_u, v + offset_v, record.z)
        for u, v in record.plate.cells
    )


def _contact_axes(candidate: JointCandidate) -> tuple[Coord3, Coord3, Coord3]:
    v_axis = _DIRECTION_VECTORS[candidate.direction]
    if candidate.contact_kind is PlateContactKind.SEGMENT_JOINT:
        u_axis = (0, 0, 1)
    elif v_axis[2] != 0:
        u_axis = (1, 0, 0)
    elif v_axis[0] != 0:
        u_axis = (0, 1, 0)
    else:
        u_axis = (1, 0, 0)
    w_axis = _cross(v_axis, u_axis)
    return u_axis, v_axis, w_axis


def _contact_interface(
    a_contact: set[Coord3],
    b_contact: set[Coord3],
) -> tuple[tuple[int, int, int, int], ...]:
    a_by_uw: dict[tuple[int, int], list[int]] = defaultdict(list)
    b_by_uw: dict[tuple[int, int], list[int]] = defaultdict(list)
    for u, v, w in a_contact:
        if (u, v + 1, w) not in a_contact:
            a_by_uw[(u, w)].append(v)
    for u, v, w in b_contact:
        if (u, v - 1, w) not in b_contact:
            b_by_uw[(u, w)].append(v)

    result: list[tuple[int, int, int, int]] = []
    for u, w in sorted(set(a_by_uw) & set(b_by_uw)):
        for va in sorted(a_by_uw[(u, w)]):
            for vb in sorted(b_by_uw[(u, w)]):
                if vb - va in (0, 1):
                    result.append((u, w, va, vb))
    return tuple(result)


def _choose_slot_start(
    row_u: set[int],
    position: int,
    width: int,
    slot_width: int,
) -> int | None:
    if not row_u:
        return None
    min_u = min(row_u)
    max_u = max(row_u)
    preferred = [position, position - (slot_width - width), position + (slot_width - width)]
    for start in preferred:
        if start > position or position + width > start + slot_width:
            continue
        if set(range(start, start + slot_width)) <= row_u:
            return start
    for start in range(min_u, max_u - slot_width + 2):
        if start > position or position + width > start + slot_width:
            continue
        if set(range(start, start + slot_width)) <= row_u:
            return start
    return None


def _root_cells(
    a_contact: set[Coord3],
    tongue_u: set[int],
    contact_w: int,
    v_a: int,
) -> tuple[frozenset[Coord3], int]:
    start = v_a
    root: set[Coord3] = set()
    depths: list[int] = []
    for u in sorted(tongue_u):
        depth = 0
        v = start
        while (u, v, contact_w) in a_contact:
            root.add((u, v, contact_w))
            depth += 1
            v -= 1
        depths.append(depth)
    return frozenset(root), (min(depths) if depths else 0)


def _to_contact(
    cell: Coord3,
    u_axis: Coord3,
    v_axis: Coord3,
    w_axis: Coord3,
) -> Coord3:
    return (
        _dot(cell, u_axis),
        _dot(cell, v_axis),
        _dot(cell, w_axis),
    )


def _from_contact(
    cell: Coord3,
    u_axis: Coord3,
    v_axis: Coord3,
    w_axis: Coord3,
) -> Coord3:
    u, v, w = cell
    return (
        u * u_axis[0] + v * v_axis[0] + w * w_axis[0],
        u * u_axis[1] + v * v_axis[1] + w * w_axis[1],
        u * u_axis[2] + v * v_axis[2] + w * w_axis[2],
    )


def _dot(left: Coord3, right: Coord3) -> int:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _cross(left: Coord3, right: Coord3) -> Coord3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _make_skipped(
    candidate: JointCandidate,
    reason: JointBooleanSkipReason,
    detail: str,
) -> SkippedJointBoolean:
    return SkippedJointBoolean(
        candidate_id=candidate.id,
        contact_edge_id=candidate.contact_edge_id,
        plate_a=candidate.plate_a,
        plate_b=candidate.plate_b,
        contact_kind=candidate.contact_kind,
        direction=candidate.direction,
        contact_length=candidate.contact_length,
        joint_type=candidate.joint_type,
        reason=reason,
        detail=detail,
    )


def _validate_boolean_matches_candidate(
    boolean: JointBoolean,
    candidate: JointCandidate,
) -> None:
    if (
        boolean.candidate_id != candidate.id
        or boolean.contact_edge_id != candidate.contact_edge_id
        or boolean.plate_a != candidate.plate_a
        or boolean.plate_b != candidate.plate_b
        or boolean.contact_kind is not candidate.contact_kind
        or boolean.direction is not candidate.direction
        or boolean.position != candidate.position
        or boolean.width != candidate.width
        or boolean.length != candidate.length
        or boolean.joint_type is not candidate.joint_type
        or boolean.slot_clearance_cells != candidate.slot_clearance_cells
        or boolean.contact_length != candidate.contact_length
        or boolean.edge_margin_cells != candidate.edge_margin_cells
    ):
        raise JointBooleanError(
            "JOINT_BOOLEAN_CANDIDATE_MISMATCH",
            "boolean metadata must match its joint candidate",
        )


def _validate_skipped_matches_candidate(
    skipped: SkippedJointBoolean,
    candidate: JointCandidate,
) -> None:
    if (
        skipped.candidate_id != candidate.id
        or skipped.contact_edge_id != candidate.contact_edge_id
        or skipped.plate_a != candidate.plate_a
        or skipped.plate_b != candidate.plate_b
        or skipped.contact_kind is not candidate.contact_kind
        or skipped.direction is not candidate.direction
        or skipped.contact_length != candidate.contact_length
        or skipped.joint_type is not candidate.joint_type
    ):
        raise JointBooleanError(
            "JOINT_BOOLEAN_CANDIDATE_MISMATCH",
            "skipped metadata must match its joint candidate",
        )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_unit_axis(value: object) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 3
        and all(_is_int(part) for part in value)
        and sum(abs(part) for part in value) == 1
    )
