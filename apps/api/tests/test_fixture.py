import json
import unittest
from pathlib import Path

from app.domain.assembly import AssemblyEdge, AssemblyGraph
from app.domain.bead import BeadSize, BeadSpec
from app.domain.design import Design
from app.domain.joint import Joint, JointDirection, JointType
from app.domain.plate import Plate, PlateKind
from app.domain.route import RouteFeature
from app.domain.validation import DesignValidator
from app.domain.voxel import VoxelGrid


def parse_cell2(value: str) -> tuple[int, int]:
    u, v = value.split(",")
    return int(u), int(v)


def parse_cell3(value: str) -> tuple[int, int, int]:
    x, y, z = value.split(",")
    return int(x), int(y), int(z)


def load_demo_design() -> Design:
    path = Path(__file__).resolve().parents[3] / "fixtures" / "demo-design.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    bead_payload = payload["bead_spec"]
    voxel_payload = payload["voxel_grid"]
    bead_spec = BeadSpec(
        size=BeadSize(bead_payload["size"]),
        outer_diameter_mm=bead_payload["outer_diameter_mm"],
        pitch_mm=bead_payload["pitch_mm"],
        height_mm=bead_payload["height_mm"],
        hole_diameter_mm=bead_payload["hole_diameter_mm"],
        board_max_cells_x=bead_payload["board_max_cells_x"],
        board_max_cells_y=bead_payload["board_max_cells_y"],
    )
    voxel_grid = VoxelGrid(
        width=voxel_payload["width"],
        height=voxel_payload["height"],
        depth=voxel_payload["depth"],
        occupied=frozenset(tuple(cell) for cell in voxel_payload["occupied"]),
        color_by_voxel={
            parse_cell3(key): value for key, value in voxel_payload["color_by_voxel"].items()
        },
    )
    plates = tuple(
        Plate(
            id=plate["id"],
            kind=PlateKind(plate["kind"]),
            cells=frozenset(tuple(cell) for cell in plate["cells"]),
            color_by_cell={
                parse_cell2(key): value for key, value in plate["color_by_cell"].items()
            },
            holes=frozenset(tuple(cell) for cell in plate["holes"]),
            label=plate["label"],
        )
        for plate in payload["plates"]
    )
    joints = tuple(
        Joint(
            id=joint["id"],
            plate_a=joint["plate_a"],
            plate_b=joint["plate_b"],
            edge_a=joint["edge_a"],
            edge_b=joint["edge_b"],
            direction=JointDirection(joint["direction"]),
            position=joint["position"],
            width=joint["width"],
            length=joint["length"],
            joint_type=JointType(joint["joint_type"]),
            tongue_cells=frozenset(tuple(cell) for cell in joint["tongue_cells"]),
            slot_cells=frozenset(tuple(cell) for cell in joint["slot_cells"]),
        )
        for joint in payload["joints"]
    )
    assembly = AssemblyGraph(
        nodes=frozenset(payload["assembly"]["nodes"]),
        edges=tuple(
            AssemblyEdge(
                before=edge["before"],
                after=edge["after"],
                joint_id=edge.get("joint_id"),
            )
            for edge in payload["assembly"]["edges"]
        ),
    )
    return Design(
        project_id=payload["project_id"],
        bead_spec=bead_spec,
        voxel_grid=voxel_grid,
        plates=plates,
        joints=joints,
        assembly=assembly,
        route_features=frozenset(RouteFeature(feature) for feature in payload["route_features"]),
        palette=payload["palette"],
        bottom_ring_id=payload["bottom_ring_id"],
    )


class FixtureTests(unittest.TestCase):
    def test_demo_design_is_valid(self) -> None:
        report = DesignValidator().validate(load_demo_design())
        self.assertTrue(report.ok, [issue.message for issue in report.errors()])


if __name__ == "__main__":
    unittest.main()
