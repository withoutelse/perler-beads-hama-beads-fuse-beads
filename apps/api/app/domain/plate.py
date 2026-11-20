from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

Cell2 = tuple[int, int]


class PlateKind(str, Enum):
    RING = "ring"
    PERIMETER = "perimeter"
    CROSS_SKELETON = "cross_skeleton"
    PIN_PATCH = "pin_patch"
    CAP = "cap"
    SPLICE = "splice"


@dataclass(frozen=True, slots=True)
class Plate:
    id: str
    kind: PlateKind
    cells: frozenset[Cell2]
    color_by_cell: Mapping[Cell2, str] = field(default_factory=dict)
    holes: frozenset[Cell2] = frozenset()
    label: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("plate id is required")
        if not self.cells:
            raise ValueError("plate must contain at least one cell")
        if self.holes & self.cells:
            raise ValueError("plate holes must not overlap solid cells")
        unknown_colors = set(self.color_by_cell) - self.cells
        if unknown_colors:
            raise ValueError("color_by_cell keys must be a subset of plate cells")
        object.__setattr__(self, "color_by_cell", MappingProxyType(dict(self.color_by_cell)))

    def is_4_connected(self) -> bool:
        if len(self.cells) <= 1:
            return True
        start = next(iter(self.cells))
        seen = {start}
        queue: deque[Cell2] = deque([start])
        while queue:
            u, v = queue.popleft()
            for neighbor in ((u + 1, v), (u - 1, v), (u, v + 1), (u, v - 1)):
                if neighbor in self.cells and neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        return len(seen) == len(self.cells)

    def bounding_box(self) -> tuple[int, int, int, int]:
        us = [u for u, _ in self.cells]
        vs = [v for _, v in self.cells]
        return min(us), min(vs), max(us), max(vs)

    def width(self) -> int:
        min_u, _, max_u, _ = self.bounding_box()
        return max_u - min_u + 1

    def height(self) -> int:
        _, min_v, _, max_v = self.bounding_box()
        return max_v - min_v + 1

    def color_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for color_id in self.color_by_cell.values():
            counts[color_id] = counts.get(color_id, 0) + 1
        return counts
