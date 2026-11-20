from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.bands import LayerBandConfig, LayerBandExtraction, detect_layer_bands
from app.domain.contours import LayerContourExtraction, trace_horizontal_contours
from app.domain.cross_skeletons import (
    CrossSkeletonConfig,
    CrossSkeletonExtraction,
    extract_cross_skeletons,
)
from app.domain.horizontal_plates import (
    HorizontalPlateExtraction,
    extract_horizontal_plates,
)
from app.domain.layers import LayerExtraction, extract_horizontal_layers
from app.domain.plate import Plate, PlateKind
from app.domain.plate_adjacency import (
    PlateAdjacencyExtraction,
    PlateContactEdge,
    extract_plate_adjacency,
)
from app.domain.vertical_plates import (
    VerticalPlateConfig,
    VerticalPlateExtraction,
    extract_vertical_plates,
)
from app.domain.voxel import VoxelGrid


class DecompositionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class DecompositionConfig:
    band: LayerBandConfig = field(default_factory=LayerBandConfig)
    vertical: VerticalPlateConfig = field(default_factory=VerticalPlateConfig)
    cross_skeleton: CrossSkeletonConfig = field(default_factory=CrossSkeletonConfig)


@dataclass(frozen=True, slots=True)
class DecompositionExtraction:
    """Complete M3 decomposition result for one voxel grid."""

    layers: LayerExtraction
    contours: LayerContourExtraction
    bands: LayerBandExtraction
    horizontal: HorizontalPlateExtraction
    vertical: VerticalPlateExtraction
    cross_skeletons: CrossSkeletonExtraction
    adjacency: PlateAdjacencyExtraction

    def __post_init__(self) -> None:
        if self.horizontal.bands != self.bands:
            raise DecompositionError(
                "DECOMPOSITION_BAND_MISMATCH",
                "horizontal plates must use the decomposition bands",
            )
        if self.vertical.bands != self.bands:
            raise DecompositionError(
                "DECOMPOSITION_BAND_MISMATCH",
                "vertical plates must use the decomposition bands",
            )
        if self.cross_skeletons.horizontal != self.horizontal:
            raise DecompositionError(
                "DECOMPOSITION_CROSS_MISMATCH",
                "cross skeletons must use the decomposition horizontal plates",
            )
        if self.adjacency.horizontal != self.horizontal:
            raise DecompositionError(
                "DECOMPOSITION_ADJACENCY_MISMATCH",
                "adjacency must use the decomposition horizontal plates",
            )
        if self.adjacency.vertical != self.vertical:
            raise DecompositionError(
                "DECOMPOSITION_ADJACENCY_MISMATCH",
                "adjacency must use the decomposition vertical plates",
            )
        if self.adjacency.cross_skeletons != self.cross_skeletons:
            raise DecompositionError(
                "DECOMPOSITION_ADJACENCY_MISMATCH",
                "adjacency must use the decomposition cross skeletons",
            )

    @property
    def plates(self) -> tuple[Plate, ...]:
        return tuple(
            [record.plate for record in self.horizontal.plates]
            + [record.plate for record in self.vertical.plates]
            + [record.plate for record in self.cross_skeletons.plates]
        )

    @property
    def plate_count(self) -> int:
        return len(self.plates)

    @property
    def contact_edges(self) -> tuple[PlateContactEdge, ...]:
        return self.adjacency.contact_edges

    def plates_by_kind(self, kind: PlateKind) -> tuple[Plate, ...]:
        return tuple(plate for plate in self.plates if plate.kind is kind)

    def plate_by_id(self, plate_id: str) -> Plate:
        for plate in self.plates:
            if plate.id == plate_id:
                return plate
        raise KeyError(plate_id)


def decompose_voxel_grid(
    grid: VoxelGrid,
    config: DecompositionConfig | None = None,
) -> DecompositionExtraction:
    """Run M3-T1 through M3-T7 deterministically for one voxel grid."""

    settings = config or DecompositionConfig()
    layers = extract_horizontal_layers(grid)
    contours = trace_horizontal_contours(layers)
    bands = detect_layer_bands(layers, contours, settings.band)
    horizontal = extract_horizontal_plates(layers, contours, bands)
    vertical = extract_vertical_plates(
        layers,
        contours,
        bands,
        settings.vertical,
        start_plate_index=horizontal.plate_count + 1,
    )
    cross_skeletons = extract_cross_skeletons(
        horizontal,
        settings.cross_skeleton,
        start_plate_index=horizontal.plate_count + vertical.plate_count + 1,
    )
    adjacency = extract_plate_adjacency(
        layers,
        contours,
        horizontal,
        vertical,
        cross_skeletons,
    )
    return DecompositionExtraction(
        layers=layers,
        contours=contours,
        bands=bands,
        horizontal=horizontal,
        vertical=vertical,
        cross_skeletons=cross_skeletons,
        adjacency=adjacency,
    )
