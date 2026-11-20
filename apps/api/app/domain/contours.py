from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise

from app.domain.layers import BoundaryEdge, Layer, LayerComponent, LayerExtraction
from app.domain.voxel import Coord2

_DIRECTION_INDEX = {
    (1, 0): 0,
    (0, 1): 1,
    (-1, 0): 2,
    (0, -1): 3,
}
_TURN_RANK = {1: 0, 0: 1, 3: 2, 2: 3}


class ContourError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ContourKind(str, Enum):
    OUTER = "outer"
    HOLE = "hole"


@dataclass(frozen=True, slots=True)
class Contour:
    id: str
    z: int
    component_id: str
    kind: ContourKind
    vertices: tuple[Coord2, ...]
    simplified_vertices: tuple[Coord2, ...]

    def __post_init__(self) -> None:
        if not self.id:
            raise ContourError("CONTOUR_INVALID_ID", "contour id is required")
        if self.z < 0:
            raise ContourError("CONTOUR_INVALID_Z", "contour z must be non-negative")
        if not self.component_id:
            raise ContourError("CONTOUR_INVALID_COMPONENT", "component_id is required")
        _validate_closed_vertices(self.vertices, code="CONTOUR_INVALID_VERTICES")
        _validate_closed_vertices(
            self.simplified_vertices,
            code="CONTOUR_INVALID_SIMPLIFICATION",
        )
        area2 = _signed_area2(self.vertices)
        if area2 == 0:
            raise ContourError("CONTOUR_DEGENERATE", "contour area must be non-zero")
        if self.kind is ContourKind.OUTER and area2 <= 0:
            raise ContourError("CONTOUR_OUTER_ORIENTATION", "outer contour must be clockwise")
        if self.kind is ContourKind.HOLE and area2 >= 0:
            raise ContourError("CONTOUR_HOLE_ORIENTATION", "hole contour must be counter-clockwise")

    @property
    def area2(self) -> int:
        return _signed_area2(self.vertices)

    @property
    def area(self) -> float:
        return abs(self.area2) / 2.0

    @property
    def edge_count(self) -> int:
        return len(self.vertices)

    @property
    def is_outer(self) -> bool:
        return self.kind is ContourKind.OUTER

    @property
    def is_hole(self) -> bool:
        return self.kind is ContourKind.HOLE

    def closed_vertices(self) -> tuple[Coord2, ...]:
        return self.vertices + (self.vertices[0],)

    def simplified_closed_vertices(self) -> tuple[Coord2, ...]:
        return self.simplified_vertices + (self.simplified_vertices[0],)

    def bounding_box(self) -> tuple[int, int, int, int]:
        xs = [x for x, _ in self.vertices]
        ys = [y for _, y in self.vertices]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass(frozen=True, slots=True)
class ComponentContours:
    component_id: str
    z: int
    outer: Contour
    holes: tuple[Contour, ...] = ()

    def __post_init__(self) -> None:
        if not self.component_id:
            raise ContourError("CONTOUR_INVALID_COMPONENT", "component_id is required")
        if self.z < 0:
            raise ContourError("CONTOUR_INVALID_Z", "component z must be non-negative")
        if self.outer.kind is not ContourKind.OUTER:
            raise ContourError("CONTOUR_OUTER_REQUIRED", "component must have an outer contour")
        if self.outer.component_id != self.component_id or self.outer.z != self.z:
            raise ContourError("CONTOUR_COMPONENT_MISMATCH", "outer contour does not match component")
        for hole in self.holes:
            if hole.kind is not ContourKind.HOLE:
                raise ContourError("CONTOUR_HOLE_REQUIRED", "component holes must be hole contours")
            if hole.component_id != self.component_id or hole.z != self.z:
                raise ContourError(
                    "CONTOUR_COMPONENT_MISMATCH",
                    "hole contour does not match component",
                )
        contour_ids = [contour.id for contour in self.contours]
        if len(contour_ids) != len(set(contour_ids)):
            raise ContourError("CONTOUR_DUPLICATE_ID", "contour ids must be unique")

    @property
    def contours(self) -> tuple[Contour, ...]:
        return (self.outer, *self.holes)

    @property
    def contour_count(self) -> int:
        return 1 + len(self.holes)

    @property
    def hole_count(self) -> int:
        return len(self.holes)

    @property
    def area(self) -> float:
        return self.outer.area - sum(hole.area for hole in self.holes)


@dataclass(frozen=True, slots=True)
class LayerContours:
    z: int
    components: tuple[ComponentContours, ...] = ()

    def __post_init__(self) -> None:
        if self.z < 0:
            raise ContourError("CONTOUR_INVALID_Z", "layer z must be non-negative")
        if any(component.z != self.z for component in self.components):
            raise ContourError("CONTOUR_LAYER_MISMATCH", "component z must match layer z")
        component_ids = [component.component_id for component in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ContourError("CONTOUR_DUPLICATE_COMPONENT", "component ids must be unique")

    @property
    def contours(self) -> tuple[Contour, ...]:
        return tuple(contour for component in self.components for contour in component.contours)

    @property
    def contour_count(self) -> int:
        return len(self.contours)

    @property
    def hole_count(self) -> int:
        return sum(component.hole_count for component in self.components)

    @property
    def area(self) -> float:
        return sum(component.area for component in self.components)


@dataclass(frozen=True, slots=True)
class LayerContourExtraction:
    width: int
    height: int
    depth: int
    layers: tuple[LayerContours, ...]

    def __post_init__(self) -> None:
        if min(self.width, self.height, self.depth) <= 0:
            raise ContourError("CONTOUR_INVALID_GRID", "contour extraction dimensions must be positive")
        if len(self.layers) != self.depth:
            raise ContourError("CONTOUR_INVALID_LAYERS", "one contour layer is required per z index")
        if tuple(layer.z for layer in self.layers) != tuple(range(self.depth)):
            raise ContourError("CONTOUR_INVALID_LAYERS", "layer z indices must be contiguous")

    @property
    def contour_count(self) -> int:
        return sum(layer.contour_count for layer in self.layers)

    @property
    def hole_count(self) -> int:
        return sum(layer.hole_count for layer in self.layers)

    @property
    def area(self) -> float:
        return sum(layer.area for layer in self.layers)

    def layer_at(self, z: int) -> LayerContours:
        if not 0 <= z < self.depth:
            raise IndexError(f"layer z {z} is outside [0, {self.depth})")
        return self.layers[z]

    def non_empty_layers(self) -> tuple[LayerContours, ...]:
        return tuple(layer for layer in self.layers if layer.components)


def trace_horizontal_contours(extraction: LayerExtraction) -> LayerContourExtraction:
    """Trace every layer component boundary into closed rectilinear contours."""
    return LayerContourExtraction(
        width=extraction.width,
        height=extraction.height,
        depth=extraction.depth,
        layers=tuple(trace_layer_contours(layer) for layer in extraction.layers),
    )


def trace_layer_contours(layer: Layer) -> LayerContours:
    return LayerContours(
        z=layer.z,
        components=tuple(trace_component_contours(component) for component in layer.components),
    )


def trace_component_contours(component: LayerComponent) -> ComponentContours:
    loops = _trace_boundary_loops(component.boundary_edges)
    records: list[tuple[tuple[Coord2, ...], tuple[Coord2, ...], int]] = []
    for vertices in loops:
        area2 = _signed_area2(vertices)
        if area2 == 0:
            raise ContourError("CONTOUR_DEGENERATE", "boundary loop has zero area")
        simplified = simplify_rectilinear_polygon(vertices)
        records.append((vertices, simplified, area2))

    outer_records = [record for record in records if record[2] > 0]
    if len(outer_records) != 1:
        raise ContourError(
            "CONTOUR_OUTER_COUNT_INVALID",
            "a 4-connected component must have exactly one outer contour",
        )
    outer_vertices, outer_simplified, _ = outer_records[0]
    outer = Contour(
        id=f"{component.id}-O",
        z=component.z,
        component_id=component.id,
        kind=ContourKind.OUTER,
        vertices=outer_vertices,
        simplified_vertices=outer_simplified,
    )

    hole_records = [record for record in records if record[2] < 0]
    hole_records.sort(key=lambda record: _min_yx(record[0]))
    holes: list[Contour] = []
    for index, (vertices, simplified, _) in enumerate(hole_records, start=1):
        if not _point_in_polygon(_interior_point(vertices), outer_vertices):
            raise ContourError("CONTOUR_HOLE_OUTSIDE", "hole contour must be inside its outer contour")
        holes.append(
            Contour(
                id=f"{component.id}-H{index:03d}",
                z=component.z,
                component_id=component.id,
                kind=ContourKind.HOLE,
                vertices=vertices,
                simplified_vertices=simplified,
            )
        )
    return ComponentContours(
        component_id=component.id,
        z=component.z,
        outer=outer,
        holes=tuple(holes),
    )


def simplify_rectilinear_polygon(vertices: Sequence[Coord2]) -> tuple[Coord2, ...]:
    """Remove duplicate and collinear vertices while preserving the closed polygon."""
    points: list[Coord2] = []
    for point in vertices:
        if not points or point != points[-1]:
            points.append(point)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) < 4:
        raise ContourError("CONTOUR_INVALID_VERTICES", "contour needs at least four vertices")

    changed = True
    while changed and len(points) > 3:
        changed = False
        simplified: list[Coord2] = []
        count = len(points)
        for index, current in enumerate(points):
            previous = points[index - 1]
            following = points[(index + 1) % count]
            if _is_collinear_between(previous, current, following):
                changed = True
            else:
                simplified.append(current)
        points = simplified
    if len(points) < 4:
        raise ContourError("CONTOUR_DEGENERATE", "contour collapsed during simplification")
    return tuple(points)


def _trace_boundary_loops(edges: tuple[BoundaryEdge, ...]) -> tuple[tuple[Coord2, ...], ...]:
    if not edges:
        raise ContourError("CONTOUR_EMPTY_BOUNDARY", "component has no boundary edges")
    outgoing: dict[Coord2, list[BoundaryEdge]] = defaultdict(list)
    for edge in edges:
        outgoing[edge.start].append(edge)
    for candidates in outgoing.values():
        candidates.sort(key=_edge_sort_key)

    unused = set(edges)
    loops: list[tuple[Coord2, ...]] = []
    while unused:
        start_edge = min(unused, key=_edge_sort_key)
        loop: list[Coord2] = [start_edge.start]
        current = start_edge
        unused.remove(start_edge)
        guard = 0
        while True:
            loop.append(current.end)
            if current.end == start_edge.start:
                break
            candidates = [edge for edge in outgoing[current.end] if edge in unused]
            if not candidates:
                raise ContourError("CONTOUR_OPEN_BOUNDARY", "boundary edges do not form a closed loop")
            current = _choose_next_edge(current, candidates)
            unused.remove(current)
            guard += 1
            if guard > len(edges):
                raise ContourError("CONTOUR_TRACE_LOOP", "boundary tracing did not terminate")
        vertices = tuple(loop[:-1])
        if len(vertices) < 4:
            raise ContourError("CONTOUR_INVALID_VERTICES", "boundary loop needs at least four vertices")
        loops.append(vertices)
    return tuple(loops)


def _choose_next_edge(
    incoming: BoundaryEdge,
    candidates: Sequence[BoundaryEdge],
) -> BoundaryEdge:
    incoming_direction = (
        incoming.end[0] - incoming.start[0],
        incoming.end[1] - incoming.start[1],
    )
    incoming_index = _DIRECTION_INDEX[incoming_direction]

    def rank(edge: BoundaryEdge) -> tuple[int, int, int, int, int]:
        direction = (edge.end[0] - edge.start[0], edge.end[1] - edge.start[1])
        turn = (_DIRECTION_INDEX[direction] - incoming_index) % 4
        return (_TURN_RANK[turn], *_edge_sort_key(edge))

    return min(candidates, key=rank)


def _validate_closed_vertices(vertices: tuple[Coord2, ...], *, code: str) -> None:
    if len(vertices) < 4:
        raise ContourError(code, "contour needs at least four vertices")
    if vertices[0] == vertices[-1]:
        raise ContourError(code, "contour vertices must omit the repeated closing vertex")
    if any(left == right for left, right in pairwise(vertices)):
        raise ContourError(code, "contour vertices must not repeat consecutively")


def _signed_area2(vertices: Sequence[Coord2]) -> int:
    points = tuple(vertices)
    return sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1], strict=True)
    )


def _is_collinear_between(previous: Coord2, current: Coord2, following: Coord2) -> bool:
    if previous[0] == current[0] == following[0]:
        return min(previous[1], following[1]) <= current[1] <= max(previous[1], following[1])
    if previous[1] == current[1] == following[1]:
        return min(previous[0], following[0]) <= current[0] <= max(previous[0], following[0])
    return False


def _interior_point(vertices: Sequence[Coord2]) -> tuple[float, float]:
    start = vertices[0]
    end = vertices[1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if abs(dx) + abs(dy) != 1:
        raise ContourError("CONTOUR_INVALID_VERTICES", "contour edge must be axis-aligned")
    midpoint_x = (start[0] + end[0]) / 2.0
    midpoint_y = (start[1] + end[1]) / 2.0
    return midpoint_x + dy / 2.0, midpoint_y - dx / 2.0


def _point_in_polygon(point: tuple[float, float], polygon: Sequence[Coord2]) -> bool:
    x, y = point
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        if _point_on_segment(x, y, x1, y1, x2, y2):
            return True
        if (y1 > y) != (y2 > y):
            intersection_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if intersection_x > x:
                inside = not inside
    return inside


def _point_on_segment(
    x: float,
    y: float,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> bool:
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if abs(cross) > 1e-9:
        return False
    return min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2)


def _edge_sort_key(edge: BoundaryEdge) -> tuple[int, int, int, int]:
    return edge.start[1], edge.start[0], edge.end[1], edge.end[0]


def _min_yx(vertices: Sequence[Coord2]) -> tuple[int, int]:
    return min(y for _, y in vertices), min(x for x, _ in vertices)
