from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from math import inf

from app.domain.bands import LayerBandExtraction
from app.domain.contours import ComponentContours, LayerContourExtraction, LayerContours
from app.domain.layers import BoundaryEdge, Layer, LayerComponent, LayerExtraction
from app.domain.plate import Plate, PlateKind
from app.domain.voxel import Coord2


class VerticalPlateError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class VerticalPlateConfig:
    """Configuration for approximating a perimeter with straight plates.

    A contour is represented by between four and eight independent straight
    plates. ``joint_margin_cells`` is metadata for the future joint generator;
    M3-T5 deliberately does not cut slots into the plate yet.
    """

    min_segments: int = 4
    max_segments: int = 8
    joint_margin_cells: int = 2

    def __post_init__(self) -> None:
        if not _is_int(self.min_segments) or not _is_int(self.max_segments):
            raise VerticalPlateError(
                "VERTICAL_INVALID_CONFIG",
                "segment counts must be integers",
            )
        if not 4 <= self.min_segments <= self.max_segments <= 8:
            raise VerticalPlateError(
                "VERTICAL_INVALID_CONFIG",
                "segment counts must satisfy 4 <= min_segments <= max_segments <= 8",
            )
        if not _is_int(self.joint_margin_cells) or self.joint_margin_cells < 0:
            raise VerticalPlateError(
                "VERTICAL_INVALID_CONFIG",
                "joint_margin_cells must be a non-negative integer",
            )


@dataclass(frozen=True, slots=True)
class VerticalPlate:
    """One rectangular ``(u, v)`` perimeter plate.

    ``segment_index`` is zero-based. The plate is a straight local grid even
    when it approximates a group of consecutive contour edges; ``start_vertex``
    and ``end_vertex`` identify the source span in the horizontal contour.
    """

    plate: Plate
    band_id: str
    component_id: str
    source_z: int
    contour_id: str
    segment_index: int
    segment_count: int
    start_vertex: Coord2
    end_vertex: Coord2
    joint_margin_cells: int = 2
    source_cells: tuple[Coord2, ...] = ()

    def __post_init__(self) -> None:
        if not self.band_id:
            raise VerticalPlateError("VERTICAL_INVALID_RECORD", "band_id is required")
        if not self.component_id:
            raise VerticalPlateError(
                "VERTICAL_INVALID_RECORD",
                "component_id is required",
            )
        if not self.contour_id:
            raise VerticalPlateError("VERTICAL_INVALID_RECORD", "contour_id is required")
        if not _is_int(self.source_z) or self.source_z < 0:
            raise VerticalPlateError(
                "VERTICAL_INVALID_RECORD",
                "source_z must be a non-negative integer",
            )
        if not _is_int(self.segment_index):
            raise VerticalPlateError(
                "VERTICAL_INVALID_RECORD",
                "segment_index must be an integer",
            )
        if not _is_int(self.segment_count) or not 4 <= self.segment_count <= 8:
            raise VerticalPlateError(
                "VERTICAL_SEGMENT_COUNT_INVALID",
                "segment_count must be between four and eight",
            )
        if not 0 <= self.segment_index < self.segment_count:
            raise VerticalPlateError(
                "VERTICAL_SEGMENT_COUNT_INVALID",
                "segment_index must be within [0, segment_count)",
            )
        if not _is_int(self.joint_margin_cells) or self.joint_margin_cells < 0:
            raise VerticalPlateError(
                "VERTICAL_INVALID_RECORD",
                "joint_margin_cells must be a non-negative integer",
            )
        if self.source_cells:
            if len(self.source_cells) != self.plate.width():
                raise VerticalPlateError(
                    "VERTICAL_INVALID_RECORD",
                    "source_cells must contain one cell per plate column",
                )
            if any(not _is_coord(cell) for cell in self.source_cells):
                raise VerticalPlateError(
                    "VERTICAL_INVALID_RECORD",
                    "source_cells must contain integer coordinate pairs",
                )
            if len(set(self.source_cells)) != len(self.source_cells):
                raise VerticalPlateError(
                    "VERTICAL_INVALID_RECORD",
                    "source_cells must be unique",
                )
        if not _is_coord(self.start_vertex) or not _is_coord(self.end_vertex):
            raise VerticalPlateError(
                "VERTICAL_INVALID_RECORD",
                "start_vertex and end_vertex must be integer coordinate pairs",
            )
        if self.start_vertex == self.end_vertex:
            raise VerticalPlateError(
                "VERTICAL_INVALID_CONTOUR",
                "vertical plate span must have non-zero length",
            )
        if self.plate.kind is not PlateKind.PERIMETER:
            raise VerticalPlateError(
                "VERTICAL_KIND_INVALID",
                "vertical plates must use PlateKind.PERIMETER",
            )
        if self.plate.holes:
            raise VerticalPlateError(
                "VERTICAL_INVALID_RECORD",
                "vertical perimeter plates cannot contain inner holes",
            )
        if not self.plate.is_4_connected():
            raise VerticalPlateError(
                "VERTICAL_DISCONNECTED",
                f"{self.plate.id} is not 4-connected",
            )

        width = self.plate.width()
        height = self.plate.height()
        if self.plate.cells != _rectangle_cells(width, height):
            raise VerticalPlateError(
                "VERTICAL_INVALID_RECORD",
                "vertical plate cells must form a rectangle starting at (0, 0)",
            )
        if width < _manhattan(self.start_vertex, self.end_vertex):
            raise VerticalPlateError(
                "VERTICAL_INVALID_RECORD",
                "plate width cannot be shorter than its source span",
            )

    @property
    def id(self) -> str:
        return self.plate.id

    @property
    def z(self) -> int:
        return self.source_z

    @property
    def segment_number(self) -> int:
        return self.segment_index + 1

    @property
    def width(self) -> int:
        return self.plate.width()

    @property
    def height(self) -> int:
        return self.plate.height()

    @property
    def joint_reserved_cells(self) -> frozenset[Coord2]:
        """Return the two end columns reserved for future joints.

        The reservation is metadata only in M3-T5. If a plate is narrower than
        twice the configured margin, the two reservations overlap rather than
        producing cells outside the plate.
        """

        margin = min(self.joint_margin_cells, self.plate.width())
        if margin == 0:
            return frozenset()
        height = self.plate.height()
        return frozenset(
            {(u, v) for u in range(margin) for v in range(height)}
            | {(u, v) for u in range(self.plate.width() - margin, self.plate.width()) for v in range(height)}
        )


@dataclass(frozen=True, slots=True)
class VerticalPlateExtraction:
    bands: LayerBandExtraction
    plates: tuple[VerticalPlate, ...] = ()

    def __post_init__(self) -> None:
        band_by_id = {band.id: band for band in self.bands.bands}
        plate_ids = [record.plate.id for record in self.plates]
        if len(plate_ids) != len(set(plate_ids)):
            raise VerticalPlateError("VERTICAL_DUPLICATE_ID", "plate ids must be unique")

        seen_segments: set[tuple[str, int, str, str, int]] = set()
        records_by_contour: dict[
            tuple[str, int, str, str],
            list[VerticalPlate],
        ] = defaultdict(list)
        for record in self.plates:
            band = band_by_id.get(record.band_id)
            if band is None:
                raise VerticalPlateError(
                    "VERTICAL_BAND_MISMATCH",
                    f"unknown band {record.band_id}",
                )
            if band.is_empty:
                raise VerticalPlateError(
                    "VERTICAL_BAND_MISMATCH",
                    f"plate cannot belong to empty band {record.band_id}",
                )
            if record.source_z != band.z_start:
                raise VerticalPlateError(
                    "VERTICAL_BAND_MISMATCH",
                    "vertical plates must use the representative band start layer",
                )
            if record.plate.height() != band.layer_count:
                raise VerticalPlateError(
                    "VERTICAL_BAND_MISMATCH",
                    "plate height must match the band layer count",
                )
            if not band.z_start <= record.source_z <= band.z_end:
                raise VerticalPlateError(
                    "VERTICAL_BAND_MISMATCH",
                    f"plate z {record.source_z} is outside band {record.band_id}",
                )

            segment_key = (
                record.band_id,
                record.source_z,
                record.component_id,
                record.contour_id,
                record.segment_index,
            )
            if segment_key in seen_segments:
                raise VerticalPlateError(
                    "VERTICAL_DUPLICATE_SEGMENT",
                    "each contour segment may produce at most one plate",
                )
            seen_segments.add(segment_key)
            records_by_contour[
                (
                    record.band_id,
                    record.source_z,
                    record.component_id,
                    record.contour_id,
                )
            ].append(record)

        for records in records_by_contour.values():
            counts = {record.segment_count for record in records}
            if len(counts) != 1:
                raise VerticalPlateError(
                    "VERTICAL_SEGMENT_COUNT_INVALID",
                    "all plates from one contour must have the same segment count",
                )
            segment_count = counts.pop()
            ordered = sorted(records, key=lambda record: record.segment_index)
            if [record.segment_index for record in ordered] != list(range(segment_count)):
                raise VerticalPlateError(
                    "VERTICAL_SEGMENT_COUNT_INVALID",
                    "contour segment indices must be contiguous from zero",
                )
            for left, right in pairwise(ordered):
                if left.end_vertex != right.start_vertex:
                    raise VerticalPlateError(
                        "VERTICAL_INVALID_RECORD",
                        "contour segment endpoints must be contiguous",
                    )
            if ordered[0].start_vertex != ordered[-1].end_vertex:
                raise VerticalPlateError(
                    "VERTICAL_INVALID_RECORD",
                    "contour segments must form a closed loop",
                )

    @property
    def plate_count(self) -> int:
        return len(self.plates)

    @property
    def segment_count(self) -> int:
        return len(self.plates)

    def plates_in_band(self, band_id: str) -> tuple[VerticalPlate, ...]:
        return tuple(record for record in self.plates if record.band_id == band_id)

    def plates_for_band(self, band_id: str) -> tuple[VerticalPlate, ...]:
        return self.plates_in_band(band_id)

    def plates_at_z(self, z: int) -> tuple[VerticalPlate, ...]:
        if not 0 <= z < self.bands.depth:
            raise IndexError(f"layer z {z} is outside [0, {self.bands.depth})")
        return tuple(record for record in self.plates if record.source_z == z)

    def plates_for_component(self, component_id: str) -> tuple[VerticalPlate, ...]:
        return tuple(record for record in self.plates if record.component_id == component_id)

    def plates_for_contour(self, contour_id: str) -> tuple[VerticalPlate, ...]:
        return tuple(record for record in self.plates if record.contour_id == contour_id)

    def segments_for_contour(self, contour_id: str) -> tuple[VerticalPlate, ...]:
        return self.plates_for_contour(contour_id)

    def segments_in_band(self, band_id: str) -> tuple[VerticalPlate, ...]:
        return self.plates_in_band(band_id)

    def plate_by_id(self, plate_id: str) -> VerticalPlate:
        for record in self.plates:
            if record.plate.id == plate_id:
                return record
        raise KeyError(plate_id)


@dataclass(frozen=True, slots=True)
class _ContourEdge:
    start: Coord2
    end: Coord2
    length: int


def extract_vertical_plates(
    layers: LayerExtraction,
    contours: LayerContourExtraction,
    bands: LayerBandExtraction,
    config: VerticalPlateConfig | None = None,
    *,
    start_plate_index: int = 1,
) -> VerticalPlateExtraction:
    """Create straight vertical perimeter plates from outer contours.

    Each non-empty band is represented by its first layer. Every outer contour
    is split into four to eight contiguous spans; each span becomes an
    independent rectangular plate in local ``(u, v)`` coordinates. Inner holes
    are intentionally ignored here because they are handled by horizontal ring
    plates.
    """

    settings = config or VerticalPlateConfig()
    if not _is_int(start_plate_index) or start_plate_index < 1:
        raise VerticalPlateError(
            "VERTICAL_INVALID_CONFIG",
            "start_plate_index must be a positive integer",
        )
    _validate_grids(layers, contours, bands)

    plates: list[VerticalPlate] = []
    plate_index = start_plate_index

    for band in bands.bands:
        if band.is_empty:
            continue
        source_z = band.z_start
        layer = layers.layer_at(source_z)
        contour_layer = contours.layer_at(source_z)
        _validate_component_ids(layer, contour_layer)
        if layer.is_empty:
            raise VerticalPlateError(
                "VERTICAL_BAND_MISMATCH",
                f"non-empty band {band.id} has an empty representative layer",
            )

        for component, component_contours in zip(
            layer.components,
            contour_layer.components,
            strict=True,
        ):
            edges = _contour_edges(component, component_contours)
            segment_count = min(settings.max_segments, len(edges))
            if segment_count < settings.min_segments:
                raise VerticalPlateError(
                    "VERTICAL_SEGMENT_COUNT_INVALID",
                    f"{component.id} has only {len(edges)} straight edges; "
                    f"at least {settings.min_segments} are required",
                )

            groups = _partition_edges(edges, segment_count)
            for segment_index, group in enumerate(groups):
                width = sum(edge.length for edge in group)
                height = band.layer_count
                cells = _rectangle_cells(width, height)
                source_cells = tuple(
                    cell
                    for edge in group
                    for cell in _interior_cells(edge, component.cells)
                )
                if len(source_cells) != width:
                    raise VerticalPlateError(
                        "VERTICAL_INVALID_CONTOUR",
                        "source span length does not match plate width",
                    )
                color_by_cell = _color_columns(
                    source_cells,
                    component,
                    layer,
                    height,
                )
                plate = Plate(
                    id=f"P{plate_index:02d}",
                    kind=PlateKind.PERIMETER,
                    cells=cells,
                    color_by_cell=color_by_cell,
                    holes=frozenset(),
                    label=(
                        f"{band.id} z={source_z} {component.id} "
                        f"垂直围板 {segment_index + 1}/{segment_count}"
                    ),
                )
                if not plate.is_4_connected():
                    raise VerticalPlateError(
                        "VERTICAL_DISCONNECTED",
                        f"{plate.id} is not 4-connected",
                    )
                plates.append(
                    VerticalPlate(
                        plate=plate,
                        band_id=band.id,
                        component_id=component.id,
                        source_z=source_z,
                        contour_id=component_contours.outer.id,
                        segment_index=segment_index,
                        segment_count=segment_count,
                        start_vertex=group[0].start,
                        end_vertex=group[-1].end,
                        joint_margin_cells=settings.joint_margin_cells,
                        source_cells=source_cells,
                    )
                )
                plate_index += 1

    return VerticalPlateExtraction(bands=bands, plates=tuple(plates))


def _validate_grids(
    layers: LayerExtraction,
    contours: LayerContourExtraction,
    bands: LayerBandExtraction,
) -> None:
    expected = (layers.width, layers.height, layers.depth)
    if expected != (contours.width, contours.height, contours.depth):
        raise VerticalPlateError(
            "VERTICAL_GRID_MISMATCH",
            "layer and contour extractions must use the same grid dimensions",
        )
    if expected != (bands.width, bands.height, bands.depth):
        raise VerticalPlateError(
            "VERTICAL_GRID_MISMATCH",
            "layer and band extractions must use the same grid dimensions",
        )


def _validate_component_ids(layer: Layer, contour: LayerContours) -> None:
    layer_component_ids = tuple(component.id for component in layer.components)
    contour_component_ids = tuple(
        component.component_id for component in contour.components
    )
    if layer_component_ids != contour_component_ids:
        raise VerticalPlateError(
            "VERTICAL_COMPONENT_MISMATCH",
            "layer and contour components must have matching ids",
        )
    for component, component_contours in zip(
        layer.components,
        contour.components,
        strict=True,
    ):
        if component.z != component_contours.z:
            raise VerticalPlateError(
                "VERTICAL_COMPONENT_MISMATCH",
                "component and contour z indices must match",
            )


def _contour_edges(
    component: LayerComponent,
    component_contours: ComponentContours,
) -> tuple[_ContourEdge, ...]:
    points = component_contours.outer.simplified_vertices
    if len(points) < 4:
        raise VerticalPlateError(
            "VERTICAL_INVALID_CONTOUR",
            "outer contour needs at least four simplified vertices",
        )
    simplified_area2 = _signed_area2(points)
    if simplified_area2 <= 0:
        raise VerticalPlateError(
            "VERTICAL_INVALID_CONTOUR",
            "outer contour must be clockwise with non-zero area",
        )
    if simplified_area2 != component_contours.outer.area2:
        raise VerticalPlateError(
            "VERTICAL_INVALID_CONTOUR",
            "simplified outer contour must preserve the source area",
        )

    boundary_edges = set(component.boundary_edges)
    seen_unit_edges: set[BoundaryEdge] = set()
    edges: list[_ContourEdge] = []
    for start, end in zip(points, points[1:] + points[:1], strict=True):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        if (dx == 0 and dy == 0) or (dx != 0 and dy != 0):
            raise VerticalPlateError(
                "VERTICAL_INVALID_CONTOUR",
                "simplified contour edges must be non-zero and axis-aligned",
            )
        length = abs(dx) + abs(dy)
        step_x = (dx > 0) - (dx < 0)
        step_y = (dy > 0) - (dy < 0)
        for offset in range(length):
            unit_start = (start[0] + step_x * offset, start[1] + step_y * offset)
            unit_end = (unit_start[0] + step_x, unit_start[1] + step_y)
            unit_edge = BoundaryEdge(unit_start, unit_end)
            if unit_edge not in boundary_edges:
                raise VerticalPlateError(
                    "VERTICAL_INVALID_CONTOUR",
                    "simplified contour must follow component boundary edges",
                )
            if unit_edge in seen_unit_edges:
                raise VerticalPlateError(
                    "VERTICAL_INVALID_CONTOUR",
                    "simplified contour must not repeat boundary edges",
                )
            seen_unit_edges.add(unit_edge)
        edges.append(_ContourEdge(start=start, end=end, length=length))

    if len(edges) < 4:
        raise VerticalPlateError(
            "VERTICAL_INVALID_CONTOUR",
            "outer contour must contain at least four straight edges",
        )
    return tuple(edges)


def _partition_edges(
    edges: Sequence[_ContourEdge],
    segment_count: int,
) -> tuple[tuple[_ContourEdge, ...], ...]:
    if segment_count <= 0 or segment_count > len(edges):
        raise VerticalPlateError(
            "VERTICAL_SEGMENT_COUNT_INVALID",
            "segment count must not exceed the number of contour edges",
        )
    if segment_count == len(edges):
        return tuple((edge,) for edge in edges)

    total_length = sum(edge.length for edge in edges)
    prefix = [0]
    for edge in edges:
        prefix.append(prefix[-1] + edge.length)

    groups: list[tuple[_ContourEdge, ...]] = []
    start = 0
    for group_index in range(segment_count - 1):
        remaining_groups = segment_count - group_index
        max_end = len(edges) - (remaining_groups - 1)
        target = total_length * (group_index + 1) / segment_count
        best_end = start + 1
        best_distance = inf
        for end in range(start + 1, max_end + 1):
            distance = abs(prefix[end] - target)
            if distance < best_distance:
                best_distance = distance
                best_end = end
        groups.append(tuple(edges[start:best_end]))
        start = best_end
    groups.append(tuple(edges[start:]))
    if any(not group for group in groups):
        raise VerticalPlateError(
            "VERTICAL_SEGMENT_COUNT_INVALID",
            "each contour segment must contain at least one edge",
        )
    return tuple(groups)


def _interior_cells(
    edge: _ContourEdge,
    component_cells: frozenset[Coord2],
) -> tuple[Coord2, ...]:
    dx = (edge.end[0] > edge.start[0]) - (edge.end[0] < edge.start[0])
    dy = (edge.end[1] > edge.start[1]) - (edge.end[1] < edge.start[1])
    cells: list[Coord2] = []
    for offset in range(edge.length):
        boundary = (edge.start[0] + dx * offset, edge.start[1] + dy * offset)
        # The edge midpoint plus half of a side normal lands in the adjacent
        # cell. Integer floor division handles the negative half-cell offsets.
        right_cell = (
            boundary[0] + (dx - dy) // 2,
            boundary[1] + (dy + dx) // 2,
        )
        left_cell = (
            boundary[0] + (dx + dy) // 2,
            boundary[1] + (dy - dx) // 2,
        )
        if right_cell in component_cells:
            cells.append(right_cell)
        elif left_cell in component_cells:
            cells.append(left_cell)
        else:
            raise VerticalPlateError(
                "VERTICAL_INVALID_CONTOUR",
                "contour edge must have a solid cell on one side",
            )
    return tuple(cells)


def _color_columns(
    source_cells: Sequence[Coord2],
    component: LayerComponent,
    layer: Layer,
    height: int,
) -> dict[Coord2, str]:
    fallback = _representative_color(component.color_by_cell)
    if fallback is None:
        fallback = _representative_color(layer.color_by_cell)
    color_by_cell: dict[Coord2, str] = {}
    for u, cell in enumerate(source_cells):
        color = component.color_by_cell.get(cell)
        if color is None:
            color = layer.color_by_cell.get(cell)
        if color is None:
            color = fallback
        if color is not None:
            for v in range(height):
                color_by_cell[(u, v)] = color
    return color_by_cell


def _representative_color(color_by_cell: Mapping[Coord2, str]) -> str | None:
    counts: dict[str, int] = {}
    for color in color_by_cell.values():
        counts[color] = counts.get(color, 0) + 1
    if not counts:
        return None
    return min(counts.items(), key=lambda item: (-item[1], item[0]))[0]


def _rectangle_cells(width: int, height: int) -> frozenset[Coord2]:
    return frozenset((u, v) for u in range(width) for v in range(height))


def _manhattan(left: Coord2, right: Coord2) -> int:
    return abs(left[0] - right[0]) + abs(left[1] - right[1])


def _signed_area2(vertices: Sequence[Coord2]) -> int:
    points = tuple(vertices)
    return sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1], strict=True)
    )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_coord(value: object) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and all(_is_int(component) for component in value)
    )
