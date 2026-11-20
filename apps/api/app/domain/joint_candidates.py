from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.joint import JointDirection, JointType
from app.domain.plate_adjacency import (
    PlateAdjacencyExtraction,
    PlateContactEdge,
    PlateContactGraph,
    PlateContactKind,
)


class JointCandidateError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class JointCandidateSkipReason(str, Enum):
    """Why a contact edge cannot receive a joint candidate in M4-T1."""

    CONTACT_TOO_SHORT = "contact_too_short"


@dataclass(frozen=True, slots=True)
class JointCandidateConfig:
    """Deterministic sizing rules for M4-T1 joint candidates.

    M4-T1 only proposes a tongue/slot descriptor on each contact edge. M4-T2
    performs the real boolean and rejects candidates whose perpendicular
    length does not fit the target plate thickness.
    """

    edge_margin_cells: int = 1
    load_bearing_width_cells: int = 2
    load_bearing_length_cells: int = 3
    pin_width_cells: int = 1
    pin_length_cells: int = 1
    min_width_cells: int = 1
    max_width_cells: int = 3
    min_length_cells: int = 1
    max_length_cells: int = 4
    slot_clearance_cells: int = 1

    def __post_init__(self) -> None:
        for name, value in (
            ("edge_margin_cells", self.edge_margin_cells),
            ("load_bearing_width_cells", self.load_bearing_width_cells),
            ("load_bearing_length_cells", self.load_bearing_length_cells),
            ("pin_width_cells", self.pin_width_cells),
            ("pin_length_cells", self.pin_length_cells),
            ("min_width_cells", self.min_width_cells),
            ("max_width_cells", self.max_width_cells),
            ("min_length_cells", self.min_length_cells),
            ("max_length_cells", self.max_length_cells),
            ("slot_clearance_cells", self.slot_clearance_cells),
        ):
            if not _is_non_negative_int(value):
                raise JointCandidateError(
                    "JOINT_CANDIDATE_INVALID_CONFIG",
                    f"{name} must be a non-negative integer",
                )
        if self.slot_clearance_cells < 1:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_CONFIG",
                "slot_clearance_cells must be at least 1",
            )
        if self.min_width_cells < 1 or self.min_length_cells < 1:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_CONFIG",
                "minimum width and length must be at least 1",
            )
        if not (
            self.min_width_cells
            <= self.load_bearing_width_cells
            <= self.max_width_cells
        ):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_CONFIG",
                "load-bearing width must be within [min_width, max_width]",
            )
        if not (
            self.min_width_cells <= self.pin_width_cells <= self.max_width_cells
        ):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_CONFIG",
                "pin width must be within [min_width, max_width]",
            )
        if not (
            self.min_length_cells
            <= self.load_bearing_length_cells
            <= self.max_length_cells
        ):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_CONFIG",
                "load-bearing length must be within [min_length, max_length]",
            )
        if not (
            self.min_length_cells <= self.pin_length_cells <= self.max_length_cells
        ):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_CONFIG",
                "pin length must be within [min_length, max_length]",
            )
        if self.load_bearing_width_cells < 2:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_CONFIG",
                "load-bearing width must be at least 2 cells",
            )
        if self.load_bearing_length_cells < 2:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_CONFIG",
                "load-bearing length must be at least 2 cells",
            )
        if self.pin_width_cells != 1:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_CONFIG",
                "pin width must be exactly 1 cell",
            )
        if self.pin_length_cells > 2:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_CONFIG",
                "pin length must be at most 2 cells",
            )


@dataclass(frozen=True, slots=True)
class JointCandidate:
    """One tongue/slot descriptor proposed on a plate contact edge.

    ``position`` and ``width`` are measured along the contact edge on plate A.
    ``length`` is measured perpendicular to the contact edge into the slot
    plate. ``slot_width`` and ``slot_length`` add the configured clearance so
    the slot is one cell larger than the tongue in both directions.
    """

    id: str
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

    def __post_init__(self) -> None:
        if not self.id:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "candidate id is required",
            )
        if not self.contact_edge_id:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "contact edge id is required",
            )
        if not self.plate_a or not self.plate_b:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "candidate plate ids are required",
            )
        if self.plate_a >= self.plate_b:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "candidate plates must be stored in canonical id order",
            )
        if not isinstance(self.contact_kind, PlateContactKind):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "contact kind must be a PlateContactKind",
            )
        if not isinstance(self.direction, JointDirection):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "direction must be a JointDirection",
            )
        if not isinstance(self.joint_type, JointType):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "joint type must be a JointType",
            )
        if not _is_non_negative_int(self.position):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "position must be a non-negative integer",
            )
        if not _is_positive_int(self.width) or not _is_positive_int(self.length):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "width and length must be positive integers",
            )
        if not _is_positive_int(self.slot_clearance_cells):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "slot clearance must be a positive integer",
            )
        if not _is_positive_int(self.contact_length):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "contact length must be a positive integer",
            )
        if not _is_non_negative_int(self.edge_margin_cells):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "edge margin must be a non-negative integer",
            )

        if self.contact_kind is PlateContactKind.FACE and self.direction in (
            JointDirection.Z_POS,
            JointDirection.Z_NEG,
        ):
            if self.joint_type is not JointType.PIN:
                raise JointCandidateError(
                    "JOINT_CANDIDATE_INVALID_RECORD",
                    "stacked face contacts must use pin joints",
                )
            if self.width != 1 or self.length != 1:
                raise JointCandidateError(
                    "JOINT_CANDIDATE_INVALID_RECORD",
                    "stacked face pins must be 1x1 cells",
                )
            if self.position != 0:
                raise JointCandidateError(
                    "JOINT_CANDIDATE_INVALID_RECORD",
                    "stacked face pins must start at position 0",
                )
            if (
                self.slot_width > self.contact_length
                or self.slot_length > self.contact_length
            ):
                raise JointCandidateError(
                    "JOINT_CANDIDATE_INVALID_RECORD",
                    "stacked face pin slot does not fit the shared face",
                )
            return

        if self.joint_type is JointType.LOAD_BEARING:
            if self.width < 2 or self.length < 2:
                raise JointCandidateError(
                    "JOINT_CANDIDATE_INVALID_RECORD",
                    "load-bearing candidates need width and length of at least 2",
                )
        else:
            if self.width != 1 or self.length > 2:
                raise JointCandidateError(
                    "JOINT_CANDIDATE_INVALID_RECORD",
                    "pin candidates must be 1 cell wide and at most 2 cells long",
                )
        if self.position < self.edge_margin_cells:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "candidate must keep the configured edge margin",
            )
        if self.position + self.width + self.edge_margin_cells > self.contact_length:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "tongue does not fit on the contact edge",
            )
        if (
            self.position + self.slot_width + self.edge_margin_cells
            > self.contact_length
        ):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "slot does not fit on the contact edge",
            )

    @property
    def slot_width(self) -> int:
        return self.width + self.slot_clearance_cells

    @property
    def slot_length(self) -> int:
        return self.length + self.slot_clearance_cells


@dataclass(frozen=True, slots=True)
class SkippedJointCandidate:
    """Explicit record for a contact edge that cannot receive a candidate."""

    contact_edge_id: str
    plate_a: str
    plate_b: str
    contact_kind: PlateContactKind
    direction: JointDirection
    contact_length: int
    joint_type: JointType
    reason: JointCandidateSkipReason

    def __post_init__(self) -> None:
        if not self.contact_edge_id:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "skipped contact edge id is required",
            )
        if not self.plate_a or not self.plate_b:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "skipped plate ids are required",
            )
        if self.plate_a >= self.plate_b:
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "skipped plates must be stored in canonical id order",
            )
        if not isinstance(self.contact_kind, PlateContactKind):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "skipped contact kind must be a PlateContactKind",
            )
        if not isinstance(self.direction, JointDirection):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "skipped direction must be a JointDirection",
            )
        if not _is_positive_int(self.contact_length):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "skipped contact length must be a positive integer",
            )
        if not isinstance(self.joint_type, JointType):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "skipped joint type must be a JointType",
            )
        if not isinstance(self.reason, JointCandidateSkipReason):
            raise JointCandidateError(
                "JOINT_CANDIDATE_INVALID_RECORD",
                "skip reason must be a JointCandidateSkipReason",
            )


@dataclass(frozen=True, slots=True)
class JointCandidateExtraction:
    """Joint candidates together with the contact graph they came from."""

    adjacency: PlateAdjacencyExtraction
    candidates: tuple[JointCandidate, ...] = ()
    skipped: tuple[SkippedJointCandidate, ...] = ()

    def __post_init__(self) -> None:
        edge_by_id = {edge.id: edge for edge in self.adjacency.contact_edges}
        candidate_ids = [candidate.id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise JointCandidateError(
                "JOINT_CANDIDATE_DUPLICATE_ID",
                "joint candidate ids must be unique",
            )

        handled_edges: set[str] = set()
        for candidate in self.candidates:
            edge = edge_by_id.get(candidate.contact_edge_id)
            if edge is None:
                raise JointCandidateError(
                    "JOINT_CANDIDATE_UNKNOWN_EDGE",
                    "candidate must reference an existing contact edge",
                )
            if candidate.contact_edge_id in handled_edges:
                raise JointCandidateError(
                    "JOINT_CANDIDATE_DUPLICATE_EDGE",
                    "a contact edge can produce at most one joint candidate",
                )
            handled_edges.add(candidate.contact_edge_id)
            _validate_candidate_matches_edge(candidate, edge)

        for skipped in self.skipped:
            edge = edge_by_id.get(skipped.contact_edge_id)
            if edge is None:
                raise JointCandidateError(
                    "JOINT_CANDIDATE_UNKNOWN_EDGE",
                    "skipped record must reference an existing contact edge",
                )
            if skipped.contact_edge_id in handled_edges:
                raise JointCandidateError(
                    "JOINT_CANDIDATE_DUPLICATE_EDGE",
                    "a contact edge cannot be both emitted and skipped",
                )
            handled_edges.add(skipped.contact_edge_id)
            _validate_skipped_matches_edge(skipped, edge)

    @property
    def graph(self) -> PlateContactGraph:
        return self.adjacency.graph

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def unhandled_edges(self) -> tuple[PlateContactEdge, ...]:
        handled = {candidate.contact_edge_id for candidate in self.candidates}
        handled |= {skipped.contact_edge_id for skipped in self.skipped}
        return tuple(
            edge for edge in self.adjacency.contact_edges if edge.id not in handled
        )

    def candidate_by_id(self, candidate_id: str) -> JointCandidate:
        for candidate in self.candidates:
            if candidate.id == candidate_id:
                return candidate
        raise KeyError(candidate_id)

    def candidates_for_edge(self, contact_edge_id: str) -> tuple[JointCandidate, ...]:
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.contact_edge_id == contact_edge_id
        )

    def skipped_for_edge(
        self,
        contact_edge_id: str,
    ) -> tuple[SkippedJointCandidate, ...]:
        return tuple(
            skipped
            for skipped in self.skipped
            if skipped.contact_edge_id == contact_edge_id
        )

    def candidates_for_plate(self, plate_id: str) -> tuple[JointCandidate, ...]:
        if plate_id not in self.graph.nodes:
            raise JointCandidateError(
                "JOINT_CANDIDATE_UNKNOWN_PLATE",
                f"unknown plate {plate_id}",
            )
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.plate_a == plate_id or candidate.plate_b == plate_id
        )


def generate_joint_candidates(
    adjacency: PlateAdjacencyExtraction,
    config: JointCandidateConfig | None = None,
) -> JointCandidateExtraction:
    """Generate one deterministic joint candidate per contact edge.

    M4-T1 deliberately stops at descriptors: it does not create tongue or slot
    cells. M4-T2 performs the boolean and the 1-cell clearance validation.
    Contact edges that cannot hold the minimum tongue plus slot clearance are
    recorded in ``skipped`` instead of being silently downgraded.
    """

    settings = config or JointCandidateConfig()
    candidates: list[JointCandidate] = []
    skipped: list[SkippedJointCandidate] = []

    for edge in adjacency.contact_edges:
        result = _candidate_for_edge(edge, settings, len(candidates) + 1)
        if isinstance(result, JointCandidate):
            candidates.append(result)
        else:
            skipped.append(result)

    return JointCandidateExtraction(
        adjacency=adjacency,
        candidates=tuple(candidates),
        skipped=tuple(skipped),
    )


def _candidate_for_edge(
    edge: PlateContactEdge,
    config: JointCandidateConfig,
    candidate_index: int,
) -> JointCandidate | SkippedJointCandidate:
    if edge.kind is PlateContactKind.FACE and edge.direction in (
        JointDirection.Z_POS,
        JointDirection.Z_NEG,
    ):
        width = config.pin_width_cells
        length = config.pin_length_cells
        slot_width = width + config.slot_clearance_cells
        slot_length = length + config.slot_clearance_cells
        if slot_width > edge.contact_length or slot_length > edge.contact_length:
            return _skip(edge, JointType.PIN, JointCandidateSkipReason.CONTACT_TOO_SHORT)
        return JointCandidate(
            id=f"J{candidate_index:02d}",
            contact_edge_id=edge.id,
            plate_a=edge.plate_a,
            plate_b=edge.plate_b,
            contact_kind=edge.kind,
            direction=edge.direction,
            position=0,
            width=width,
            length=length,
            joint_type=JointType.PIN,
            slot_clearance_cells=config.slot_clearance_cells,
            contact_length=edge.contact_length,
            edge_margin_cells=config.edge_margin_cells,
        )

    available_width = edge.contact_length - 2 * config.edge_margin_cells
    if available_width < config.min_width_cells:
        return _skip(
            edge,
            edge.joint_type_hint,
            JointCandidateSkipReason.CONTACT_TOO_SHORT,
        )

    if edge.joint_type_hint is JointType.LOAD_BEARING:
        requested_width = config.load_bearing_width_cells
        requested_length = config.load_bearing_length_cells
    else:
        requested_width = config.pin_width_cells
        requested_length = config.pin_length_cells

    width = min(requested_width, config.max_width_cells, available_width)
    length = min(requested_length, config.max_length_cells)
    if width < config.min_width_cells or length < config.min_length_cells:
        return _skip(
            edge,
            edge.joint_type_hint,
            JointCandidateSkipReason.CONTACT_TOO_SHORT,
        )
    if edge.joint_type_hint is JointType.LOAD_BEARING and (width < 2 or length < 2):
        return _skip(
            edge,
            edge.joint_type_hint,
            JointCandidateSkipReason.CONTACT_TOO_SHORT,
        )
    if edge.joint_type_hint is JointType.PIN and (width != 1 or length > 2):
        return _skip(
            edge,
            edge.joint_type_hint,
            JointCandidateSkipReason.CONTACT_TOO_SHORT,
        )

    position = (edge.contact_length - width) // 2
    slot_width = width + config.slot_clearance_cells
    if position < config.edge_margin_cells:
        return _skip(
            edge,
            edge.joint_type_hint,
            JointCandidateSkipReason.CONTACT_TOO_SHORT,
        )
    if position + slot_width + config.edge_margin_cells > edge.contact_length:
        return _skip(
            edge,
            edge.joint_type_hint,
            JointCandidateSkipReason.CONTACT_TOO_SHORT,
        )

    return JointCandidate(
        id=f"J{candidate_index:02d}",
        contact_edge_id=edge.id,
        plate_a=edge.plate_a,
        plate_b=edge.plate_b,
        contact_kind=edge.kind,
        direction=edge.direction,
        position=position,
        width=width,
        length=length,
        joint_type=edge.joint_type_hint,
        slot_clearance_cells=config.slot_clearance_cells,
        contact_length=edge.contact_length,
        edge_margin_cells=config.edge_margin_cells,
    )


def _skip(
    edge: PlateContactEdge,
    joint_type: JointType,
    reason: JointCandidateSkipReason,
) -> SkippedJointCandidate:
    return SkippedJointCandidate(
        contact_edge_id=edge.id,
        plate_a=edge.plate_a,
        plate_b=edge.plate_b,
        contact_kind=edge.kind,
        direction=edge.direction,
        contact_length=edge.contact_length,
        joint_type=joint_type,
        reason=reason,
    )


def _validate_candidate_matches_edge(
    candidate: JointCandidate,
    edge: PlateContactEdge,
) -> None:
    if (
        candidate.plate_a != edge.plate_a
        or candidate.plate_b != edge.plate_b
        or candidate.contact_kind is not edge.kind
        or candidate.direction is not edge.direction
        or candidate.contact_length != edge.contact_length
    ):
        raise JointCandidateError(
            "JOINT_CANDIDATE_EDGE_MISMATCH",
            "candidate metadata must match its contact edge",
        )


def _validate_skipped_matches_edge(
    skipped: SkippedJointCandidate,
    edge: PlateContactEdge,
) -> None:
    if (
        skipped.plate_a != edge.plate_a
        or skipped.plate_b != edge.plate_b
        or skipped.contact_kind is not edge.kind
        or skipped.direction is not edge.direction
        or skipped.contact_length != edge.contact_length
    ):
        raise JointCandidateError(
            "JOINT_CANDIDATE_EDGE_MISMATCH",
            "skipped metadata must match its contact edge",
        )


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
