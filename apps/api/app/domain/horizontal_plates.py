from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from app.domain.bands import LayerBandExtraction
from app.domain.contours import LayerContourExtraction, LayerContours
from app.domain.layers import Layer, LayerExtraction
from app.domain.plate import Plate, PlateKind
from app.domain.voxel import Coord2

_NEIGHBORS_4: tuple[Coord2, ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))


class HorizontalPlateError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class HorizontalPlateSkipReason(str, Enum):
    NO_INNER_HOLE = "no_inner_hole"


@dataclass(frozen=True, slots=True)
class HorizontalPlate:
    plate: Plate
    band_id: str
    z: int
    component_id: str
    outer_contour_id: str
    hole_contour_ids: tuple[str, ...] = ()
    hole_cells_by_contour: Mapping[str, frozenset[Coord2]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.band_id:
            raise HorizontalPlateError("PLATE_INVALID_RECORD", "band_id is required")
        if self.z < 0:
            raise HorizontalPlateError("PLATE_INVALID_RECORD", "plate z must be non-negative")
        if not self.component_id:
            raise HorizontalPlateError("PLATE_INVALID_RECORD", "component_id is required")
        if not self.outer_contour_id:
            raise HorizontalPlateError(
                "PLATE_INVALID_RECORD",
                "outer_contour_id is required",
            )
        if self.plate.kind is not PlateKind.RING:
            raise HorizontalPlateError(
                "PLATE_KIND_INVALID",
                "horizontal plates must use PlateKind.RING",
            )
        if not self.plate.holes:
            raise HorizontalPlateError(
                "PLATE_SOLID_SLICE_FORBIDDEN",
                "horizontal plates must contain at least one inner hole",
            )
        if not self.plate.is_4_connected():
            raise HorizontalPlateError(
                "PLATE_DISCONNECTED",
                f"{self.plate.id} is not 4-connected",
            )
        if not self.hole_contour_ids:
            raise HorizontalPlateError(
                "PLATE_INVALID_RECORD",
                "at least one hole contour id is required",
            )
        if len(self.hole_contour_ids) > len(self.plate.holes):
            raise HorizontalPlateError(
                "PLATE_INVALID_RECORD",
                "hole contour ids cannot outnumber hole cells",
            )
        if any(not hole_id for hole_id in self.hole_contour_ids):
            raise HorizontalPlateError(
                "PLATE_INVALID_RECORD",
                "hole contour ids must be non-empty",
            )
        if len(set(self.hole_contour_ids)) != len(self.hole_contour_ids):
            raise HorizontalPlateError(
                "PLATE_INVALID_RECORD",
                "hole contour ids must be unique",
            )

        hole_cells_by_contour = {
            hole_id: frozenset(cells)
            for hole_id, cells in self.hole_cells_by_contour.items()
        }
        if hole_cells_by_contour:
            if set(hole_cells_by_contour) != set(self.hole_contour_ids):
                raise HorizontalPlateError(
                    "PLATE_INVALID_RECORD",
                    "hole cell map keys must match hole contour ids",
                )
            if any(not cells for cells in hole_cells_by_contour.values()):
                raise HorizontalPlateError(
                    "PLATE_INVALID_RECORD",
                    "hole cell map values must be non-empty",
                )
            flattened: set[Coord2] = set()
            for cells in hole_cells_by_contour.values():
                if flattened & cells:
                    raise HorizontalPlateError(
                        "PLATE_HOLE_OVERLAP",
                        "hole cell map values must be disjoint",
                    )
                flattened.update(cells)
            if flattened != set(self.plate.holes):
                raise HorizontalPlateError(
                    "PLATE_CONTOUR_MISMATCH",
                    "hole cell map must partition the plate holes",
                )
        object.__setattr__(
            self,
            "hole_cells_by_contour",
            MappingProxyType(hole_cells_by_contour),
        )

    @property
    def id(self) -> str:
        return self.plate.id

    @property
    def hole_count(self) -> int:
        return len(self.hole_contour_ids)


@dataclass(frozen=True, slots=True)
class SkippedHorizontalComponent:
    band_id: str
    z: int
    component_id: str
    outer_contour_id: str
    reason: HorizontalPlateSkipReason = HorizontalPlateSkipReason.NO_INNER_HOLE

    def __post_init__(self) -> None:
        if not self.band_id or not self.component_id or not self.outer_contour_id:
            raise HorizontalPlateError(
                "PLATE_INVALID_RECORD",
                "skipped component ids must be non-empty",
            )
        if self.z < 0:
            raise HorizontalPlateError(
                "PLATE_INVALID_RECORD",
                "skipped component z must be non-negative",
            )
        if not isinstance(self.reason, HorizontalPlateSkipReason):
            raise HorizontalPlateError(
                "PLATE_INVALID_RECORD",
                "skip reason must be a HorizontalPlateSkipReason",
            )


@dataclass(frozen=True, slots=True)
class HorizontalPlateExtraction:
    bands: LayerBandExtraction
    plates: tuple[HorizontalPlate, ...] = ()
    skipped: tuple[SkippedHorizontalComponent, ...] = ()

    def __post_init__(self) -> None:
        band_by_id = {band.id: band for band in self.bands.bands}
        plate_ids = [record.plate.id for record in self.plates]
        if len(plate_ids) != len(set(plate_ids)):
            raise HorizontalPlateError("PLATE_DUPLICATE_ID", "plate ids must be unique")

        seen: set[tuple[str, int, str]] = set()
        for record in self.plates:
            band = band_by_id.get(record.band_id)
            if band is None:
                raise HorizontalPlateError(
                    "PLATE_BAND_MISMATCH",
                    f"unknown band {record.band_id}",
                )
            if band.is_empty:
                raise HorizontalPlateError(
                    "PLATE_BAND_MISMATCH",
                    f"plate cannot belong to empty band {record.band_id}",
                )
            if not band.z_start <= record.z <= band.z_end:
                raise HorizontalPlateError(
                    "PLATE_BAND_MISMATCH",
                    f"plate z {record.z} is outside band {record.band_id}",
                )
            key = (record.band_id, record.z, record.component_id)
            if key in seen:
                raise HorizontalPlateError(
                    "PLATE_DUPLICATE_COMPONENT",
                    "each component may produce at most one horizontal plate",
                )
            seen.add(key)

        for skipped_record in self.skipped:
            band = band_by_id.get(skipped_record.band_id)
            if band is None:
                raise HorizontalPlateError(
                    "PLATE_BAND_MISMATCH",
                    f"unknown band {skipped_record.band_id}",
                )
            if band.is_empty:
                raise HorizontalPlateError(
                    "PLATE_BAND_MISMATCH",
                    f"skipped component cannot belong to empty band {skipped_record.band_id}",
                )
            if not band.z_start <= skipped_record.z <= band.z_end:
                raise HorizontalPlateError(
                    "PLATE_BAND_MISMATCH",
                    f"skipped component z {skipped_record.z} is outside band "
                    f"{skipped_record.band_id}",
                )
            key = (
                skipped_record.band_id,
                skipped_record.z,
                skipped_record.component_id,
            )
            if key in seen:
                raise HorizontalPlateError(
                    "PLATE_DUPLICATE_COMPONENT",
                    "component cannot be both emitted and skipped",
                )
            seen.add(key)

    @property
    def plate_count(self) -> int:
        return len(self.plates)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    def plates_at_z(self, z: int) -> tuple[HorizontalPlate, ...]:
        if not 0 <= z < self.bands.depth:
            raise IndexError(f"layer z {z} is outside [0, {self.bands.depth})")
        return tuple(record for record in self.plates if record.z == z)

    def plates_in_band(self, band_id: str) -> tuple[HorizontalPlate, ...]:
        return tuple(record for record in self.plates if record.band_id == band_id)

    def plate_by_id(self, plate_id: str) -> HorizontalPlate:
        for record in self.plates:
            if record.plate.id == plate_id:
                return record
        raise KeyError(plate_id)


def extract_horizontal_plates(
    layers: LayerExtraction,
    contours: LayerContourExtraction,
    bands: LayerBandExtraction,
) -> HorizontalPlateExtraction:
    """Create ring plates from outer contours minus inner holes.

    Components without an inner hole are not emitted as horizontal plates,
    because a solid horizontal slice would violate the product route.
    """
    _validate_grids(layers, contours, bands)

    plates: list[HorizontalPlate] = []
    skipped: list[SkippedHorizontalComponent] = []
    plate_index = 1

    for band in bands.bands:
        if band.is_empty:
            continue
        for z in band.layer_indices:
            layer = layers.layer_at(z)
            contour = contours.layer_at(z)
            _validate_component_ids(layer, contour)
            for component, component_contours in zip(
                layer.components,
                contour.components,
                strict=True,
            ):
                outer_cells = _rasterize_rectilinear_polygon(
                    component_contours.outer.vertices
                )
                hole_cells_by_contour: dict[str, frozenset[Coord2]] = {}
                hole_cells: set[Coord2] = set()
                for hole in component_contours.holes:
                    hole_component_cells = frozenset(
                        _rasterize_rectilinear_polygon(hole.vertices)
                    )
                    if hole_cells & hole_component_cells:
                        raise HorizontalPlateError(
                            "PLATE_HOLE_OVERLAP",
                            f"{component.id} has overlapping inner holes",
                        )
                    hole_cells_by_contour[hole.id] = hole_component_cells
                    hole_cells.update(hole_component_cells)

                if not hole_cells <= outer_cells:
                    raise HorizontalPlateError(
                        "PLATE_HOLE_OUTSIDE",
                        f"{component.id} has a hole outside its outer contour",
                    )
                if hole_cells & _boundary_cells(outer_cells):
                    raise HorizontalPlateError(
                        "PLATE_HOLE_OUTSIDE",
                        f"{component.id} has a hole touching the outer boundary",
                    )
                if hole_cells & component.cells:
                    raise HorizontalPlateError(
                        "PLATE_HOLE_OVERLAP",
                        f"{component.id} has a hole overlapping solid cells",
                    )
                expected_cells = outer_cells - hole_cells
                if expected_cells != component.cells:
                    raise HorizontalPlateError(
                        "PLATE_CONTOUR_MISMATCH",
                        f"{component.id} cells do not match outer contour minus holes",
                    )

                if not hole_cells:
                    skipped.append(
                        SkippedHorizontalComponent(
                            band_id=band.id,
                            z=z,
                            component_id=component.id,
                            outer_contour_id=component_contours.outer.id,
                        )
                    )
                    continue

                plate = Plate(
                    id=f"P{plate_index:02d}",
                    kind=PlateKind.RING,
                    cells=component.cells,
                    color_by_cell=component.color_by_cell,
                    holes=frozenset(hole_cells),
                    label=f"{band.id} z={z} {component.id} 水平环片",
                )
                if not plate.is_4_connected():
                    raise HorizontalPlateError(
                        "PLATE_DISCONNECTED",
                        f"{plate.id} is not 4-connected",
                    )
                plates.append(
                    HorizontalPlate(
                        plate=plate,
                        band_id=band.id,
                        z=z,
                        component_id=component.id,
                        outer_contour_id=component_contours.outer.id,
                        hole_contour_ids=tuple(
                            hole.id for hole in component_contours.holes
                        ),
                        hole_cells_by_contour=hole_cells_by_contour,
                    )
                )
                plate_index += 1

    return HorizontalPlateExtraction(
        bands=bands,
        plates=tuple(plates),
        skipped=tuple(skipped),
    )


def _validate_grids(
    layers: LayerExtraction,
    contours: LayerContourExtraction,
    bands: LayerBandExtraction,
) -> None:
    expected = (layers.width, layers.height, layers.depth)
    if expected != (contours.width, contours.height, contours.depth):
        raise HorizontalPlateError(
            "PLATE_GRID_MISMATCH",
            "layer and contour extractions must use the same grid dimensions",
        )
    if expected != (bands.width, bands.height, bands.depth):
        raise HorizontalPlateError(
            "PLATE_GRID_MISMATCH",
            "layer and band extractions must use the same grid dimensions",
        )


def _validate_component_ids(
    layer: Layer,
    contour: LayerContours,
) -> None:
    layer_component_ids = tuple(component.id for component in layer.components)
    contour_component_ids = tuple(
        component.component_id for component in contour.components
    )
    if layer_component_ids != contour_component_ids:
        raise HorizontalPlateError(
            "PLATE_COMPONENT_MISMATCH",
            "layer and contour components must have matching ids",
        )


def _boundary_cells(cells: frozenset[Coord2]) -> frozenset[Coord2]:
    return frozenset(
        cell
        for cell in cells
        if any(
            (cell[0] + dx, cell[1] + dy) not in cells
            for dx, dy in _NEIGHBORS_4
        )
    )


def _rasterize_rectilinear_polygon(vertices: Sequence[Coord2]) -> frozenset[Coord2]:
    points = tuple(vertices)
    if len(points) < 4:
        raise HorizontalPlateError(
            "PLATE_INVALID_CONTOUR",
            "contour needs at least four vertices",
        )
    edges = tuple(zip(points, points[1:] + points[:1], strict=True))
    for (x1, y1), (x2, y2) in edges:
        if x1 != x2 and y1 != y2:
            raise HorizontalPlateError(
                "PLATE_INVALID_CONTOUR",
                "contour edges must be axis-aligned",
            )

    cells: set[Coord2] = set()
    min_y = min(y for _, y in points)
    max_y = max(y for _, y in points)
    for y in range(min_y, max_y):
        scan_y = y + 0.5
        intersections: list[int] = []
        for (x1, y1), (x2, y2) in edges:
            if x1 != x2:
                continue
            if min(y1, y2) < scan_y < max(y1, y2):
                intersections.append(x1)
        intersections.sort()
        if len(intersections) % 2 != 0:
            raise HorizontalPlateError(
                "PLATE_INVALID_CONTOUR",
                "scanline intersections must form pairs",
            )
        for start, end in zip(intersections[::2], intersections[1::2], strict=True):
            if start >= end:
                raise HorizontalPlateError(
                    "PLATE_INVALID_CONTOUR",
                    "scanline interval is degenerate",
                )
            for x in range(start, end):
                cells.add((x, y))

    if not cells:
        raise HorizontalPlateError("PLATE_EMPTY_CONTOUR", "contour has no cells")
    return frozenset(cells)
