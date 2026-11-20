from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from app.domain.voxel import Coord2, VoxelGrid

_NEIGHBORS_4: tuple[Coord2, ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _cell_sort_key(cell: Coord2) -> tuple[int, int]:
    return cell[1], cell[0]


def _edge_sort_key(edge: BoundaryEdge) -> tuple[int, int, int, int]:
    return edge.start[1], edge.start[0], edge.end[1], edge.end[0]


@dataclass(frozen=True, order=True, slots=True)
class BoundaryEdge:
    """A directed unit edge on the integer lattice.

    Edges are emitted clockwise around solid cells in screen coordinates
    (x right, y down). Shared edges between solid cells are omitted.
    """

    start: Coord2
    end: Coord2

    def __post_init__(self) -> None:
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        if abs(dx) + abs(dy) != 1:
            raise ValueError("boundary edge must be a unit axis-aligned segment")


@dataclass(frozen=True, slots=True)
class LayerComponent:
    id: str
    z: int
    cells: frozenset[Coord2]
    color_by_cell: Mapping[Coord2, str] = field(default_factory=dict)
    boundary_cells: frozenset[Coord2] = frozenset()
    boundary_edges: tuple[BoundaryEdge, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("layer component id is required")
        if self.z < 0:
            raise ValueError("layer component z must be non-negative")
        if not self.cells:
            raise ValueError("layer component must contain at least one cell")
        unknown_colors = set(self.color_by_cell) - self.cells
        if unknown_colors:
            raise ValueError("color_by_cell keys must be a subset of component cells")
        if not self.is_4_connected():
            raise ValueError("component cells must be 4-connected")

        expected_boundary_cells = _boundary_cells(self.cells)
        if self.boundary_cells != expected_boundary_cells:
            raise ValueError("boundary_cells must match the component boundary")
        expected_boundary_edges = _boundary_edges(self.cells)
        if tuple(sorted(self.boundary_edges, key=_edge_sort_key)) != expected_boundary_edges:
            raise ValueError("boundary_edges must match the component boundary")

        object.__setattr__(self, "color_by_cell", MappingProxyType(dict(self.color_by_cell)))
        object.__setattr__(self, "boundary_edges", expected_boundary_edges)

    @classmethod
    def from_cells(
        cls,
        *,
        id: str,
        z: int,
        cells: frozenset[Coord2] | set[Coord2] | tuple[Coord2, ...],
        color_by_cell: Mapping[Coord2, str] | None = None,
    ) -> LayerComponent:
        cell_set = frozenset(cells)
        return cls(
            id=id,
            z=z,
            cells=cell_set,
            color_by_cell=color_by_cell or {},
            boundary_cells=_boundary_cells(cell_set),
            boundary_edges=_boundary_edges(cell_set),
        )

    def is_4_connected(self) -> bool:
        if len(self.cells) <= 1:
            return True
        start = min(self.cells, key=_cell_sort_key)
        seen = {start}
        queue: deque[Coord2] = deque([start])
        while queue:
            x, y = queue.popleft()
            for dx, dy in _NEIGHBORS_4:
                neighbor = (x + dx, y + dy)
                if neighbor in self.cells and neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        return len(seen) == len(self.cells)

    def bounding_box(self) -> tuple[int, int, int, int]:
        xs = [x for x, _ in self.cells]
        ys = [y for _, y in self.cells]
        return min(xs), min(ys), max(xs), max(ys)

    def width(self) -> int:
        min_x, _, max_x, _ = self.bounding_box()
        return max_x - min_x + 1

    def height(self) -> int:
        _, min_y, _, max_y = self.bounding_box()
        return max_y - min_y + 1

    @property
    def area(self) -> int:
        return len(self.cells)

    def color_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for color_id in self.color_by_cell.values():
            counts[color_id] = counts.get(color_id, 0) + 1
        return counts


@dataclass(frozen=True, slots=True)
class Layer:
    z: int
    cells: frozenset[Coord2]
    color_by_cell: Mapping[Coord2, str] = field(default_factory=dict)
    components: tuple[LayerComponent, ...] = ()
    boundary_cells: frozenset[Coord2] = frozenset()
    boundary_edges: tuple[BoundaryEdge, ...] = ()

    def __post_init__(self) -> None:
        if self.z < 0:
            raise ValueError("layer z must be non-negative")
        if any(component.z != self.z for component in self.components):
            raise ValueError("component z must match layer z")
        component_cells: set[Coord2] = set()
        for component in self.components:
            component_cells.update(component.cells)
        if frozenset(component_cells) != self.cells:
            raise ValueError("layer components must partition layer cells")

        expected_boundary_cells = _union_boundary_cells(self.components)
        if self.boundary_cells != expected_boundary_cells:
            raise ValueError("boundary_cells must match the union of component boundaries")
        expected_boundary_edges = _union_boundary_edges(self.components)
        if tuple(sorted(self.boundary_edges, key=_edge_sort_key)) != expected_boundary_edges:
            raise ValueError("boundary_edges must match the union of component boundaries")

        unknown_colors = set(self.color_by_cell) - self.cells
        if unknown_colors:
            raise ValueError("color_by_cell keys must be a subset of layer cells")
        object.__setattr__(self, "color_by_cell", MappingProxyType(dict(self.color_by_cell)))
        object.__setattr__(self, "boundary_edges", expected_boundary_edges)

    @property
    def is_empty(self) -> bool:
        return not self.cells

    @property
    def component_count(self) -> int:
        return len(self.components)

    @property
    def area(self) -> int:
        return len(self.cells)

    def color_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for color_id in self.color_by_cell.values():
            counts[color_id] = counts.get(color_id, 0) + 1
        return counts


@dataclass(frozen=True, slots=True)
class LayerExtraction:
    width: int
    height: int
    depth: int
    layers: tuple[Layer, ...]

    def __post_init__(self) -> None:
        if min(self.width, self.height, self.depth) <= 0:
            raise ValueError("layer extraction dimensions must be positive")
        if len(self.layers) != self.depth:
            raise ValueError("layer extraction must contain one layer per z index")
        if tuple(layer.z for layer in self.layers) != tuple(range(self.depth)):
            raise ValueError("layer z indices must be contiguous from zero")

    @property
    def component_count(self) -> int:
        return sum(layer.component_count for layer in self.layers)

    @property
    def boundary_edge_count(self) -> int:
        return sum(len(layer.boundary_edges) for layer in self.layers)

    def layer_at(self, z: int) -> Layer:
        if not 0 <= z < self.depth:
            raise IndexError(f"layer z {z} is outside [0, {self.depth})")
        return self.layers[z]

    def non_empty_layers(self) -> tuple[Layer, ...]:
        return tuple(layer for layer in self.layers if not layer.is_empty)


def extract_horizontal_layers(grid: VoxelGrid) -> LayerExtraction:
    """Extract every z layer and its 4-connected components and boundaries."""
    layers: list[Layer] = []
    for z in range(grid.depth):
        cells = grid.layer(z)
        color_by_cell = {
            (x, y): grid.color_by_voxel[(x, y, z)]
            for x, y in cells
            if (x, y, z) in grid.color_by_voxel
        }
        component_cells = _connected_components(cells)
        components = tuple(
            LayerComponent.from_cells(
                id=f"L{z:03d}-C{index:03d}",
                z=z,
                cells=component,
                color_by_cell={
                    cell: color_by_cell[cell]
                    for cell in component
                    if cell in color_by_cell
                },
            )
            for index, component in enumerate(component_cells, start=1)
        )
        layers.append(
            Layer(
                z=z,
                cells=cells,
                color_by_cell=color_by_cell,
                components=components,
                boundary_cells=_union_boundary_cells(components),
                boundary_edges=_union_boundary_edges(components),
            )
        )
    return LayerExtraction(
        width=grid.width,
        height=grid.height,
        depth=grid.depth,
        layers=tuple(layers),
    )


def _connected_components(cells: frozenset[Coord2]) -> tuple[frozenset[Coord2], ...]:
    remaining = set(cells)
    components: list[frozenset[Coord2]] = []
    while remaining:
        start = min(remaining, key=_cell_sort_key)
        component = _flood_fill_4(start, cells)
        components.append(component)
        remaining.difference_update(component)
    components.sort(key=lambda component: _cell_sort_key(min(component, key=_cell_sort_key)))
    return tuple(components)


def _flood_fill_4(start: Coord2, cells: frozenset[Coord2]) -> frozenset[Coord2]:
    seen = {start}
    queue: deque[Coord2] = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in _NEIGHBORS_4:
            neighbor = (x + dx, y + dy)
            if neighbor in cells and neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return frozenset(seen)


def _boundary_cells(cells: frozenset[Coord2]) -> frozenset[Coord2]:
    return frozenset(
        cell
        for cell in cells
        if any(
            (cell[0] + dx, cell[1] + dy) not in cells
            for dx, dy in _NEIGHBORS_4
        )
    )


def _boundary_edges(cells: frozenset[Coord2]) -> tuple[BoundaryEdge, ...]:
    edges: set[BoundaryEdge] = set()
    for x, y in cells:
        if (x, y - 1) not in cells:
            edges.add(BoundaryEdge((x, y), (x + 1, y)))
        if (x + 1, y) not in cells:
            edges.add(BoundaryEdge((x + 1, y), (x + 1, y + 1)))
        if (x, y + 1) not in cells:
            edges.add(BoundaryEdge((x + 1, y + 1), (x, y + 1)))
        if (x - 1, y) not in cells:
            edges.add(BoundaryEdge((x, y + 1), (x, y)))
    return tuple(sorted(edges, key=_edge_sort_key))


def _union_boundary_cells(components: tuple[LayerComponent, ...]) -> frozenset[Coord2]:
    cells: set[Coord2] = set()
    for component in components:
        cells.update(component.boundary_cells)
    return frozenset(cells)


def _union_boundary_edges(components: tuple[LayerComponent, ...]) -> tuple[BoundaryEdge, ...]:
    edges: set[BoundaryEdge] = set()
    for component in components:
        edges.update(component.boundary_edges)
    return tuple(sorted(edges, key=_edge_sort_key))
