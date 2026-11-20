from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

Coord3 = tuple[int, int, int]


class JointType(str, Enum):
    LOAD_BEARING = "load_bearing"
    PIN = "pin"


class JointDirection(str, Enum):
    X_POS = "x+"
    X_NEG = "x-"
    Y_POS = "y+"
    Y_NEG = "y-"
    Z_POS = "z+"
    Z_NEG = "z-"


@dataclass(frozen=True, slots=True)
class Joint:
    id: str
    plate_a: str
    plate_b: str
    edge_a: str
    edge_b: str
    direction: JointDirection
    position: int
    width: int
    length: int
    joint_type: JointType
    tongue_cells: frozenset[Coord3]
    slot_cells: frozenset[Coord3]

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("joint id is required")
        if not self.plate_a or not self.plate_b:
            raise ValueError("joint plate ids are required")
        if self.plate_a == self.plate_b:
            raise ValueError("joint plates must be different")
        if self.width <= 0 or self.length <= 0:
            raise ValueError("joint width and length must be positive")
        if self.position < 0:
            raise ValueError("joint position must be non-negative")
        if not self.tongue_cells:
            raise ValueError("joint tongue must contain cells")
        if not self.slot_cells:
            raise ValueError("joint slot must contain cells")
        if not self.tongue_cells <= self.slot_cells:
            raise ValueError("tongue cells must fit inside slot cells")
        if not self.clearance_cells:
            raise ValueError("slot must include at least one clearance cell")

    @property
    def clearance_cells(self) -> frozenset[Coord3]:
        return self.slot_cells - self.tongue_cells
