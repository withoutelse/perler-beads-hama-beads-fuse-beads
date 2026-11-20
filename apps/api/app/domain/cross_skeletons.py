from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

from app.domain.horizontal_plates import HorizontalPlate, HorizontalPlateExtraction
from app.domain.plate import Plate, PlateKind
from app.domain.voxel import Coord2

_NEIGHBORS_4: tuple[Coord2, ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))


class CrossSkeletonError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class CrossSkeletonSkipReason(str, Enum):
    HOLE_TOO_SMALL = "hole_too_small"
    HOLE_SHAPE_UNSUPPORTED = "hole_shape_unsupported"


@dataclass(frozen=True, slots=True)
class CrossSkeletonConfig:
    """Configuration for a deterministic plus-shaped skeleton blank.

    M3-T7 deliberately emits a single connected blank per ring plate. M4-T1/T2
    will split the blank into the two complementary slotted plates required by
    the glue-free route. ``min_clearance_cells`` is the minimum number of hole
    cells that must remain free around the blank for later slot generation.
    """

    arm_width_cells: int = 1
    min_clearance_cells: int = 1

    def __post_init__(self) -> None:
        if not _is_int(self.arm_width_cells) or self.arm_width_cells <= 0:
            raise CrossSkeletonError(
                "CROSS_INVALID_CONFIG",
                "arm_width_cells must be a positive integer",
            )
        if self.arm_width_cells % 2 == 0:
            raise CrossSkeletonError(
                "CROSS_INVALID_CONFIG",
                "arm_width_cells must be odd so the cross has a unique center",
            )
        if not _is_int(self.min_clearance_cells) or self.min_clearance_cells < 0:
            raise CrossSkeletonError(
                "CROSS_INVALID_CONFIG",
                "min_clearance_cells must be a non-negative integer",
            )


@dataclass(frozen=True, slots=True)
class CrossSkeleton:
    """One plus-shaped cross-skeleton blank derived from a ring hole.

    ``source_hole_cells`` and ``source_cells`` are in the source layer's
    ``(x, y)`` coordinates. ``plate.cells`` are translated to a local grid
    whose minimum coordinate is ``(0, 0)``. ``clearance_cells`` is the part of
    the chosen hole not occupied by the blank.
    """

    plate: Plate
    band_id: str
    z: int
    component_id: str
    hole_contour_ids: tuple[str, ...]
    source_hole_cells: frozenset[Coord2]
    source_cells: frozenset[Coord2]
    clearance_cells: frozenset[Coord2]
    arm_width_cells: int = 1

    def __post_init__(self) -> None:
        if not self.band_id:
            raise CrossSkeletonError("CROSS_INVALID_RECORD", "band_id is required")
        if not _is_int(self.z) or self.z < 0:
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "z must be a non-negative integer",
            )
        if not self.component_id:
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "component_id is required",
            )
        if not self.hole_contour_ids:
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "at least one hole contour id is required",
            )
        if any(not hole_id for hole_id in self.hole_contour_ids):
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "hole contour ids must be non-empty",
            )
        if len(set(self.hole_contour_ids)) != len(self.hole_contour_ids):
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "hole contour ids must be unique",
            )
        if self.plate.kind is not PlateKind.CROSS_SKELETON:
            raise CrossSkeletonError(
                "CROSS_KIND_INVALID",
                "cross skeletons must use PlateKind.CROSS_SKELETON",
            )
        if self.plate.holes:
            raise CrossSkeletonError(
                "CROSS_HOLES_FORBIDDEN",
                "cross skeleton blanks cannot contain inner holes",
            )
        if not self.plate.is_4_connected():
            raise CrossSkeletonError(
                "CROSS_DISCONNECTED",
                f"{self.plate.id} is not 4-connected",
            )
        if not self.source_hole_cells:
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "source_hole_cells must be non-empty",
            )
        if not self.source_cells:
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "source_cells must be non-empty",
            )
        if not self.source_cells <= self.source_hole_cells:
            raise CrossSkeletonError(
                "CROSS_CONTOUR_MISMATCH",
                "cross skeleton cells must be inside the source hole",
            )
        if self.clearance_cells != self.source_hole_cells - self.source_cells:
            raise CrossSkeletonError(
                "CROSS_CONTOUR_MISMATCH",
                "clearance cells must equal the source hole minus the blank",
            )
        if not _is_int(self.arm_width_cells) or self.arm_width_cells <= 0:
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "arm_width_cells must be a positive integer",
            )
        if self.arm_width_cells % 2 == 0:
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "arm_width_cells must be odd",
            )

        min_u = min(u for u, _ in self.source_cells)
        min_v = min(v for _, v in self.source_cells)
        expected_cells = frozenset(
            (u - min_u, v - min_v) for u, v in self.source_cells
        )
        if expected_cells != self.plate.cells:
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "plate cells must be the translated source cells",
            )

    @property
    def id(self) -> str:
        return self.plate.id

    @property
    def width(self) -> int:
        return self.plate.width()

    @property
    def height(self) -> int:
        return self.plate.height()

    @property
    def cell_count(self) -> int:
        return len(self.plate.cells)

    @property
    def clearance_count(self) -> int:
        return len(self.clearance_cells)


@dataclass(frozen=True, slots=True)
class SkippedCrossSkeleton:
    band_id: str
    z: int
    component_id: str
    hole_contour_ids: tuple[str, ...]
    reason: CrossSkeletonSkipReason

    def __post_init__(self) -> None:
        if not self.band_id or not self.component_id:
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "skipped cross skeleton ids must be non-empty",
            )
        if not _is_int(self.z) or self.z < 0:
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "skipped cross skeleton z must be a non-negative integer",
            )
        if not self.hole_contour_ids or any(
            not hole_id for hole_id in self.hole_contour_ids
        ):
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "skipped cross skeleton hole ids must be non-empty",
            )
        if not isinstance(self.reason, CrossSkeletonSkipReason):
            raise CrossSkeletonError(
                "CROSS_INVALID_RECORD",
                "skip reason must be a CrossSkeletonSkipReason",
            )


@dataclass(frozen=True, slots=True)
class CrossSkeletonExtraction:
    horizontal: HorizontalPlateExtraction
    plates: tuple[CrossSkeleton, ...] = ()
    skipped: tuple[SkippedCrossSkeleton, ...] = ()

    def __post_init__(self) -> None:
        plate_ids = [record.plate.id for record in self.plates]
        if len(plate_ids) != len(set(plate_ids)):
            raise CrossSkeletonError(
                "CROSS_DUPLICATE_ID",
                "cross skeleton plate ids must be unique",
            )

        ring_by_key = {
            (ring.band_id, ring.z, ring.component_id): ring
            for ring in self.horizontal.plates
        }
        band_by_id = {band.id: band for band in self.horizontal.bands.bands}
        seen: set[tuple[str, int, str]] = set()

        for record in self.plates:
            key = (record.band_id, record.z, record.component_id)
            if key in seen:
                raise CrossSkeletonError(
                    "CROSS_DUPLICATE_RING",
                    "a ring can produce at most one cross skeleton",
                )
            seen.add(key)
            ring = ring_by_key.get(key)
            if ring is None:
                raise CrossSkeletonError(
                    "CROSS_PLATE_MISMATCH",
                    "cross skeleton must reference an existing horizontal ring",
                )
            band = band_by_id.get(record.band_id)
            if band is None or band.is_empty or record.z not in band.layer_indices:
                raise CrossSkeletonError(
                    "CROSS_BAND_MISMATCH",
                    "cross skeleton z must belong to a non-empty layer band",
                )
            if not record.source_hole_cells <= ring.plate.holes:
                raise CrossSkeletonError(
                    "CROSS_CONTOUR_MISMATCH",
                    "cross skeleton source hole must be part of the ring holes",
                )
            if not set(record.hole_contour_ids) <= set(ring.hole_contour_ids):
                raise CrossSkeletonError(
                    "CROSS_CONTOUR_MISMATCH",
                    "cross skeleton hole ids must belong to the source ring",
                )

        for skipped in self.skipped:
            key = (skipped.band_id, skipped.z, skipped.component_id)
            if key in seen:
                raise CrossSkeletonError(
                    "CROSS_DUPLICATE_RING",
                    "a ring cannot be both emitted and skipped",
                )
            seen.add(key)
            ring = ring_by_key.get(key)
            if ring is None:
                raise CrossSkeletonError(
                    "CROSS_PLATE_MISMATCH",
                    "skipped cross skeleton must reference an existing ring",
                )
            if not set(skipped.hole_contour_ids) <= set(ring.hole_contour_ids):
                raise CrossSkeletonError(
                    "CROSS_CONTOUR_MISMATCH",
                    "skipped cross skeleton hole ids must belong to the ring",
                )

    @property
    def plate_count(self) -> int:
        return len(self.plates)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    def plates_in_band(self, band_id: str) -> tuple[CrossSkeleton, ...]:
        return tuple(record for record in self.plates if record.band_id == band_id)

    def plates_at_z(self, z: int) -> tuple[CrossSkeleton, ...]:
        if not 0 <= z < self.horizontal.bands.depth:
            raise IndexError(f"layer z {z} is outside [0, {self.horizontal.bands.depth})")
        return tuple(record for record in self.plates if record.z == z)

    def plate_by_id(self, plate_id: str) -> CrossSkeleton:
        for record in self.plates:
            if record.plate.id == plate_id:
                return record
        raise KeyError(plate_id)


def extract_cross_skeletons(
    horizontal: HorizontalPlateExtraction,
    config: CrossSkeletonConfig | None = None,
    *,
    start_plate_index: int = 1,
) -> CrossSkeletonExtraction:
    """Create one deterministic plus-shaped blank per horizontal ring plate.

    The largest connected hole of each ring is used. A ring whose hole cannot
    contain the requested arm width plus clearance is recorded as skipped
    rather than silently producing a solid or touching plate.
    """

    settings = config or CrossSkeletonConfig()
    if not _is_int(start_plate_index) or start_plate_index < 1:
        raise CrossSkeletonError(
            "CROSS_INVALID_CONFIG",
            "start_plate_index must be a positive integer",
        )

    plates: list[CrossSkeleton] = []
    skipped: list[SkippedCrossSkeleton] = []
    plate_index = start_plate_index

    for ring in horizontal.plates:
        hole_components = _connected_components(ring.plate.holes)
        if not hole_components:
            continue
        chosen = min(
            hole_components,
            key=lambda cells: (-len(cells), _cell_sort_key(min(cells, key=_cell_sort_key))),
        )
        hole_contour_ids = _hole_contour_ids_for_cells(ring, chosen)
        min_u, min_v, max_u, max_v = _bounding_box(chosen)
        required_span = settings.arm_width_cells + 2 * settings.min_clearance_cells
        if max_u - min_u + 1 < required_span or max_v - min_v + 1 < required_span:
            skipped.append(
                SkippedCrossSkeleton(
                    band_id=ring.band_id,
                    z=ring.z,
                    component_id=ring.component_id,
                    hole_contour_ids=hole_contour_ids,
                    reason=CrossSkeletonSkipReason.HOLE_TOO_SMALL,
                )
            )
            continue

        plus_cells = _plus_cells(
            min_u,
            min_v,
            max_u,
            max_v,
            settings.arm_width_cells,
        )
        if not plus_cells <= chosen:
            skipped.append(
                SkippedCrossSkeleton(
                    band_id=ring.band_id,
                    z=ring.z,
                    component_id=ring.component_id,
                    hole_contour_ids=hole_contour_ids,
                    reason=CrossSkeletonSkipReason.HOLE_SHAPE_UNSUPPORTED,
                )
            )
            continue

        clearance_cells = chosen - plus_cells
        if len(clearance_cells) < settings.min_clearance_cells:
            skipped.append(
                SkippedCrossSkeleton(
                    band_id=ring.band_id,
                    z=ring.z,
                    component_id=ring.component_id,
                    hole_contour_ids=hole_contour_ids,
                    reason=CrossSkeletonSkipReason.HOLE_TOO_SMALL,
                )
            )
            continue

        local_cells = frozenset(
            (u - min_u, v - min_v) for u, v in plus_cells
        )
        color_by_cell = {
            (u - min_u, v - min_v): color
            for u, v in plus_cells
            if (color := ring.plate.color_by_cell.get((u, v))) is not None
        }
        plate = Plate(
            id=f"P{plate_index:02d}",
            kind=PlateKind.CROSS_SKELETON,
            cells=local_cells,
            color_by_cell=color_by_cell,
            holes=frozenset(),
            label=f"{ring.band_id} z={ring.z} {ring.component_id} 十字骨架",
        )
        if not plate.is_4_connected():
            raise CrossSkeletonError(
                "CROSS_DISCONNECTED",
                f"{plate.id} is not 4-connected",
            )
        plates.append(
            CrossSkeleton(
                plate=plate,
                band_id=ring.band_id,
                z=ring.z,
                component_id=ring.component_id,
                hole_contour_ids=hole_contour_ids,
                source_hole_cells=chosen,
                source_cells=plus_cells,
                clearance_cells=clearance_cells,
                arm_width_cells=settings.arm_width_cells,
            )
        )
        plate_index += 1

    return CrossSkeletonExtraction(
        horizontal=horizontal,
        plates=tuple(plates),
        skipped=tuple(skipped),
    )


def _hole_contour_ids_for_cells(
    ring: HorizontalPlate,
    cells: frozenset[Coord2],
) -> tuple[str, ...]:
    if not ring.hole_cells_by_contour:
        return ring.hole_contour_ids
    matching = tuple(
        hole_id
        for hole_id in ring.hole_contour_ids
        if ring.hole_cells_by_contour.get(hole_id, frozenset()) & cells
    )
    if not matching:
        raise CrossSkeletonError(
            "CROSS_CONTOUR_MISMATCH",
            "chosen hole component has no matching contour id",
        )
    return matching


def _plus_cells(
    min_u: int,
    min_v: int,
    max_u: int,
    max_v: int,
    arm_width: int,
) -> frozenset[Coord2]:
    center_u = (min_u + max_u) // 2
    center_v = (min_v + max_v) // 2
    half = arm_width // 2
    cells: set[Coord2] = set()
    for u in range(center_u - half, center_u + half + 1):
        for v in range(min_v, max_v + 1):
            cells.add((u, v))
    for v in range(center_v - half, center_v + half + 1):
        for u in range(min_u, max_u + 1):
            cells.add((u, v))
    return frozenset(cells)


def _connected_components(cells: frozenset[Coord2]) -> tuple[frozenset[Coord2], ...]:
    remaining = set(cells)
    components: list[frozenset[Coord2]] = []
    while remaining:
        start = min(remaining, key=_cell_sort_key)
        remaining.remove(start)
        seen = {start}
        queue: deque[Coord2] = deque([start])
        while queue:
            x, y = queue.popleft()
            for dx, dy in _NEIGHBORS_4:
                neighbor = (x + dx, y + dy)
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    seen.add(neighbor)
                    queue.append(neighbor)
        components.append(frozenset(seen))
    components.sort(key=lambda component: _cell_sort_key(min(component, key=_cell_sort_key)))
    return tuple(components)


def _bounding_box(cells: frozenset[Coord2]) -> tuple[int, int, int, int]:
    return (
        min(u for u, _ in cells),
        min(v for _, v in cells),
        max(u for u, _ in cells),
        max(v for _, v in cells),
    )


def _cell_sort_key(cell: Coord2) -> tuple[int, int]:
    return cell[1], cell[0]


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
