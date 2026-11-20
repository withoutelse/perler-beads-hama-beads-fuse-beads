from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from app.domain.assembly import AssemblyGraph
from app.domain.bead import BeadSpec
from app.domain.joint import Joint
from app.domain.plate import Plate
from app.domain.route import RouteFeature
from app.domain.voxel import VoxelGrid


@dataclass(frozen=True, slots=True)
class Design:
    project_id: str
    bead_spec: BeadSpec
    voxel_grid: VoxelGrid
    plates: tuple[Plate, ...]
    joints: tuple[Joint, ...]
    assembly: AssemblyGraph
    route_features: frozenset[RouteFeature]
    palette: Mapping[str, str] = field(default_factory=dict)
    bottom_ring_id: str | None = None

    def __post_init__(self) -> None:
        if not self.project_id:
            raise ValueError("project_id is required")
        if not self.plates:
            raise ValueError("design must contain plates")
        if not self.palette:
            raise ValueError("design palette is required")
        object.__setattr__(self, "palette", MappingProxyType(dict(self.palette)))

    def plate_by_id(self, plate_id: str) -> Plate:
        for plate in self.plates:
            if plate.id == plate_id:
                return plate
        raise KeyError(plate_id)

    def joint_by_id(self, joint_id: str) -> Joint:
        for joint in self.joints:
            if joint.id == joint_id:
                return joint
        raise KeyError(joint_id)
