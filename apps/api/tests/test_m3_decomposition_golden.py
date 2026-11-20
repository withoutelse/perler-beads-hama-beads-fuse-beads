import json
import unittest
from itertools import pairwise
from pathlib import Path

from app.domain.assembly import AssemblyEdge, AssemblyGraph
from app.domain.bands import LayerBandConfig
from app.domain.bead import BeadSize, BeadSpec
from app.domain.cross_skeletons import CrossSkeletonConfig
from app.domain.decomposition import DecompositionConfig, decompose_voxel_grid
from app.domain.design import Design
from app.domain.joint import JointType
from app.domain.plate import PlateKind
from app.domain.route import RouteFeature, RouteGuard
from app.domain.validation import DesignValidator
from app.domain.vertical_plates import VerticalPlateConfig
from app.domain.voxel import VoxelGrid

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "fixtures" / "m3-decomposition.json"
)


def parse_cell2(value: list[int]) -> tuple[int, int]:
    return int(value[0]), int(value[1])


def parse_cell3(value: list[int]) -> tuple[int, int, int]:
    return int(value[0]), int(value[1]), int(value[2])


def parse_color_map_2(value: dict[str, str]) -> dict[tuple[int, int], str]:
    return {
        parse_cell2([int(part) for part in key.split(",")]): color
        for key, color in value.items()
    }


class M3DecompositionGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.result = decompose_voxel_grid(cls.build_grid(), cls.build_config())

    @classmethod
    def build_grid(cls) -> VoxelGrid:
        voxel_payload = cls.payload["voxel_grid"]
        return VoxelGrid(
            width=voxel_payload["width"],
            height=voxel_payload["height"],
            depth=voxel_payload["depth"],
            occupied=frozenset(
                parse_cell3(cell) for cell in voxel_payload["occupied"]
            ),
            color_by_voxel={
                parse_cell3([int(part) for part in key.split(",")]): color
                for key, color in voxel_payload["color_by_voxel"].items()
            },
        )

    @classmethod
    def build_config(cls) -> DecompositionConfig:
        config = cls.payload["config"]
        return DecompositionConfig(
            band=LayerBandConfig(**config["band"]),
            vertical=VerticalPlateConfig(**config["vertical"]),
            cross_skeleton=CrossSkeletonConfig(**config["cross_skeleton"]),
        )

    def build_design(self) -> Design:
        bead_payload = self.payload["bead_spec"]
        bead_spec = BeadSpec(
            size=BeadSize(bead_payload["size"]),
            outer_diameter_mm=bead_payload["outer_diameter_mm"],
            pitch_mm=bead_payload["pitch_mm"],
            height_mm=bead_payload["height_mm"],
            hole_diameter_mm=bead_payload["hole_diameter_mm"],
            board_max_cells_x=bead_payload["board_max_cells_x"],
            board_max_cells_y=bead_payload["board_max_cells_y"],
        )
        plates = self.result.plates
        ordered_ids = sorted(plate.id for plate in plates)
        assembly = AssemblyGraph(
            nodes=frozenset(ordered_ids),
            edges=tuple(
                AssemblyEdge(before, after)
                for before, after in pairwise(ordered_ids)
            ),
        )
        return Design(
            project_id=self.payload["project_id"],
            bead_spec=bead_spec,
            voxel_grid=self.build_grid(),
            plates=plates,
            joints=(),
            assembly=assembly,
            route_features=frozenset(
                RouteFeature(feature) for feature in self.payload["route_features"]
            ),
            palette=self.payload["palette"],
            bottom_ring_id=self.payload["bottom_ring_id"],
        )

    def test_golden_layers_bands_and_horizontal_plates(self) -> None:
        expected = self.payload["expected"]
        self.assertEqual(len(self.result.layers.layers), expected["layer_count"])
        self.assertEqual(self.result.layers.component_count, expected["component_count"])
        self.assertEqual(
            self.result.layers.boundary_edge_count,
            expected["boundary_edge_count"],
        )
        self.assertEqual(self.result.bands.band_count, expected["band_count"])
        self.assertEqual(
            [
                {
                    "id": band.id,
                    "z_start": band.z_start,
                    "z_end": band.z_end,
                    "layer_count": band.layer_count,
                    "is_empty": band.is_empty,
                }
                for band in self.result.bands.bands
            ],
            expected["bands"],
        )

        actual_horizontal = [
            {
                "id": record.plate.id,
                "kind": record.plate.kind.value,
                "z": record.z,
                "band_id": record.band_id,
                "component_id": record.component_id,
                "outer_contour_id": record.outer_contour_id,
                "hole_contour_ids": list(record.hole_contour_ids),
                "cells": [
                    list(cell)
                    for cell in sorted(record.plate.cells, key=lambda c: (c[1], c[0]))
                ],
                "holes": [
                    list(cell)
                    for cell in sorted(record.plate.holes, key=lambda c: (c[1], c[0]))
                ],
                "color_by_cell": {
                    f"{u},{v}": color
                    for (u, v), color in sorted(
                        record.plate.color_by_cell.items(),
                        key=lambda item: (item[0][1], item[0][0]),
                    )
                },
            }
            for record in self.result.horizontal.plates
        ]
        self.assertEqual(actual_horizontal, expected["horizontal_plates"])

    def test_golden_vertical_and_cross_skeleton_plates(self) -> None:
        expected = self.payload["expected"]
        actual_vertical = [
            {
                "id": record.plate.id,
                "kind": record.plate.kind.value,
                "band_id": record.band_id,
                "component_id": record.component_id,
                "source_z": record.source_z,
                "contour_id": record.contour_id,
                "segment_index": record.segment_index,
                "segment_count": record.segment_count,
                "start_vertex": list(record.start_vertex),
                "end_vertex": list(record.end_vertex),
                "width": record.width,
                "height": record.height,
                "joint_margin_cells": record.joint_margin_cells,
                "cells": [
                    list(cell)
                    for cell in sorted(record.plate.cells, key=lambda c: (c[1], c[0]))
                ],
                "color_by_cell": {
                    f"{u},{v}": color
                    for (u, v), color in sorted(
                        record.plate.color_by_cell.items(),
                        key=lambda item: (item[0][1], item[0][0]),
                    )
                },
            }
            for record in self.result.vertical.plates
        ]
        self.assertEqual(actual_vertical, expected["vertical_plates"])

        actual_cross = [
            {
                "id": record.plate.id,
                "kind": record.plate.kind.value,
                "band_id": record.band_id,
                "z": record.z,
                "component_id": record.component_id,
                "hole_contour_ids": list(record.hole_contour_ids),
                "arm_width_cells": record.arm_width_cells,
                "width": record.width,
                "height": record.height,
                "cell_count": record.cell_count,
                "clearance_count": record.clearance_count,
                "cells": [
                    list(cell)
                    for cell in sorted(record.plate.cells, key=lambda c: (c[1], c[0]))
                ],
                "source_cells": [
                    list(cell)
                    for cell in sorted(record.source_cells, key=lambda c: (c[1], c[0]))
                ],
                "clearance_cells": [
                    list(cell)
                    for cell in sorted(record.clearance_cells, key=lambda c: (c[1], c[0]))
                ],
                "color_by_cell": {
                    f"{u},{v}": color
                    for (u, v), color in sorted(
                        record.plate.color_by_cell.items(),
                        key=lambda item: (item[0][1], item[0][0]),
                    )
                },
            }
            for record in self.result.cross_skeletons.plates
        ]
        self.assertEqual(actual_cross, expected["cross_skeletons"])

    def test_golden_contact_graph_is_stable(self) -> None:
        expected = self.payload["expected"]
        actual_edges = [
            {
                "id": edge.id,
                "plate_a": edge.plate_a,
                "plate_b": edge.plate_b,
                "kind": edge.kind.value,
                "direction": edge.direction.value,
                "position": edge.position,
                "contact_length": edge.contact_length,
                "contact_edge": edge.contact_edge,
                "band_id": edge.band_id,
                "source_z": edge.source_z,
                "contour_id": edge.contour_id,
                "segment_index": edge.segment_index,
                "joint_type_hint": edge.joint_type_hint.value,
            }
            for edge in self.result.adjacency.contact_edges
        ]
        self.assertEqual(actual_edges, expected["contact_edges"])
        self.assertEqual(
            [edge["id"] for edge in actual_edges],
            [f"E{index:02d}" for index in range(1, len(actual_edges) + 1)],
        )
        self.assertTrue(
            all(
                edge.joint_type_hint is JointType.LOAD_BEARING
                for edge in self.result.adjacency.contact_edges
            )
        )
        self.assertEqual(
            [list(component) for component in self.result.adjacency.graph.connected_components()],
            expected["summary"]["connected_components"],
        )
        self.assertEqual(
            self.result.adjacency.graph.contact_length("P08", "P09"),
            5,
        )
        self.assertEqual(
            self.result.adjacency.graph.contact_length("P09", "P10"),
            5,
        )

    def test_golden_summary_and_plate_invariants(self) -> None:
        expected = self.payload["expected"]
        summary = expected["summary"]
        self.assertEqual(self.result.plate_count, summary["plate_count"])
        self.assertEqual(self.result.horizontal.plate_count, summary["horizontal_count"])
        self.assertEqual(self.result.vertical.plate_count, summary["vertical_count"])
        self.assertEqual(
            self.result.cross_skeletons.plate_count,
            summary["cross_count"],
        )
        self.assertEqual(
            self.result.adjacency.edge_count,
            summary["contact_edge_count"],
        )

        self.assertTrue(all(plate.is_4_connected() for plate in self.result.plates))
        self.assertEqual(
            {plate.kind for plate in self.result.plates},
            {PlateKind.RING, PlateKind.PERIMETER, PlateKind.CROSS_SKELETON},
        )
        self.assertTrue(
            all(record.plate.holes for record in self.result.horizontal.plates)
        )
        self.assertTrue(
            all(not record.plate.holes for record in self.result.vertical.plates)
        )
        self.assertTrue(
            all(not record.plate.holes for record in self.result.cross_skeletons.plates)
        )

        ring_holes = {
            (record.band_id, record.z, record.component_id): record.plate.holes
            for record in self.result.horizontal.plates
        }
        for record in self.result.cross_skeletons.plates:
            holes = ring_holes[(record.band_id, record.z, record.component_id)]
            self.assertTrue(record.source_cells <= holes)
            self.assertEqual(
                record.clearance_cells,
                holes - record.source_cells,
            )
            self.assertGreaterEqual(record.clearance_count, 1)

    def test_golden_design_passes_route_guard_and_validator(self) -> None:
        features = {
            RouteFeature(feature) for feature in self.payload["route_features"]
        }
        self.assertTrue(RouteGuard().check(features).ok)
        self.assertNotIn(RouteFeature.HORIZONTAL_SOLID_SLICES, features)
        self.assertNotIn(RouteFeature.GLUE, features)
        self.assertNotIn(RouteFeature.CONNECTOR_ROD, features)
        self.assertNotIn(RouteFeature.ACRYLIC_ROD, features)
        self.assertNotIn(RouteFeature.TRUE_CURVED_SURFACE, features)

        report = DesignValidator().validate(self.build_design())
        self.assertTrue(report.ok, [issue.message for issue in report.errors()])
        self.assertFalse(
            any(issue.code.startswith("ROUTE_") for issue in report.errors())
        )


if __name__ == "__main__":
    unittest.main()
