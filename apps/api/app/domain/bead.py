from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BeadSize(str, Enum):
    MIDI_5MM = "5mm"
    MINI_2_6MM = "2.6mm"


@dataclass(frozen=True, slots=True)
class BeadSpec:
    size: BeadSize
    outer_diameter_mm: float
    pitch_mm: float
    height_mm: float
    hole_diameter_mm: float
    board_max_cells_x: int = 29
    board_max_cells_y: int = 29

    def __post_init__(self) -> None:
        if self.outer_diameter_mm <= 0:
            raise ValueError("outer_diameter_mm must be positive")
        if self.pitch_mm <= 0:
            raise ValueError("pitch_mm must be positive")
        if self.height_mm <= 0:
            raise ValueError("height_mm must be positive")
        if self.hole_diameter_mm <= 0:
            raise ValueError("hole_diameter_mm must be positive")
        if self.hole_diameter_mm >= self.outer_diameter_mm:
            raise ValueError("hole_diameter_mm must be smaller than outer_diameter_mm")
        if self.board_max_cells_x <= 0 or self.board_max_cells_y <= 0:
            raise ValueError("board limits must be positive")

    @classmethod
    def standard_5mm(cls) -> BeadSpec:
        return cls(
            size=BeadSize.MIDI_5MM,
            outer_diameter_mm=5.0,
            pitch_mm=5.0,
            height_mm=5.1,
            hole_diameter_mm=2.2,
            board_max_cells_x=29,
            board_max_cells_y=29,
        )

    @classmethod
    def mini_2_6mm(cls) -> BeadSpec:
        return cls(
            size=BeadSize.MINI_2_6MM,
            outer_diameter_mm=2.6,
            pitch_mm=2.6,
            height_mm=2.8,
            hole_diameter_mm=1.0,
            board_max_cells_x=57,
            board_max_cells_y=57,
        )

    @property
    def board_capacity(self) -> int:
        return self.board_max_cells_x * self.board_max_cells_y
