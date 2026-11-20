from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from app.domain.contours import LayerContourExtraction, LayerContours
from app.domain.layers import Layer, LayerExtraction

_COLOR_SUM_TOLERANCE = 1e-9


class BandError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class BandSplitReason(str, Enum):
    EMPTY_LAYER = "empty_layer"
    COMPONENT_COUNT_CHANGE = "component_count_change"
    HOLE_COUNT_CHANGE = "hole_count_change"
    COLOR_DISTANCE = "color_distance"
    AREA_CHANGE = "area_change"
    RADIUS_CHANGE = "radius_change"


_REASON_ORDER = {reason: index for index, reason in enumerate(BandSplitReason)}


@dataclass(frozen=True, slots=True)
class LayerBandConfig:
    """Thresholds for deterministic layer-band splitting.

    Color distance and area/radius changes are normalized to [0, 1]. A split
    happens only when the measured value is strictly greater than its threshold.
    """

    color_distance_threshold: float = 0.20
    area_change_threshold: float = 0.10
    radius_change_threshold: float = 0.10
    hole_count_change_threshold: int = 0
    component_count_change_threshold: int = 0

    def __post_init__(self) -> None:
        _validate_unit_threshold(
            "color_distance_threshold",
            self.color_distance_threshold,
        )
        _validate_unit_threshold(
            "area_change_threshold",
            self.area_change_threshold,
        )
        _validate_unit_threshold(
            "radius_change_threshold",
            self.radius_change_threshold,
        )
        _validate_count_threshold(
            "hole_count_change_threshold",
            self.hole_count_change_threshold,
        )
        _validate_count_threshold(
            "component_count_change_threshold",
            self.component_count_change_threshold,
        )


@dataclass(frozen=True, slots=True)
class LayerBandMetrics:
    z: int
    cell_count: int
    outer_area: float
    equivalent_radius: float
    hole_count: int
    component_count: int
    color_histogram: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.z < 0:
            raise BandError("BAND_INVALID_METRICS", "band metrics z must be non-negative")
        if self.cell_count < 0:
            raise BandError("BAND_INVALID_METRICS", "cell_count must be non-negative")
        if not math.isfinite(self.outer_area) or self.outer_area < 0.0:
            raise BandError("BAND_INVALID_METRICS", "outer_area must be finite and non-negative")
        if not math.isfinite(self.equivalent_radius) or self.equivalent_radius < 0.0:
            raise BandError(
                "BAND_INVALID_METRICS",
                "equivalent_radius must be finite and non-negative",
            )
        if self.hole_count < 0:
            raise BandError("BAND_INVALID_METRICS", "hole_count must be non-negative")
        if self.component_count < 0:
            raise BandError("BAND_INVALID_METRICS", "component_count must be non-negative")
        if self.component_count > self.cell_count:
            raise BandError(
                "BAND_INVALID_METRICS",
                "component_count cannot exceed cell_count",
            )

        histogram = dict(self.color_histogram)
        for color_id, fraction in histogram.items():
            if not color_id:
                raise BandError("BAND_INVALID_METRICS", "color ids must be non-empty")
            if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
                raise BandError(
                    "BAND_INVALID_METRICS",
                    "color histogram fractions must be finite and within [0, 1]",
                )
        if sum(histogram.values()) > 1.0 + _COLOR_SUM_TOLERANCE:
            raise BandError(
                "BAND_INVALID_METRICS",
                "color histogram fractions cannot sum above one",
            )

        if self.cell_count == 0:
            if self.outer_area != 0.0 or self.equivalent_radius != 0.0:
                raise BandError(
                    "BAND_INVALID_METRICS",
                    "empty layers must have zero area and radius",
                )
            if self.hole_count != 0 or self.component_count != 0 or histogram:
                raise BandError(
                    "BAND_INVALID_METRICS",
                    "empty layers cannot have holes, components or colors",
                )
        elif self.outer_area <= 0.0 or self.component_count == 0:
            raise BandError(
                "BAND_INVALID_METRICS",
                "non-empty layers require positive outer area and components",
            )

        object.__setattr__(
            self,
            "color_histogram",
            MappingProxyType(dict(sorted(histogram.items()))),
        )

    @property
    def uncolored_fraction(self) -> float:
        if self.cell_count == 0:
            return 0.0
        return max(0.0, 1.0 - sum(self.color_histogram.values()))


@dataclass(frozen=True, slots=True)
class BandTransition:
    lower: LayerBandMetrics
    upper: LayerBandMetrics
    color_distance: float
    area_change: float
    radius_change: float
    hole_count_delta: int
    component_count_delta: int
    reasons: tuple[BandSplitReason, ...] = ()

    def __post_init__(self) -> None:
        if self.upper.z != self.lower.z + 1:
            raise BandError(
                "BAND_INVALID_TRANSITION",
                "transition metrics must describe adjacent layers",
            )
        for name, value in (
            ("color_distance", self.color_distance),
            ("area_change", self.area_change),
            ("radius_change", self.radius_change),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise BandError(
                    "BAND_INVALID_TRANSITION",
                    f"{name} must be finite and within [0, 1]",
                )
        if self.hole_count_delta < 0 or self.component_count_delta < 0:
            raise BandError(
                "BAND_INVALID_TRANSITION",
                "transition count deltas must be non-negative",
            )
        expected_hole_delta = abs(self.upper.hole_count - self.lower.hole_count)
        if self.hole_count_delta != expected_hole_delta:
            raise BandError(
                "BAND_INVALID_TRANSITION",
                "hole_count_delta does not match metrics",
            )
        expected_component_delta = abs(
            self.upper.component_count - self.lower.component_count
        )
        if self.component_count_delta != expected_component_delta:
            raise BandError(
                "BAND_INVALID_TRANSITION",
                "component_count_delta does not match metrics",
            )
        if any(not isinstance(reason, BandSplitReason) for reason in self.reasons):
            raise BandError(
                "BAND_INVALID_TRANSITION",
                "reasons must contain BandSplitReason values",
            )
        object.__setattr__(
            self,
            "reasons",
            tuple(sorted(set(self.reasons), key=_REASON_ORDER.__getitem__)),
        )

    @property
    def z_lower(self) -> int:
        return self.lower.z

    @property
    def z_upper(self) -> int:
        return self.upper.z

    @property
    def should_split(self) -> bool:
        return bool(self.reasons)


@dataclass(frozen=True, slots=True)
class LayerBand:
    id: str
    z_start: int
    z_end: int
    is_empty: bool
    transition: BandTransition | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise BandError("BAND_INVALID_BAND", "band id is required")
        if self.z_start < 0 or self.z_end < self.z_start:
            raise BandError(
                "BAND_INVALID_BAND",
                "band z range must be non-negative and ordered",
            )
        if self.transition is not None:
            if self.transition.z_upper != self.z_start:
                raise BandError(
                    "BAND_INVALID_BAND",
                    "band transition must end at the band start",
                )
            if not self.transition.should_split:
                raise BandError(
                    "BAND_INVALID_BAND",
                    "band transition must contain a split reason",
                )

    @property
    def layer_indices(self) -> tuple[int, ...]:
        return tuple(range(self.z_start, self.z_end + 1))

    @property
    def layer_count(self) -> int:
        return self.z_end - self.z_start + 1

    @property
    def split_reasons(self) -> tuple[BandSplitReason, ...]:
        return self.transition.reasons if self.transition is not None else ()


@dataclass(frozen=True, slots=True)
class LayerBandExtraction:
    width: int
    height: int
    depth: int
    bands: tuple[LayerBand, ...]
    transitions: tuple[BandTransition, ...]

    def __post_init__(self) -> None:
        if min(self.width, self.height, self.depth) <= 0:
            raise BandError("BAND_INVALID_GRID", "band extraction dimensions must be positive")
        if not self.bands:
            raise BandError("BAND_INVALID_BANDS", "at least one layer band is required")
        if len(self.transitions) != self.depth - 1:
            raise BandError(
                "BAND_INVALID_TRANSITIONS",
                "one transition is required between every adjacent layer pair",
            )

        expected_start = 0
        for index, band in enumerate(self.bands):
            if band.z_start != expected_start:
                raise BandError(
                    "BAND_INVALID_BANDS",
                    "bands must cover every z index exactly once and in order",
                )
            expected_start = band.z_end + 1
            expected_id = f"B{index + 1:02d}"
            if band.id != expected_id:
                raise BandError(
                    "BAND_INVALID_BANDS",
                    f"band id must be {expected_id}",
                )
        if expected_start != self.depth:
            raise BandError(
                "BAND_INVALID_BANDS",
                "bands must cover the full depth",
            )

        for index, transition in enumerate(self.transitions):
            if transition.z_lower != index or transition.z_upper != index + 1:
                raise BandError(
                    "BAND_INVALID_TRANSITIONS",
                    "transitions must be ordered by adjacent z index",
                )

        for index, band in enumerate(self.bands):
            if index == 0:
                if band.transition is not None:
                    raise BandError(
                        "BAND_INVALID_BANDS",
                        "the first band cannot have a preceding transition",
                    )
                continue
            transition = self.transitions[band.z_start - 1]
            if band.transition != transition:
                raise BandError(
                    "BAND_INVALID_BANDS",
                    "band transition must match the corresponding layer transition",
                )
            if not transition.should_split:
                raise BandError(
                    "BAND_INVALID_BANDS",
                    "a new band requires a split transition",
                )

    @property
    def band_count(self) -> int:
        return len(self.bands)

    @property
    def empty_band_count(self) -> int:
        return sum(band.is_empty for band in self.bands)

    def band_at(self, z: int) -> LayerBand:
        if not 0 <= z < self.depth:
            raise IndexError(f"layer z {z} is outside [0, {self.depth})")
        for band in self.bands:
            if band.z_start <= z <= band.z_end:
                return band
        raise BandError("BAND_INVALID_BANDS", "layer is not covered by any band")

    def transition_at(self, z: int) -> BandTransition:
        if not 0 <= z < self.depth - 1:
            raise IndexError(f"transition z {z} is outside [0, {self.depth - 1})")
        return self.transitions[z]

    def non_empty_bands(self) -> tuple[LayerBand, ...]:
        return tuple(band for band in self.bands if not band.is_empty)


def detect_layer_bands(
    layers: LayerExtraction,
    contours: LayerContourExtraction,
    config: LayerBandConfig | None = None,
) -> LayerBandExtraction:
    """Split a voxel stack into deterministic layer bands."""
    thresholds = config or LayerBandConfig()
    _validate_extraction_pair(layers, contours)

    metrics = tuple(
        _layer_metrics(layers.layer_at(z), contours.layer_at(z))
        for z in range(layers.depth)
    )
    transitions = tuple(
        _transition_between(metrics[z], metrics[z + 1], thresholds)
        for z in range(layers.depth - 1)
    )

    bands: list[LayerBand] = []
    band_start = 0
    for z, transition in enumerate(transitions):
        if not transition.should_split:
            continue
        bands.append(
            _make_band(
                index=len(bands) + 1,
                z_start=band_start,
                z_end=z,
                metrics=metrics,
                transition=transitions[band_start - 1] if band_start > 0 else None,
            )
        )
        band_start = z + 1
    bands.append(
        _make_band(
            index=len(bands) + 1,
            z_start=band_start,
            z_end=layers.depth - 1,
            metrics=metrics,
            transition=transitions[band_start - 1] if band_start > 0 else None,
        )
    )

    return LayerBandExtraction(
        width=layers.width,
        height=layers.height,
        depth=layers.depth,
        bands=tuple(bands),
        transitions=transitions,
    )


def _validate_extraction_pair(
    layers: LayerExtraction,
    contours: LayerContourExtraction,
) -> None:
    if (
        layers.width,
        layers.height,
        layers.depth,
    ) != (
        contours.width,
        contours.height,
        contours.depth,
    ):
        raise BandError(
            "BAND_GRID_MISMATCH",
            "layer and contour extractions must use the same grid dimensions",
        )
    for z in range(layers.depth):
        layer = layers.layer_at(z)
        contour = contours.layer_at(z)
        layer_component_ids = tuple(component.id for component in layer.components)
        contour_component_ids = tuple(
            component.component_id for component in contour.components
        )
        if layer_component_ids != contour_component_ids:
            raise BandError(
                "BAND_COMPONENT_MISMATCH",
                "layer and contour components must have matching ids",
            )
        for layer_component, contour_component in zip(
            layer.components,
            contour.components,
            strict=True,
        ):
            if not math.isclose(
                layer_component.area,
                contour_component.area,
                abs_tol=1e-9,
            ):
                raise BandError(
                    "BAND_CONTOUR_MISMATCH",
                    "component cell count must match contour net area",
                )
        if not math.isclose(layer.area, contour.area, abs_tol=1e-9):
            raise BandError(
                "BAND_CONTOUR_MISMATCH",
                "layer cell count must match contour net area",
            )


def _layer_metrics(layer: Layer, contours: LayerContours) -> LayerBandMetrics:
    outer_area = sum(component.outer.area for component in contours.components)
    equivalent_radius = math.sqrt(outer_area / math.pi) if outer_area > 0.0 else 0.0
    histogram: dict[str, float] = {}
    if layer.area > 0:
        histogram = {
            color_id: count / layer.area
            for color_id, count in layer.color_counts().items()
        }
    return LayerBandMetrics(
        z=layer.z,
        cell_count=layer.area,
        outer_area=outer_area,
        equivalent_radius=equivalent_radius,
        hole_count=contours.hole_count,
        component_count=len(contours.components),
        color_histogram=histogram,
    )


def _transition_between(
    lower: LayerBandMetrics,
    upper: LayerBandMetrics,
    config: LayerBandConfig,
) -> BandTransition:
    color_distance = _histogram_distance(lower, upper)
    area_change = _relative_change(lower.outer_area, upper.outer_area)
    radius_change = _relative_change(lower.equivalent_radius, upper.equivalent_radius)
    hole_count_delta = abs(upper.hole_count - lower.hole_count)
    component_count_delta = abs(upper.component_count - lower.component_count)
    reasons = _split_reasons(
        lower=lower,
        upper=upper,
        color_distance=color_distance,
        area_change=area_change,
        radius_change=radius_change,
        hole_count_delta=hole_count_delta,
        component_count_delta=component_count_delta,
        config=config,
    )
    return BandTransition(
        lower=lower,
        upper=upper,
        color_distance=color_distance,
        area_change=area_change,
        radius_change=radius_change,
        hole_count_delta=hole_count_delta,
        component_count_delta=component_count_delta,
        reasons=reasons,
    )


def _split_reasons(
    *,
    lower: LayerBandMetrics,
    upper: LayerBandMetrics,
    color_distance: float,
    area_change: float,
    radius_change: float,
    hole_count_delta: int,
    component_count_delta: int,
    config: LayerBandConfig,
) -> tuple[BandSplitReason, ...]:
    if lower.cell_count == 0 or upper.cell_count == 0:
        if lower.cell_count != upper.cell_count:
            return (BandSplitReason.EMPTY_LAYER,)
        return ()

    reasons: list[BandSplitReason] = []
    if component_count_delta > config.component_count_change_threshold:
        reasons.append(BandSplitReason.COMPONENT_COUNT_CHANGE)
    if hole_count_delta > config.hole_count_change_threshold:
        reasons.append(BandSplitReason.HOLE_COUNT_CHANGE)
    if color_distance > config.color_distance_threshold:
        reasons.append(BandSplitReason.COLOR_DISTANCE)
    if area_change > config.area_change_threshold:
        reasons.append(BandSplitReason.AREA_CHANGE)
    if radius_change > config.radius_change_threshold:
        reasons.append(BandSplitReason.RADIUS_CHANGE)
    return tuple(sorted(reasons, key=_REASON_ORDER.__getitem__))


def _histogram_distance(
    lower: LayerBandMetrics,
    upper: LayerBandMetrics,
) -> float:
    if lower.cell_count == 0 and upper.cell_count == 0:
        return 0.0
    if lower.cell_count == 0 or upper.cell_count == 0:
        return 1.0

    color_ids = set(lower.color_histogram) | set(upper.color_histogram)
    distance = sum(
        abs(
            lower.color_histogram.get(color_id, 0.0)
            - upper.color_histogram.get(color_id, 0.0)
        )
        for color_id in color_ids
    )
    distance += abs(lower.uncolored_fraction - upper.uncolored_fraction)
    return min(1.0, max(0.0, distance / 2.0))


def _relative_change(lower: float, upper: float) -> float:
    denominator = max(lower, upper)
    if denominator <= 0.0:
        return 0.0
    return min(1.0, abs(upper - lower) / denominator)


def _make_band(
    *,
    index: int,
    z_start: int,
    z_end: int,
    metrics: tuple[LayerBandMetrics, ...],
    transition: BandTransition | None,
) -> LayerBand:
    return LayerBand(
        id=f"B{index:02d}",
        z_start=z_start,
        z_end=z_end,
        is_empty=all(metrics[z].cell_count == 0 for z in range(z_start, z_end + 1)),
        transition=transition,
    )


def _validate_unit_threshold(name: str, value: float) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise BandError(
            "BAND_INVALID_CONFIG",
            f"{name} must be finite and within [0, 1]",
        )


def _validate_count_threshold(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BandError(
            "BAND_INVALID_CONFIG",
            f"{name} must be a non-negative integer",
        )
