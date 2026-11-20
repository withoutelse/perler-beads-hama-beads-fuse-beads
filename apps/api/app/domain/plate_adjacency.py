from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise

from app.domain.contours import Contour, LayerContourExtraction
from app.domain.cross_skeletons import CrossSkeleton, CrossSkeletonExtraction
from app.domain.horizontal_plates import HorizontalPlate, HorizontalPlateExtraction
from app.domain.joint import JointDirection, JointType
from app.domain.layers import LayerExtraction
from app.domain.vertical_plates import VerticalPlate, VerticalPlateExtraction
from app.domain.voxel import Coord2, Coord3

_DIRECTION_ORDER = {
    JointDirection.X_POS: 0,
    JointDirection.X_NEG: 1,
    JointDirection.Y_POS: 2,
    JointDirection.Y_NEG: 3,
    JointDirection.Z_POS: 4,
    JointDirection.Z_NEG: 5,
}

_NORMAL_TO_DIRECTION = {
    (1, 0, 0): JointDirection.X_POS,
    (-1, 0, 0): JointDirection.X_NEG,
    (0, 1, 0): JointDirection.Y_POS,
    (0, -1, 0): JointDirection.Y_NEG,
    (0, 0, 1): JointDirection.Z_POS,
    (0, 0, -1): JointDirection.Z_NEG,
}


class PlateAdjacencyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class PlateContactKind(str, Enum):
    """How two plates meet.

    ``FACE`` means the plates share an axis-aligned face. ``SEGMENT_JOINT``
    means two consecutive straight perimeter plates meet at a vertical corner
    and therefore need a corner interlock in M4.
    """

    FACE = "face"
    SEGMENT_JOINT = "segment_joint"


@dataclass(frozen=True, slots=True)
class PlateContactEdge:
    """One physical contact candidate between two plates.

    ``plate_a`` is always lexicographically smaller than ``plate_b`` so the
    undirected graph has a stable canonical representation. ``direction`` is
    the contact normal from ``plate_a`` toward ``plate_b``. ``position`` is the
    zero-based position on plate A's local contact edge; for face contacts it
    is the first contact cell. ``contact_length`` is measured in cells along
    the contact edge (or shared face cells for a stacked horizontal contact).
    """

    id: str
    plate_a: str
    plate_b: str
    kind: PlateContactKind
    direction: JointDirection
    position: int
    contact_length: int
    contact_edge: str
    band_id: str | None = None
    source_z: int | None = None
    contour_id: str | None = None
    segment_index: int | None = None
    joint_type_hint: JointType = JointType.LOAD_BEARING

    def __post_init__(self) -> None:
        if not self.id:
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "contact id is required",
            )
        if not self.plate_a or not self.plate_b:
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "contact plate ids are required",
            )
        if self.plate_a == self.plate_b:
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "contact plates must be different",
            )
        if self.plate_a >= self.plate_b:
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "contact plates must be stored in canonical id order",
            )
        if not isinstance(self.kind, PlateContactKind):
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "contact kind must be a PlateContactKind",
            )
        if not isinstance(self.direction, JointDirection):
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "contact direction must be a JointDirection",
            )
        if not _is_non_negative_int(self.position):
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "contact position must be a non-negative integer",
            )
        if not _is_positive_int(self.contact_length):
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "contact length must be a positive integer",
            )
        if not self.contact_edge:
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "contact_edge is required",
            )
        if self.band_id is not None and not self.band_id:
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "band_id must be non-empty when provided",
            )
        if self.source_z is not None and not _is_non_negative_int(self.source_z):
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "source_z must be a non-negative integer when provided",
            )
        if self.contour_id is not None and not self.contour_id:
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "contour_id must be non-empty when provided",
            )
        if self.segment_index is not None and not _is_non_negative_int(self.segment_index):
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "segment_index must be a non-negative integer when provided",
            )
        if not isinstance(self.joint_type_hint, JointType):
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_CONTACT",
                "joint_type_hint must be a JointType",
            )


@dataclass(frozen=True, slots=True)
class PlateContactGraph:
    """Undirected plate contact graph ``G = (P, E_contact)``."""

    nodes: frozenset[str]
    edges: tuple[PlateContactEdge, ...] = ()

    def __post_init__(self) -> None:
        if any(not node for node in self.nodes):
            raise PlateAdjacencyError(
                "ADJACENCY_INVALID_GRAPH",
                "plate ids must be non-empty",
            )
        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise PlateAdjacencyError(
                "ADJACENCY_DUPLICATE_EDGE",
                "contact edge ids must be unique",
            )
        for edge in self.edges:
            if edge.plate_a not in self.nodes or edge.plate_b not in self.nodes:
                raise PlateAdjacencyError(
                    "ADJACENCY_UNKNOWN_PLATE",
                    "contact edge references an unknown plate",
                )
        keys = [
            (
                edge.plate_a,
                edge.plate_b,
                edge.kind,
                edge.direction,
                edge.position,
                edge.contact_edge,
            )
            for edge in self.edges
        ]
        if len(keys) != len(set(keys)):
            raise PlateAdjacencyError(
                "ADJACENCY_DUPLICATE_EDGE",
                "contact graph contains a duplicate contact edge",
            )
        object.__setattr__(
            self,
            "edges",
            tuple(sorted(self.edges, key=_contact_sort_key)),
        )

    @property
    def plate_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def isolated_plates(self) -> tuple[str, ...]:
        connected = {edge.plate_a for edge in self.edges} | {
            edge.plate_b for edge in self.edges
        }
        return tuple(sorted(node for node in self.nodes if node not in connected))

    def neighbors(self, plate_id: str) -> tuple[str, ...]:
        self._require_node(plate_id)
        return tuple(
            sorted(
                {
                    edge.plate_b if edge.plate_a == plate_id else edge.plate_a
                    for edge in self.edges
                    if plate_id in (edge.plate_a, edge.plate_b)
                }
            )
        )

    def edges_for(self, plate_id: str) -> tuple[PlateContactEdge, ...]:
        self._require_node(plate_id)
        return tuple(
            edge for edge in self.edges if plate_id in (edge.plate_a, edge.plate_b)
        )

    def degree(self, plate_id: str) -> int:
        return len(self.neighbors(plate_id))

    def has_edge(self, plate_a: str, plate_b: str) -> bool:
        self._require_node(plate_a)
        self._require_node(plate_b)
        if plate_a == plate_b:
            return False
        low, high = sorted((plate_a, plate_b))
        return any(
            edge.plate_a == low and edge.plate_b == high for edge in self.edges
        )

    def contact_length(self, plate_a: str, plate_b: str) -> int:
        self._require_node(plate_a)
        self._require_node(plate_b)
        if plate_a == plate_b:
            return 0
        low, high = sorted((plate_a, plate_b))
        return sum(
            edge.contact_length
            for edge in self.edges
            if edge.plate_a == low and edge.plate_b == high
        )

    def connected_components(self) -> tuple[tuple[str, ...], ...]:
        remaining = set(self.nodes)
        components: list[tuple[str, ...]] = []
        while remaining:
            start = min(remaining)
            stack = [start]
            remaining.remove(start)
            component: list[str] = []
            while stack:
                node = stack.pop()
                component.append(node)
                for neighbor in self.neighbors(node):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        stack.append(neighbor)
            components.append(tuple(sorted(component)))
        return tuple(sorted(components, key=lambda component: component[0]))

    def is_connected(self) -> bool:
        return len(self.connected_components()) <= 1

    def _require_node(self, plate_id: str) -> None:
        if plate_id not in self.nodes:
            raise PlateAdjacencyError(
                "ADJACENCY_UNKNOWN_PLATE",
                f"unknown plate {plate_id}",
            )


@dataclass(frozen=True, slots=True)
class PlateAdjacencyExtraction:
    """Contact graph together with the two plate extractions it came from."""

    horizontal: HorizontalPlateExtraction
    vertical: VerticalPlateExtraction
    graph: PlateContactGraph
    cross_skeletons: CrossSkeletonExtraction | None = None

    def __post_init__(self) -> None:
        expected = {
            record.plate.id for record in self.horizontal.plates
        } | {record.plate.id for record in self.vertical.plates}
        if self.cross_skeletons is not None:
            if self.cross_skeletons.horizontal != self.horizontal:
                raise PlateAdjacencyError(
                    "ADJACENCY_CROSS_MISMATCH",
                    "cross skeletons must reference the same horizontal extraction",
                )
            expected |= {
                record.plate.id for record in self.cross_skeletons.plates
            }
        if set(self.graph.nodes) != expected:
            raise PlateAdjacencyError(
                "ADJACENCY_UNKNOWN_PLATE",
                "graph nodes must match the horizontal, vertical and cross plates",
            )

    @property
    def plate_count(self) -> int:
        return self.graph.plate_count

    @property
    def edge_count(self) -> int:
        return self.graph.edge_count

    @property
    def contact_edges(self) -> tuple[PlateContactEdge, ...]:
        return self.graph.edges

    @property
    def isolated_plates(self) -> tuple[str, ...]:
        return self.graph.isolated_plates

    def neighbors(self, plate_id: str) -> tuple[str, ...]:
        return self.graph.neighbors(plate_id)

    def connected_components(self) -> tuple[tuple[str, ...], ...]:
        return self.graph.connected_components()


@dataclass(frozen=True, slots=True)
class _ContactDraft:
    plate_a: str
    plate_b: str
    kind: PlateContactKind
    direction: JointDirection
    position: int
    contact_length: int
    contact_edge: str
    band_id: str | None
    source_z: int | None
    contour_id: str | None
    segment_index: int | None
    joint_type_hint: JointType


def extract_plate_adjacency(
    layers: LayerExtraction,
    contours: LayerContourExtraction,
    horizontal: HorizontalPlateExtraction,
    vertical: VerticalPlateExtraction,
    cross_skeletons: CrossSkeletonExtraction | None = None,
) -> PlateAdjacencyExtraction:
    """Build the deterministic undirected plate contact graph.

    M3-T6 records contact candidates from the source layer bands, contours and
    plate local grids. It intentionally does not create tongue/slot cells;
    M4-T1/T2 resolve those from each contact edge.
    """

    _validate_inputs(layers, contours, horizontal, vertical, cross_skeletons)
    contour_lookup = _contour_lookup(contours)
    component_cells = _component_cells(layers)
    source_cells = {
        record.plate.id: vertical_plate_source_cells(
            record,
            component_cells,
            contour_lookup,
        )
        for record in vertical.plates
    }

    drafts: list[_ContactDraft] = []
    drafts.extend(_segment_joint_contacts(vertical, contour_lookup))
    drafts.extend(_vertical_stack_contacts(vertical, source_cells))
    drafts.extend(_horizontal_stack_contacts(horizontal))
    drafts.extend(_cross_stack_contacts(cross_skeletons))
    drafts.extend(
        _ring_perimeter_contacts(
            horizontal,
            vertical,
            contour_lookup,
            source_cells,
        )
    )

    nodes = frozenset(
        [record.plate.id for record in horizontal.plates]
        + [record.plate.id for record in vertical.plates]
        + (
            [record.plate.id for record in cross_skeletons.plates]
            if cross_skeletons is not None
            else []
        )
    )
    graph = PlateContactGraph(nodes=nodes, edges=_finalize_edges(drafts))
    return PlateAdjacencyExtraction(
        horizontal=horizontal,
        vertical=vertical,
        graph=graph,
        cross_skeletons=cross_skeletons,
    )


def extract_plate_contact_graph(
    layers: LayerExtraction,
    contours: LayerContourExtraction,
    horizontal: HorizontalPlateExtraction,
    vertical: VerticalPlateExtraction,
    cross_skeletons: CrossSkeletonExtraction | None = None,
) -> PlateContactGraph:
    """Convenience wrapper returning only the contact graph."""

    return extract_plate_adjacency(
        layers,
        contours,
        horizontal,
        vertical,
        cross_skeletons,
    ).graph


def _validate_inputs(
    layers: LayerExtraction,
    contours: LayerContourExtraction,
    horizontal: HorizontalPlateExtraction,
    vertical: VerticalPlateExtraction,
    cross_skeletons: CrossSkeletonExtraction | None,
) -> None:
    expected = (layers.width, layers.height, layers.depth)
    for extraction in (contours, horizontal.bands, vertical.bands):
        if (extraction.width, extraction.height, extraction.depth) != expected:
            raise PlateAdjacencyError(
                "ADJACENCY_GRID_MISMATCH",
                "layer, contour and band extractions must use the same grid dimensions",
            )
    if horizontal.bands != vertical.bands:
        raise PlateAdjacencyError(
            "ADJACENCY_BAND_MISMATCH",
            "horizontal and vertical plates must use the same layer bands",
        )
    if cross_skeletons is not None and cross_skeletons.horizontal != horizontal:
        raise PlateAdjacencyError(
            "ADJACENCY_CROSS_MISMATCH",
            "cross skeletons must use the same horizontal extraction",
        )

    for z in range(layers.depth):
        layer = layers.layer_at(z)
        contour_layer = contours.layer_at(z)
        if tuple(component.id for component in layer.components) != tuple(
            component.component_id for component in contour_layer.components
        ):
            raise PlateAdjacencyError(
                "ADJACENCY_CONTOUR_MISMATCH",
                "layer and contour components must have matching ids",
            )

    plate_ids = [record.plate.id for record in horizontal.plates] + [
        record.plate.id for record in vertical.plates
    ]
    if cross_skeletons is not None:
        plate_ids.extend(record.plate.id for record in cross_skeletons.plates)
    if len(plate_ids) != len(set(plate_ids)):
        raise PlateAdjacencyError(
            "ADJACENCY_DUPLICATE_ID",
            "horizontal and vertical plate ids must be unique",
        )


def _contour_lookup(
    contours: LayerContourExtraction,
) -> dict[tuple[int, str], Contour]:
    lookup: dict[tuple[int, str], Contour] = {}
    for layer in contours.layers:
        for component in layer.components:
            for contour in component.contours:
                lookup[(layer.z, contour.id)] = contour
    return lookup


def _component_cells(
    layers: LayerExtraction,
) -> dict[tuple[int, str], frozenset[Coord2]]:
    return {
        (layer.z, component.id): component.cells
        for layer in layers.layers
        for component in layer.components
    }


def vertical_plate_source_cells(
    record: VerticalPlate,
    component_cells: dict[tuple[int, str], frozenset[Coord2]],
    contour_lookup: dict[tuple[int, str], Contour],
) -> tuple[Coord2, ...]:
    contour = contour_lookup.get((record.source_z, record.contour_id))
    if contour is None:
        raise PlateAdjacencyError(
            "ADJACENCY_CONTOUR_MISMATCH",
            f"unknown contour {record.contour_id} at z={record.source_z}",
        )
    cells = component_cells.get((record.source_z, record.component_id))
    if cells is None:
        raise PlateAdjacencyError(
            "ADJACENCY_CONTOUR_MISMATCH",
            f"unknown component {record.component_id} at z={record.source_z}",
        )

    points = contour.simplified_vertices
    try:
        start_index = points.index(record.start_vertex)
    except ValueError as error:
        raise PlateAdjacencyError(
            "ADJACENCY_CONTOUR_MISMATCH",
            "vertical plate start vertex is not on its source contour",
        ) from error
    if record.end_vertex not in points:
        raise PlateAdjacencyError(
            "ADJACENCY_CONTOUR_MISMATCH",
            "vertical plate end vertex is not on its source contour",
        )

    source_cells: list[Coord2] = []
    index = start_index
    while True:
        start = points[index]
        end = points[(index + 1) % len(points)]
        source_cells.extend(_interior_cells_for_edge(start, end, cells))
        if end == record.end_vertex:
            break
        index = (index + 1) % len(points)
        if index == start_index:
            raise PlateAdjacencyError(
                "ADJACENCY_CONTOUR_MISMATCH",
                "vertical plate span does not follow the contour",
            )

    if len(source_cells) != record.width:
        raise PlateAdjacencyError(
            "ADJACENCY_CONTOUR_MISMATCH",
            "vertical plate width does not match its source contour span",
        )
    return tuple(source_cells)


def _interior_cells_for_edge(
    start: Coord2,
    end: Coord2,
    component_cells: frozenset[Coord2],
) -> tuple[Coord2, ...]:
    dx = (end[0] > start[0]) - (end[0] < start[0])
    dy = (end[1] > start[1]) - (end[1] < start[1])
    if (dx == 0) == (dy == 0):
        raise PlateAdjacencyError(
            "ADJACENCY_CONTOUR_MISMATCH",
            "contour edges must be non-zero and axis-aligned",
        )
    length = abs(end[0] - start[0]) + abs(end[1] - start[1])
    cells: list[Coord2] = []
    for offset in range(length):
        boundary = (start[0] + dx * offset, start[1] + dy * offset)
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
            raise PlateAdjacencyError(
                "ADJACENCY_CONTOUR_MISMATCH",
                "contour edge must have a solid cell on one side",
            )
    return tuple(cells)


def _segment_joint_contacts(
    vertical: VerticalPlateExtraction,
    contour_lookup: dict[tuple[int, str], Contour],
) -> list[_ContactDraft]:
    groups: dict[tuple[str, int, str, str], list[VerticalPlate]] = defaultdict(list)
    for record in vertical.plates:
        groups[
            (record.band_id, record.source_z, record.component_id, record.contour_id)
        ].append(record)

    drafts: list[_ContactDraft] = []
    for key in sorted(groups):
        records = sorted(groups[key], key=lambda record: record.segment_index)
        if len(records) < 2:
            continue
        for left, right in zip(records, records[1:] + records[:1], strict=True):
            if left.end_vertex != right.start_vertex:
                raise PlateAdjacencyError(
                    "ADJACENCY_CONTOUR_MISMATCH",
                    "consecutive vertical plates must share a contour vertex",
                )
            contour = contour_lookup.get((left.source_z, left.contour_id))
            if contour is None:
                raise PlateAdjacencyError(
                    "ADJACENCY_CONTOUR_MISMATCH",
                    f"unknown contour {left.contour_id}",
                )
            normal = _outward_normal_at_vertex(
                contour.simplified_vertices,
                right.start_vertex,
            )
            drafts.append(
                _make_contact(
                    plate_x=left.plate.id,
                    plate_y=right.plate.id,
                    kind=PlateContactKind.SEGMENT_JOINT,
                    normal_xy=normal,
                    position_x=left.width - 1,
                    position_y=0,
                    contact_length=min(left.height, right.height),
                    contact_edge=(
                        f"{left.band_id}:{left.contour_id}:"
                        f"{left.segment_index}-{right.segment_index}"
                    ),
                    band_id=left.band_id,
                    source_z=left.source_z,
                    contour_id=left.contour_id,
                    segment_index=left.segment_index,
                )
            )
    return drafts


def _vertical_stack_contacts(
    vertical: VerticalPlateExtraction,
    source_cells: dict[str, tuple[Coord2, ...]],
) -> list[_ContactDraft]:
    band_by_id = {band.id: band for band in vertical.bands.bands}
    groups: dict[tuple[Coord2, Coord2, int, int], list[VerticalPlate]] = defaultdict(list)
    for record in vertical.plates:
        groups[
            (
                record.start_vertex,
                record.end_vertex,
                record.segment_index,
                record.segment_count,
            )
        ].append(record)

    drafts: list[_ContactDraft] = []
    for key in sorted(groups):
        records = sorted(groups[key], key=lambda record: record.source_z)
        for lower, upper in pairwise(records):
            lower_band = band_by_id[lower.band_id]
            upper_band = band_by_id[upper.band_id]
            if lower_band.z_end + 1 != upper_band.z_start:
                continue
            shared = set(source_cells[lower.plate.id]) & set(
                source_cells[upper.plate.id]
            )
            if not shared:
                continue
            drafts.append(
                _make_contact(
                    plate_x=lower.plate.id,
                    plate_y=upper.plate.id,
                    kind=PlateContactKind.FACE,
                    normal_xy=(0, 0, 1),
                    position_x=0,
                    position_y=0,
                    contact_length=len(shared),
                    contact_edge=(
                        f"{lower.band_id}/{upper.band_id}:"
                        f"{lower.start_vertex}->{lower.end_vertex}:"
                        f"{lower.segment_index}"
                    ),
                    band_id=lower.band_id,
                    source_z=lower.source_z,
                    contour_id=lower.contour_id,
                    segment_index=lower.segment_index,
                )
            )
    return drafts


def _horizontal_stack_contacts(
    horizontal: HorizontalPlateExtraction,
) -> list[_ContactDraft]:
    by_z: dict[int, list[HorizontalPlate]] = defaultdict(list)
    for record in horizontal.plates:
        by_z[record.z].append(record)

    drafts: list[_ContactDraft] = []
    for z in sorted(by_z):
        for lower in sorted(by_z[z], key=lambda record: record.plate.id):
            for upper in sorted(by_z.get(z + 1, ()), key=lambda record: record.plate.id):
                shared = lower.plate.cells & upper.plate.cells
                if not shared:
                    continue
                drafts.append(
                    _make_contact(
                        plate_x=lower.plate.id,
                        plate_y=upper.plate.id,
                        kind=PlateContactKind.FACE,
                        normal_xy=(0, 0, 1),
                        position_x=0,
                        position_y=0,
                        contact_length=len(shared),
                        contact_edge=(
                            f"{lower.band_id}/{upper.band_id}:"
                            f"{lower.component_id}/{upper.component_id}:"
                            f"z{lower.z}-z{upper.z}"
                        ),
                        band_id=lower.band_id,
                        source_z=lower.z,
                        contour_id=lower.outer_contour_id,
                        segment_index=None,
                    )
                )
    return drafts


def _cross_stack_contacts(
    cross_skeletons: CrossSkeletonExtraction | None,
) -> list[_ContactDraft]:
    if cross_skeletons is None:
        return []
    band_by_id = {band.id: band for band in cross_skeletons.horizontal.bands.bands}
    groups: dict[tuple[str, frozenset[Coord2]], list[CrossSkeleton]] = defaultdict(list)
    for record in cross_skeletons.plates:
        groups[(_component_key(record.component_id), record.plate.cells)].append(record)

    drafts: list[_ContactDraft] = []
    for key in sorted(
        groups,
        key=lambda item: (item[0], tuple(sorted(item[1]))),
    ):
        records = sorted(groups[key], key=lambda record: record.z)
        for lower, upper in pairwise(records):
            lower_band = band_by_id[lower.band_id]
            upper_band = band_by_id[upper.band_id]
            if lower.band_id == upper.band_id:
                if lower.z + 1 != upper.z:
                    continue
            elif lower_band.z_end + 1 != upper_band.z_start:
                continue
            shared = lower.plate.cells & upper.plate.cells
            if not shared:
                continue
            drafts.append(
                _make_contact(
                    plate_x=lower.plate.id,
                    plate_y=upper.plate.id,
                    kind=PlateContactKind.FACE,
                    normal_xy=(0, 0, 1),
                    position_x=0,
                    position_y=0,
                    contact_length=len(shared),
                    contact_edge=(
                        f"{lower.band_id}/{upper.band_id}:cross:"
                        f"{lower.z}-{upper.z}"
                    ),
                    band_id=lower.band_id,
                    source_z=lower.z,
                    contour_id=None,
                    segment_index=None,
                )
            )
    return drafts


def _ring_perimeter_contacts(
    horizontal: HorizontalPlateExtraction,
    vertical: VerticalPlateExtraction,
    contour_lookup: dict[tuple[int, str], Contour],
    source_cells: dict[str, tuple[Coord2, ...]],
) -> list[_ContactDraft]:
    drafts: list[_ContactDraft] = []
    for ring in horizontal.plates:
        for perimeter in vertical.plates:
            if (
                ring.band_id != perimeter.band_id
                or _component_key(ring.component_id)
                != _component_key(perimeter.component_id)
            ):
                continue
            shared = ring.plate.cells & frozenset(source_cells[perimeter.plate.id])
            if not shared:
                continue
            contour = contour_lookup.get((perimeter.source_z, perimeter.contour_id))
            if contour is None:
                raise PlateAdjacencyError(
                    "ADJACENCY_CONTOUR_MISMATCH",
                    f"unknown contour {perimeter.contour_id}",
                )
            outward = _outward_normal_at_vertex(
                contour.simplified_vertices,
                perimeter.start_vertex,
            )
            inward = (-outward[0], -outward[1], 0)
            drafts.append(
                _make_contact(
                    plate_x=perimeter.plate.id,
                    plate_y=ring.plate.id,
                    kind=PlateContactKind.FACE,
                    normal_xy=inward,
                    position_x=0,
                    position_y=0,
                    contact_length=len(shared),
                    contact_edge=(
                        f"{ring.band_id}:{ring.component_id}:"
                        f"{perimeter.contour_id}:{perimeter.segment_index}:z{ring.z}"
                    ),
                    band_id=ring.band_id,
                    source_z=ring.z,
                    contour_id=perimeter.contour_id,
                    segment_index=perimeter.segment_index,
                )
            )
    return drafts


def _make_contact(
    *,
    plate_x: str,
    plate_y: str,
    kind: PlateContactKind,
    normal_xy: Coord3,
    position_x: int,
    position_y: int,
    contact_length: int,
    contact_edge: str,
    band_id: str | None,
    source_z: int | None,
    contour_id: str | None,
    segment_index: int | None,
) -> _ContactDraft:
    if plate_x == plate_y:
        raise PlateAdjacencyError(
            "ADJACENCY_INVALID_CONTACT",
            "contact plates must be different",
        )
    if plate_x < plate_y:
        plate_a, plate_b = plate_x, plate_y
        direction = _direction_from_normal(normal_xy)
        position = position_x
    else:
        plate_a, plate_b = plate_y, plate_x
        direction = _direction_from_normal(
            (-normal_xy[0], -normal_xy[1], -normal_xy[2])
        )
        position = position_y
    return _ContactDraft(
        plate_a=plate_a,
        plate_b=plate_b,
        kind=kind,
        direction=direction,
        position=position,
        contact_length=contact_length,
        contact_edge=contact_edge,
        band_id=band_id,
        source_z=source_z,
        contour_id=contour_id,
        segment_index=segment_index,
        joint_type_hint=JointType.LOAD_BEARING,
    )


def _finalize_edges(drafts: list[_ContactDraft]) -> tuple[PlateContactEdge, ...]:
    unique: dict[tuple[object, ...], _ContactDraft] = {}
    for draft in drafts:
        key = (
            draft.plate_a,
            draft.plate_b,
            draft.kind,
            draft.direction,
            draft.position,
            draft.contact_edge,
        )
        previous = unique.get(key)
        if previous is not None and previous.contact_length != draft.contact_length:
            raise PlateAdjacencyError(
                "ADJACENCY_DUPLICATE_EDGE",
                "duplicate contact edge has conflicting contact length",
            )
        unique[key] = draft

    ordered = sorted(unique.values(), key=_contact_sort_key)
    return tuple(
        PlateContactEdge(
            id=f"E{index:02d}",
            plate_a=draft.plate_a,
            plate_b=draft.plate_b,
            kind=draft.kind,
            direction=draft.direction,
            position=draft.position,
            contact_length=draft.contact_length,
            contact_edge=draft.contact_edge,
            band_id=draft.band_id,
            source_z=draft.source_z,
            contour_id=draft.contour_id,
            segment_index=draft.segment_index,
            joint_type_hint=draft.joint_type_hint,
        )
        for index, draft in enumerate(ordered, start=1)
    )


def _contact_sort_key(edge: PlateContactEdge | _ContactDraft) -> tuple[object, ...]:
    return (
        edge.plate_a,
        edge.plate_b,
        edge.kind.value,
        _DIRECTION_ORDER[edge.direction],
        edge.position,
        edge.contact_edge,
    )


def _outward_normal_at_vertex(
    vertices: tuple[Coord2, ...],
    vertex: Coord2,
) -> Coord3:
    points = tuple(vertices)
    for start, end in zip(points, points[1:] + points[:1], strict=True):
        if start != vertex:
            continue
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        if (dx == 0) == (dy == 0):
            raise PlateAdjacencyError(
                "ADJACENCY_CONTOUR_MISMATCH",
                "contour edges must be non-zero and axis-aligned",
            )
        step_x = (dx > 0) - (dx < 0)
        step_y = (dy > 0) - (dy < 0)
        return (step_y, -step_x, 0)
    raise PlateAdjacencyError(
        "ADJACENCY_CONTOUR_MISMATCH",
        f"vertex {vertex} is not on the source contour",
    )


def _direction_from_normal(normal: Coord3) -> JointDirection:
    direction = _NORMAL_TO_DIRECTION.get(normal)
    if direction is None:
        raise PlateAdjacencyError(
            "ADJACENCY_INVALID_CONTACT",
            f"contact normal {normal} is not axis-aligned",
        )
    return direction


def _component_key(component_id: str) -> str:
    """Return the z-independent component suffix, e.g. ``C001``."""

    _, separator, suffix = component_id.partition("-")
    return suffix if separator else component_id


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
