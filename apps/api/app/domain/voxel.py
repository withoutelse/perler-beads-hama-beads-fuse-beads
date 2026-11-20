from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

Coord3 = tuple[int, int, int]
Coord2 = tuple[int, int]


@dataclass(frozen=True, slots=True)
class VoxelGrid:
    width: int
    height: int
    depth: int
    occupied: frozenset[Coord3]
    color_by_voxel: Mapping[Coord3, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if min(self.width, self.height, self.depth) <= 0:
            raise ValueError("voxel grid dimensions must be positive")
        for x, y, z in self.occupied:
            if not (0 <= x < self.width and 0 <= y < self.height and 0 <= z < self.depth):
                raise ValueError(f"voxel {(x, y, z)} is outside the grid")
        unknown_colors = set(self.color_by_voxel) - self.occupied
        if unknown_colors:
            raise ValueError("color_by_voxel keys must be a subset of occupied voxels")
        object.__setattr__(self, "color_by_voxel", MappingProxyType(dict(self.color_by_voxel)))

    def is_solid(self, x: int, y: int, z: int) -> bool:
        return (x, y, z) in self.occupied

    def layer(self, z: int) -> frozenset[Coord2]:
        return frozenset((x, y) for x, y, vz in self.occupied if vz == z)

    def bounds(self) -> tuple[Coord3, Coord3] | None:
        if not self.occupied:
            return None
        xs = [x for x, _, _ in self.occupied]
        ys = [y for _, y, _ in self.occupied]
        zs = [z for _, _, z in self.occupied]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def center_of_mass(self) -> tuple[float, float, float] | None:
        if not self.occupied:
            return None
        count = len(self.occupied)
        return (
            sum(x + 0.5 for x, _, _ in self.occupied) / count,
            sum(y + 0.5 for _, y, _ in self.occupied) / count,
            sum(z + 0.5 for _, _, z in self.occupied) / count,
        )

    def color_counts(self) -> dict[str, int]:
        return dict(Counter(self.color_by_voxel.values()))
