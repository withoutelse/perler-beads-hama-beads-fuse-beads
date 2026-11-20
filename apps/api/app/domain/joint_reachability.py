from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

from app.domain.joint_booleans import JointBoolean, JointBooleanExtraction
from app.domain.voxel import Coord2, Coord3

_NEIGHBORS_4: tuple[Coord2, ...] = ((0, 1), (1, 0), (0, -1), (-1, 0))


class JointReachabilityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class JointReachabilitySkipReason(str, Enum):
    """Why a complete M4-T2 boolean is not reachable to the plate boundary."""

    SLOT_OPENING_NOT_ON_PLATE_BOUNDARY = "slot_opening_not_on_plate_boundary"
    SLOT_OPENING_TOO_NARROW = "slot_opening_too_narrow"
    NO_FREE_PATH_TO_PLATE_BOUNDARY = "no_free_path_to_plate_boundary"
    PATH_TOO_NARROW = "path_too_narrow"
    UNSUPPORTED_PLATE = "unsupported_plate"


@dataclass(frozen=True, slots=True)
class JointReachabilityConfig:
    """Manufacturability rules for M4-T3 slot-mouth reachability.

    The required path width is the larger of ``min_path_width_cells`` and the
    joint's tongue width. A free cell is passable at width ``w`` only when it
    belongs to a ``w x w`` all-free square in the contact-frame slot-cavity
    plane. This makes a one-cell-wide corridor fail for a two-cell load-bearing
    tongue while still allowing a through-slot to leave a one-cell-thick plate.
    """

    min_path_width_cells: int = 1

    def __post_init__(self) -> None:
        if not _is_positive_int(self.min_path_width_cells):
            raise JointReachabilityError(
                "JOINT_REACHABILITY_INVALID_CONFIG",
                "min_path_width_cells must be a positive integer",
            )


@dataclass(frozen=True, slots=True)
class JointReachability:
    """A complete boolean whose slot mouth reaches the free exterior."""

    boolean_id: str
    candidate_id: str
    contact_edge_id: str
    plate_a: str
    plate_b: str
    required_width_cells: int
    path_width_cells: int
    path_cells: frozenset[Coord3]
    opening_cells: frozenset[Coord3]
    plate_axes: tuple[int, int]
    thickness_axis: int
    thickness_value: int

    def __post_init__(self) -> None:
        _validate_ids(self.boolean_id, self.candidate_id, self.contact_edge_id)
        _validate_plates(self.plate_a, self.plate_b)
        if not _is_positive_int(self.required_width_cells):
            raise JointReachabilityError(
                "JOINT_REACHABILITY_INVALID_RECORD",
                "required width must be positive",
            )
        if not _is_positive_int(self.path_width_cells):
            raise JointReachabilityError(
                "JOINT_REACHABILITY_INVALID_RECORD",
                "path width must be positive",
            )
        if self.path_width_cells < self.required_width_cells:
            raise JointReachabilityError(
                "JOINT_REACHABILITY_INVALID_RECORD",
                "path width must satisfy the required width",
            )
        _validate_axes(self.plate_axes, self.thickness_axis)
        if not _is_int(self.thickness_value):
            raise JointReachabilityError(
                "JOINT_REACHABILITY_INVALID_RECORD",
                "thickness value must be an integer",
            )
        _validate_cell_set(self.path_cells, "path")
        _validate_cell_set(self.opening_cells, "opening")
        _validate_plane_cells(
            self.path_cells,
            self.thickness_axis,
            self.thickness_value,
        )
        _validate_plane_cells(
            self.opening_cells,
            self.thickness_axis,
            self.thickness_value,
        )
        if not self.path_cells or not self.opening_cells:
            raise JointReachabilityError(
                "JOINT_REACHABILITY_INVALID_RECORD",
                "path and opening cells are required",
            )
        if not self.opening_cells <= self.path_cells:
            raise JointReachabilityError(
                "JOINT_REACHABILITY_INVALID_RECORD",
                "opening cells must be part of the path",
            )
        if not _is_connected_path(self.path_cells, self.plate_axes):
            raise JointReachabilityError(
                "JOINT_REACHABILITY_INVALID_RECORD",
                "path cells must be 4-connected in the plate plane",
            )

    @property
    def id(self) -> str:
        return self.boolean_id

    @property
    def is_reachable(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class SkippedJointReachability:
    """A complete boolean that cannot reach the free exterior."""

    boolean_id: str
    candidate_id: str
    contact_edge_id: str
    plate_a: str
    plate_b: str
    required_width_cells: int
    max_path_width_cells: int
    reason: JointReachabilitySkipReason
    detail: str = ""

    def __post_init__(self) -> None:
        _validate_ids(self.boolean_id, self.candidate_id, self.contact_edge_id)
        _validate_plates(self.plate_a, self.plate_b)
        if not _is_positive_int(self.required_width_cells):
            raise JointReachabilityError(
                "JOINT_REACHABILITY_INVALID_RECORD",
                "required width must be positive",
            )
        if not _is_non_negative_int(self.max_path_width_cells):
            raise JointReachabilityError(
                "JOINT_REACHABILITY_INVALID_RECORD",
                "max path width must be non-negative",
            )
        if not isinstance(self.reason, JointReachabilitySkipReason):
            raise JointReachabilityError(
                "JOINT_REACHABILITY_INVALID_RECORD",
                "skip reason must be a JointReachabilitySkipReason",
            )

    @property
    def id(self) -> str:
        return self.boolean_id


@dataclass(frozen=True, slots=True)
class JointReachabilityExtraction:
    """M4-T3 results together with the M4-T2 booleans they consume."""

    booleans: JointBooleanExtraction
    reachable: tuple[JointReachability, ...] = ()
    skipped: tuple[SkippedJointReachability, ...] = ()

    def __post_init__(self) -> None:
        boolean_by_id = {
            boolean.id: boolean for boolean in self.booleans.booleans
        }
        reachable_ids = [record.boolean_id for record in self.reachable]
        if len(reachable_ids) != len(set(reachable_ids)):
            raise JointReachabilityError(
                "JOINT_REACHABILITY_DUPLICATE_ID",
                "reachability ids must be unique",
            )

        handled: set[str] = set()
        for reachable_record in self.reachable:
            boolean = boolean_by_id.get(reachable_record.boolean_id)
            if boolean is None:
                raise JointReachabilityError(
                    "JOINT_REACHABILITY_UNKNOWN_BOOLEAN",
                    "reachability must reference an existing joint boolean",
                )
            if reachable_record.boolean_id in handled:
                raise JointReachabilityError(
                    "JOINT_REACHABILITY_DUPLICATE_BOOLEAN",
                    "a boolean can produce at most one reachability record",
                )
            handled.add(reachable_record.boolean_id)
            _validate_reachability_matches_boolean(reachable_record, boolean)

        for skipped_record in self.skipped:
            boolean = boolean_by_id.get(skipped_record.boolean_id)
            if boolean is None:
                raise JointReachabilityError(
                    "JOINT_REACHABILITY_UNKNOWN_BOOLEAN",
                    "skipped reachability must reference an existing joint boolean",
                )
            if skipped_record.boolean_id in handled:
                raise JointReachabilityError(
                    "JOINT_REACHABILITY_DUPLICATE_BOOLEAN",
                    "a boolean cannot be both reachable and skipped",
                )
            handled.add(skipped_record.boolean_id)
            _validate_skipped_matches_boolean(skipped_record, boolean)

    @property
    def graph(self):
        return self.booleans.graph

    @property
    def source(self) -> JointBooleanExtraction:
        return self.booleans

    @property
    def boolean_extraction(self) -> JointBooleanExtraction:
        return self.booleans

    @property
    def reachable_count(self) -> int:
        return len(self.reachable)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def unhandled_booleans(self) -> tuple[JointBoolean, ...]:
        handled = {record.boolean_id for record in self.reachable}
        handled |= {record.boolean_id for record in self.skipped}
        return tuple(
            boolean
            for boolean in self.booleans.booleans
            if boolean.id not in handled
        )

    def reachability_by_id(self, boolean_id: str) -> JointReachability:
        for record in self.reachable:
            if record.boolean_id == boolean_id:
                return record
        raise KeyError(boolean_id)

    def reachable_for_edge(
        self,
        contact_edge_id: str,
    ) -> tuple[JointReachability, ...]:
        return tuple(
            record
            for record in self.reachable
            if record.contact_edge_id == contact_edge_id
        )

    def skipped_for_edge(
        self,
        contact_edge_id: str,
    ) -> tuple[SkippedJointReachability, ...]:
        return tuple(
            record
            for record in self.skipped
            if record.contact_edge_id == contact_edge_id
        )

    def reachable_for_plate(self, plate_id: str) -> tuple[JointReachability, ...]:
        if plate_id not in self.graph.nodes:
            raise JointReachabilityError(
                "JOINT_REACHABILITY_UNKNOWN_PLATE",
                f"unknown plate {plate_id}",
            )
        return tuple(
            record
            for record in self.reachable
            if plate_id in (record.plate_a, record.plate_b)
        )


def generate_joint_reachability(
    booleans: JointBooleanExtraction,
    config: JointReachabilityConfig | None = None,
) -> JointReachabilityExtraction:
    """Check that every complete boolean has a wide enough slot-mouth path.

    The BFS runs in the contact-frame slot-cavity plane (``u-v``) at the fixed
    ``w`` coordinate, not in the full voxel assembly. Plate B solid cells in
    that plane are obstacles; the slot cavity and the space outside the plate
    are free. A path must start at the slot opening and reach the outer boundary
    of the expanded domain. This rejects blind interior pockets while allowing
    a through-slot to leave a one-cell-thick plate.
    """

    settings = config or JointReachabilityConfig()
    reachable: list[JointReachability] = []
    skipped: list[SkippedJointReachability] = []

    for boolean in booleans.booleans:
        try:
            record = _build_reachability(boolean, settings)
        except _ReachabilitySkip as skip:
            skipped.append(
                _make_skipped(
                    boolean,
                    skip.reason,
                    skip.detail,
                    skip.max_path_width_cells,
                    max(settings.min_path_width_cells, boolean.width),
                )
            )
        else:
            reachable.append(record)

    return JointReachabilityExtraction(
        booleans=booleans,
        reachable=tuple(reachable),
        skipped=tuple(skipped),
    )


class _ReachabilitySkip(Exception):
    def __init__(
        self,
        reason: JointReachabilitySkipReason,
        detail: str,
        max_path_width_cells: int = 0,
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.max_path_width_cells = max_path_width_cells
        super().__init__(detail)


def _build_reachability(
    boolean: JointBoolean,
    config: JointReachabilityConfig,
) -> JointReachability:
    original_cells = (
        boolean.plate_b_remaining_cells | boolean.slot_solid_cells
    )
    if not original_cells:
        raise _ReachabilitySkip(
            JointReachabilitySkipReason.UNSUPPORTED_PLATE,
            "plate B has no solid cells",
        )
    if boolean.plate_b_remaining_cells & boolean.slot_solid_cells:
        raise _ReachabilitySkip(
            JointReachabilitySkipReason.UNSUPPORTED_PLATE,
            "plate B remaining and slot solid cells overlap",
        )

    plate_axes, thickness_axis, thickness_value = _slot_plane(boolean)
    original_at_slot_plane = {
        cell for cell in original_cells if cell[thickness_axis] == thickness_value
    }
    if not original_at_slot_plane:
        raise _ReachabilitySkip(
            JointReachabilitySkipReason.UNSUPPORTED_PLATE,
            "plate B has no solid cells in the slot plane",
        )
    original_projected = {
        _project(cell, plate_axes) for cell in original_at_slot_plane
    }
    remaining_projected = {
        _project(cell, plate_axes)
        for cell in boolean.plate_b_remaining_cells
        if cell[thickness_axis] == thickness_value
    }
    opening_projected = {
        _project(cell, plate_axes) for cell in boolean.slot_opening_cells
    }
    if not opening_projected:
        raise _ReachabilitySkip(
            JointReachabilitySkipReason.UNSUPPORTED_PLATE,
            "slot opening cells are unavailable",
        )

    plate_boundary = {
        cell
        for cell in original_projected
        if any(
            _add(cell, offset) not in original_projected
            for offset in _NEIGHBORS_4
        )
    }
    if not opening_projected <= plate_boundary:
        raise _ReachabilitySkip(
            JointReachabilitySkipReason.SLOT_OPENING_NOT_ON_PLATE_BOUNDARY,
            "slot opening is not on the plate-B boundary",
        )

    all_projected = original_projected | {
        _project(cell, plate_axes) for cell in boolean.slot_cells
    }
    required_width = max(config.min_path_width_cells, boolean.width)
    max_possible_width = max(
        boolean.slot_width,
        boolean.slot_length,
        required_width,
        1,
    )
    margin = max_possible_width + 1
    min_u = min(u for u, _ in all_projected) - margin
    max_u = max(u for u, _ in all_projected) + margin
    min_v = min(v for _, v in all_projected) - margin
    max_v = max(v for _, v in all_projected) + margin
    domain = {
        (u, v)
        for u in range(min_u, max_u + 1)
        for v in range(min_v, max_v + 1)
    }
    free = domain - remaining_projected
    domain_boundary = {
        cell
        for cell in domain
        if cell[0] in (min_u, max_u) or cell[1] in (min_v, max_v)
    }
    starts = opening_projected & free
    if not starts:
        raise _ReachabilitySkip(
            JointReachabilitySkipReason.UNSUPPORTED_PLATE,
            "slot opening cells are not free in the slot-cavity plane",
        )

    bounds = (min_u, min_v, max_u, max_v)
    max_path_width = _max_reachable_width(
        free,
        starts,
        domain_boundary,
        max_possible_width,
        bounds,
    )
    if max_path_width < required_width:
        passable = _passable_cells(free, required_width, bounds)
        reason = (
            JointReachabilitySkipReason.SLOT_OPENING_TOO_NARROW
            if not starts & passable
            else JointReachabilitySkipReason.PATH_TOO_NARROW
        )
        if max_path_width == 0:
            reason = JointReachabilitySkipReason.NO_FREE_PATH_TO_PLATE_BOUNDARY
        raise _ReachabilitySkip(
            reason,
            f"max path width {max_path_width} < required {required_width}",
            max_path_width,
        )

    path = _path_to_boundary(
        free,
        starts,
        domain_boundary,
        required_width,
        bounds,
    )
    if path is None:
        raise _ReachabilitySkip(
            JointReachabilitySkipReason.NO_FREE_PATH_TO_PLATE_BOUNDARY,
            "no free path from the slot opening to the plate boundary",
            max_path_width,
        )
    path = frozenset(path | opening_projected)

    opening_cells = _to_world(
        opening_projected,
        plate_axes,
        thickness_axis,
        thickness_value,
    )
    if not opening_cells <= boolean.slot_opening_cells:
        raise _ReachabilitySkip(
            JointReachabilitySkipReason.UNSUPPORTED_PLATE,
                "slot opening does not lie in the slot-cavity plane",
        )

    return JointReachability(
        boolean_id=boolean.id,
        candidate_id=boolean.candidate_id,
        contact_edge_id=boolean.contact_edge_id,
        plate_a=boolean.plate_a,
        plate_b=boolean.plate_b,
        required_width_cells=required_width,
        path_width_cells=max_path_width,
        path_cells=_to_world(
            path,
            plate_axes,
            thickness_axis,
            thickness_value,
        ),
        opening_cells=opening_cells,
        plate_axes=plate_axes,
        thickness_axis=thickness_axis,
        thickness_value=thickness_value,
    )


def _slot_plane(boolean: JointBoolean) -> tuple[tuple[int, int], int, int]:
    """Return the contact-frame slot-cavity plane and its fixed w coordinate.

    The slot is cut along the contact normal ``v`` and spans the tongue width
    along ``u``. A one-cell-thick plate therefore appears as a line in this
    plane; a through-slot is open to the exterior through the ``v`` direction
    instead of being mistaken for a blind hole in the plate's physical plane.
    """

    u_axis = _axis_index(boolean.u_axis)
    v_axis = _axis_index(boolean.v_axis)
    w_axis = _axis_index(boolean.w_axis)
    if len({u_axis, v_axis, w_axis}) != 3:
        raise _ReachabilitySkip(
            JointReachabilitySkipReason.UNSUPPORTED_PLATE,
            "contact axes do not span three world axes",
        )

    thickness_values = {cell[w_axis] for cell in boolean.slot_cells}
    if len(thickness_values) != 1:
        raise _ReachabilitySkip(
            JointReachabilitySkipReason.UNSUPPORTED_PLATE,
            "slot cavity must have one fixed w coordinate",
        )
    return (min(u_axis, v_axis), max(u_axis, v_axis)), w_axis, next(
        iter(thickness_values)
    )


def _max_reachable_width(
    free: set[Coord2],
    starts: set[Coord2],
    targets: set[Coord2],
    upper_bound: int,
    bounds: tuple[int, int, int, int],
) -> int:
    if _path_to_boundary(free, starts, targets, 1, bounds) is None:
        return 0
    low = 1
    high = upper_bound
    while low < high:
        middle = (low + high + 1) // 2
        if _path_to_boundary(free, starts, targets, middle, bounds) is None:
            high = middle - 1
        else:
            low = middle
    return low


def _path_to_boundary(
    free: set[Coord2],
    starts: set[Coord2],
    targets: set[Coord2],
    width: int,
    bounds: tuple[int, int, int, int],
) -> frozenset[Coord2] | None:
    if width <= 0:
        return None
    passable = _passable_cells(free, width, bounds)
    start_cells = starts & passable
    target_cells = targets & passable
    if not start_cells or not target_cells:
        return None

    queue = deque(sorted(start_cells))
    parent: dict[Coord2, Coord2 | None] = {cell: None for cell in queue}
    while queue:
        cell = queue.popleft()
        if cell in target_cells:
            return frozenset(_reconstruct_path(parent, cell))
        for offset in _NEIGHBORS_4:
            neighbor = _add(cell, offset)
            if neighbor in passable and neighbor not in parent:
                parent[neighbor] = cell
                queue.append(neighbor)
    return None


def _passable_cells(
    free: set[Coord2],
    width: int,
    bounds: tuple[int, int, int, int],
) -> set[Coord2]:
    min_u, min_v, max_u, max_v = bounds
    passable: set[Coord2] = set()
    for u in range(min_u, max_u - width + 2):
        for v in range(min_v, max_v - width + 2):
            square = {
                (u + du, v + dv)
                for du in range(width)
                for dv in range(width)
            }
            if square <= free:
                passable.update(square)
    return passable


def _reconstruct_path(
    parent: dict[Coord2, Coord2 | None],
    end: Coord2,
) -> tuple[Coord2, ...]:
    path: list[Coord2] = []
    current: Coord2 | None = end
    while current is not None:
        path.append(current)
        current = parent[current]
    path.reverse()
    return tuple(path)


def _project(cell: Coord3, axes: tuple[int, int]) -> Coord2:
    return (cell[axes[0]], cell[axes[1]])


def _to_world(
    cells: set[Coord2] | frozenset[Coord2],
    axes: tuple[int, int],
    thickness_axis: int,
    thickness_value: int,
) -> frozenset[Coord3]:
    result: set[Coord3] = set()
    for u, v in cells:
        coordinate = [0, 0, 0]
        coordinate[axes[0]] = u
        coordinate[axes[1]] = v
        coordinate[thickness_axis] = thickness_value
        result.add((coordinate[0], coordinate[1], coordinate[2]))
    return frozenset(result)


def _is_connected_path(
    cells: frozenset[Coord3],
    axes: tuple[int, int],
) -> bool:
    projected = {_project(cell, axes) for cell in cells}
    if not projected:
        return False
    start = min(projected)
    seen = {start}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        for offset in _NEIGHBORS_4:
            neighbor = _add(cell, offset)
            if neighbor in projected and neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return len(seen) == len(projected)


def _validate_reachability_matches_boolean(
    record: JointReachability,
    boolean: JointBoolean,
) -> None:
    if (
        record.boolean_id != boolean.id
        or record.candidate_id != boolean.candidate_id
        or record.contact_edge_id != boolean.contact_edge_id
        or record.plate_a != boolean.plate_a
        or record.plate_b != boolean.plate_b
        or record.required_width_cells < boolean.width
        or not record.opening_cells <= boolean.slot_opening_cells
    ):
        raise JointReachabilityError(
            "JOINT_REACHABILITY_BOOLEAN_MISMATCH",
            "reachability metadata must match its joint boolean",
        )


def _validate_skipped_matches_boolean(
    record: SkippedJointReachability,
    boolean: JointBoolean,
) -> None:
    if (
        record.boolean_id != boolean.id
        or record.candidate_id != boolean.candidate_id
        or record.contact_edge_id != boolean.contact_edge_id
        or record.plate_a != boolean.plate_a
        or record.plate_b != boolean.plate_b
        or record.required_width_cells < boolean.width
    ):
        raise JointReachabilityError(
            "JOINT_REACHABILITY_BOOLEAN_MISMATCH",
            "skipped reachability metadata must match its joint boolean",
        )


def _make_skipped(
    boolean: JointBoolean,
    reason: JointReachabilitySkipReason,
    detail: str,
    max_path_width_cells: int,
    required_width_cells: int,
) -> SkippedJointReachability:
    return SkippedJointReachability(
        boolean_id=boolean.id,
        candidate_id=boolean.candidate_id,
        contact_edge_id=boolean.contact_edge_id,
        plate_a=boolean.plate_a,
        plate_b=boolean.plate_b,
        required_width_cells=required_width_cells,
        max_path_width_cells=max_path_width_cells,
        reason=reason,
        detail=detail,
    )


def _validate_ids(*values: str) -> None:
    if any(not value for value in values):
        raise JointReachabilityError(
            "JOINT_REACHABILITY_INVALID_RECORD",
            "reachability ids are required",
        )


def _validate_plates(plate_a: str, plate_b: str) -> None:
    if not plate_a or not plate_b or plate_a >= plate_b:
        raise JointReachabilityError(
            "JOINT_REACHABILITY_INVALID_RECORD",
            "reachability plates must be canonical and non-empty",
        )


def _validate_axes(plate_axes: tuple[int, int], thickness_axis: int) -> None:
    if (
        len(plate_axes) != 2
        or plate_axes[0] == plate_axes[1]
        or any(axis not in (0, 1, 2) for axis in plate_axes)
        or thickness_axis not in (0, 1, 2)
        or thickness_axis in plate_axes
    ):
        raise JointReachabilityError(
            "JOINT_REACHABILITY_INVALID_RECORD",
            "slot-cavity axes must be two distinct world axes plus one thickness axis",
        )


def _validate_cell_set(cells: frozenset[Coord3], name: str) -> None:
    if not isinstance(cells, frozenset):
        raise JointReachabilityError(
            "JOINT_REACHABILITY_INVALID_RECORD",
            f"{name} cells must be a frozenset",
        )
    for cell in cells:
        if (
            not isinstance(cell, tuple)
            or len(cell) != 3
            or not all(_is_int(part) for part in cell)
        ):
            raise JointReachabilityError(
                "JOINT_REACHABILITY_INVALID_RECORD",
                f"{name} cells must be world-coordinate integer triples",
            )


def _validate_plane_cells(
    cells: frozenset[Coord3],
    thickness_axis: int,
    thickness_value: int,
) -> None:
    if any(cell[thickness_axis] != thickness_value for cell in cells):
        raise JointReachabilityError(
            "JOINT_REACHABILITY_INVALID_RECORD",
            "path and opening cells must lie in the slot-cavity plane",
        )


def _axis_index(axis: Coord3) -> int:
    for index, value in enumerate(axis):
        if value != 0:
            return index
    raise JointReachabilityError(
        "JOINT_REACHABILITY_INVALID_RECORD",
        "contact axis must be a signed world axis",
    )


def _add(left: Coord2, right: Coord2) -> Coord2:
    return (left[0] + right[0], left[1] + right[1])


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
