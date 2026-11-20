from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class RouteFeature(str, Enum):
    SHAPE_PARTITIONED = "shape_partitioned"
    DOUBLE_SIDED_HOLE = "double_sided_hole"
    GLUE_FREE_INTERLOCK = "glue_free_interlock"
    HORIZONTAL_SOLID_SLICES = "horizontal_solid_slices"
    GLUE = "glue"
    CONNECTOR_ROD = "connector_rod"
    ACRYLIC_ROD = "acrylic_rod"
    TRUE_CURVED_SURFACE = "true_curved_surface"


REQUIRED_ROUTE_FEATURES = frozenset(
    {
        RouteFeature.SHAPE_PARTITIONED,
        RouteFeature.DOUBLE_SIDED_HOLE,
        RouteFeature.GLUE_FREE_INTERLOCK,
    }
)

FORBIDDEN_ROUTE_FEATURES = frozenset(
    {
        RouteFeature.HORIZONTAL_SOLID_SLICES,
        RouteFeature.GLUE,
        RouteFeature.CONNECTOR_ROD,
        RouteFeature.ACRYLIC_ROD,
        RouteFeature.TRUE_CURVED_SURFACE,
    }
)


class RouteViolation(ValueError):
    def __init__(
        self,
        missing: Iterable[RouteFeature],
        forbidden: Iterable[RouteFeature],
    ) -> None:
        self.missing = tuple(sorted(missing, key=lambda feature: feature.value))
        self.forbidden = tuple(sorted(forbidden, key=lambda feature: feature.value))
        parts: list[str] = []
        if self.missing:
            parts.append("缺少必需特征: " + ", ".join(feature.value for feature in self.missing))
        if self.forbidden:
            parts.append("出现禁止特征: " + ", ".join(feature.value for feature in self.forbidden))
        super().__init__("; ".join(parts) or "route violation")


@dataclass(frozen=True, slots=True)
class RouteCheck:
    missing: tuple[RouteFeature, ...] = ()
    forbidden: tuple[RouteFeature, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.missing and not self.forbidden


@dataclass(frozen=True, slots=True)
class RouteGuard:
    required: frozenset[RouteFeature] = REQUIRED_ROUTE_FEATURES
    forbidden: frozenset[RouteFeature] = FORBIDDEN_ROUTE_FEATURES

    def check(self, features: Iterable[RouteFeature]) -> RouteCheck:
        present = frozenset(features)
        return RouteCheck(
            missing=tuple(sorted(self.required - present, key=lambda feature: feature.value)),
            forbidden=tuple(sorted(self.forbidden & present, key=lambda feature: feature.value)),
        )

    def assert_compliant(self, features: Iterable[RouteFeature]) -> None:
        check = self.check(features)
        if not check.ok:
            raise RouteViolation(check.missing, check.forbidden)
