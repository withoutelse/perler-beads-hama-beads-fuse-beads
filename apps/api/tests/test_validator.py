import unittest

from app.domain.assembly import AssemblyEdge, AssemblyGraph
from app.domain.bead import BeadSpec
from app.domain.design import Design
from app.domain.joint import Joint, JointDirection, JointType
from app.domain.plate import Plate, PlateKind
from app.domain.route import REQUIRED_ROUTE_FEATURES, RouteFeature
from app.domain.validation import DesignValidator
from app.domain.voxel import VoxelGrid


def build_design(
    ring_cells: frozenset[tuple[int, int]] | None = None,
    plate_color: str = "orange",
    route_features: frozenset[RouteFeature] = REQUIRED_ROUTE_FEATURES,
    assembly_edges: tuple[AssemblyEdge, ...] | None = None,
) -> Design:
    ring_cells = ring_cells or frozenset({(0, 0), (1, 0), (0, 1), (1, 1)})
    cap_cells = frozenset({(0, 0)})
    voxel_grid = VoxelGrid(
        width=2,
        height=2,
        depth=1,
        occupied=frozenset({(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)}),
        color_by_voxel={
            (0, 0, 0): "orange",
            (1, 0, 0): "orange",
            (0, 1, 0): "orange",
            (1, 1, 0): "orange",
        },
    )
    ring = Plate(
        id="P01",
        kind=PlateKind.RING,
        cells=ring_cells,
        color_by_cell={cell: plate_color for cell in ring_cells},
        label="底环",
    )
    cap = Plate(
        id="P02",
        kind=PlateKind.CAP,
        cells=cap_cells,
        color_by_cell={cell: "orange" for cell in cap_cells},
        label="封顶",
    )
    joint = Joint(
        id="J01",
        plate_a="P01",
        plate_b="P02",
        edge_a="top",
        edge_b="bottom",
        direction=JointDirection.Z_NEG,
        position=1,
        width=1,
        length=1,
        joint_type=JointType.LOAD_BEARING,
        tongue_cells=frozenset({(0, 0, 0)}),
        slot_cells=frozenset({(0, 0, 0), (1, 0, 0)}),
    )
    assembly = AssemblyGraph(
        nodes=frozenset({"P01", "P02"}),
        edges=assembly_edges or (AssemblyEdge("P01", "P02", joint_id="J01"),),
    )
    return Design(
        project_id="prj_test",
        bead_spec=BeadSpec.standard_5mm(),
        voxel_grid=voxel_grid,
        plates=(ring, cap),
        joints=(joint,),
        assembly=assembly,
        route_features=route_features,
        palette={"orange": "#e86f2d"},
        bottom_ring_id="P01",
    )


class DesignValidatorTests(unittest.TestCase):
    def test_valid_design_passes(self) -> None:
        report = DesignValidator().validate(build_design())
        self.assertTrue(report.ok, [issue.message for issue in report.errors()])

    def test_disconnected_plate_fails(self) -> None:
        report = DesignValidator().validate(
            build_design(ring_cells=frozenset({(0, 0), (2, 0)}))
        )
        self.assertFalse(report.ok)
        self.assertIn("PLATE_DISCONNECTED", {issue.code for issue in report.errors()})

    def test_unknown_color_fails(self) -> None:
        report = DesignValidator().validate(build_design(plate_color="blue"))
        self.assertFalse(report.ok)
        self.assertIn("COLOR_NOT_IN_PALETTE", {issue.code for issue in report.errors()})

    def test_route_violation_fails(self) -> None:
        report = DesignValidator().validate(
            build_design(route_features=REQUIRED_ROUTE_FEATURES | {RouteFeature.GLUE})
        )
        self.assertFalse(report.ok)
        self.assertIn("ROUTE_FORBIDDEN_FEATURE", {issue.code for issue in report.errors()})

    def test_double_sided_hole_route_is_required(self) -> None:
        report = DesignValidator().validate(
            build_design(
                route_features=REQUIRED_ROUTE_FEATURES - {RouteFeature.DOUBLE_SIDED_HOLE}
            )
        )
        self.assertFalse(report.ok)
        self.assertIn(
            "ROUTE_REQUIRED_FEATURE_MISSING",
            {issue.code for issue in report.errors()},
        )

    def test_assembly_cycle_fails(self) -> None:
        report = DesignValidator().validate(
            build_design(
                assembly_edges=(
                    AssemblyEdge("P01", "P02"),
                    AssemblyEdge("P02", "P01"),
                )
            )
        )
        self.assertFalse(report.ok)
        self.assertIn("ASSEMBLY_CYCLE", {issue.code for issue in report.errors()})


if __name__ == "__main__":
    unittest.main()
