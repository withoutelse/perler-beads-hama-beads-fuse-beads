import unittest
from dataclasses import replace

from app.domain.bands import LayerBandConfig, LayerBandExtraction, detect_layer_bands
from app.domain.contours import LayerContourExtraction, trace_horizontal_contours
from app.domain.horizontal_plates import (
    HorizontalPlateExtraction,
    extract_horizontal_plates,
)
from app.domain.joint import JointDirection, JointType
from app.domain.layers import LayerExtraction, extract_horizontal_layers
from app.domain.plate_adjacency import (
    PlateAdjacencyError,
    PlateAdjacencyExtraction,
    PlateContactEdge,
    PlateContactGraph,
    PlateContactKind,
    extract_plate_adjacency,
    extract_plate_contact_graph,
)
from app.domain.vertical_plates import (
    VerticalPlateExtraction,
    extract_vertical_plates,
)
from app.domain.voxel import VoxelGrid


class PlateAdjacencyTests(unittest.TestCase):
    def make_grid(
        self,
        occupied: set[tuple[int, int, int]],
        *,
        width: int = 3,
        height: int = 3,
        depth: int = 1,
        color_by_voxel: dict[tuple[int, int, int], str] | None = None,
    ) -> VoxelGrid:
        colors = (
            color_by_voxel
            if color_by_voxel is not None
            else {voxel: "orange" for voxel in occupied}
        )
        return VoxelGrid(
            width=width,
            height=height,
            depth=depth,
            occupied=frozenset(occupied),
            color_by_voxel=colors,
        )

    def extract_all(
        self,
        grid: VoxelGrid,
        band_config: LayerBandConfig | None = None,
    ) -> tuple[
        LayerExtraction,
        LayerContourExtraction,
        LayerBandExtraction,
        HorizontalPlateExtraction,
        VerticalPlateExtraction,
        PlateAdjacencyExtraction,
    ]:
        layers = extract_horizontal_layers(grid)
        contours = trace_horizontal_contours(layers)
        bands = detect_layer_bands(layers, contours, band_config)
        horizontal = extract_horizontal_plates(layers, contours, bands)
        vertical = extract_vertical_plates(
            layers,
            contours,
            bands,
            start_plate_index=horizontal.plate_count + 1,
        )
        adjacency = extract_plate_adjacency(
            layers,
            contours,
            horizontal,
            vertical,
        )
        return layers, contours, bands, horizontal, vertical, adjacency

    @staticmethod
    def ring(z: int = 0, *, size: int = 3) -> set[tuple[int, int, int]]:
        return {
            (x, y, z)
            for x in range(size)
            for y in range(size)
            if (x, y) != (size // 2, size // 2)
        }

    def test_ring_has_ring_perimeter_and_segment_contacts(self) -> None:
        _, _, _, horizontal, vertical, adjacency = self.extract_all(
            self.make_grid(self.ring())
        )

        self.assertEqual(horizontal.plate_count, 1)
        self.assertEqual(vertical.plate_count, 4)
        graph = adjacency.graph
        self.assertEqual(graph.nodes, frozenset({"P01", "P02", "P03", "P04", "P05"}))
        self.assertEqual(graph.edge_count, 8)
        self.assertTrue(graph.is_connected())
        self.assertEqual(graph.isolated_plates, ())
        self.assertEqual(
            graph.neighbors("P01"),
            ("P02", "P03", "P04", "P05"),
        )
        self.assertEqual(graph.degree("P02"), 3)
        self.assertEqual(graph.contact_length("P01", "P02"), 3)
        self.assertTrue(graph.has_edge("P04", "P01"))
        self.assertEqual(
            graph.connected_components(),
            (("P01", "P02", "P03", "P04", "P05"),),
        )

        face_edges = [
            edge for edge in graph.edges if edge.kind is PlateContactKind.FACE
        ]
        joint_edges = [
            edge
            for edge in graph.edges
            if edge.kind is PlateContactKind.SEGMENT_JOINT
        ]
        self.assertEqual(len(face_edges), 4)
        self.assertEqual(len(joint_edges), 4)
        self.assertEqual(
            {(edge.plate_a, edge.plate_b): edge.direction for edge in face_edges},
            {
                ("P01", "P02"): JointDirection.Y_NEG,
                ("P01", "P03"): JointDirection.X_POS,
                ("P01", "P04"): JointDirection.Y_POS,
                ("P01", "P05"): JointDirection.X_NEG,
            },
        )
        self.assertEqual(
            {(edge.plate_a, edge.plate_b): edge.direction for edge in joint_edges},
            {
                ("P02", "P03"): JointDirection.X_POS,
                ("P03", "P04"): JointDirection.Y_POS,
                ("P04", "P05"): JointDirection.X_NEG,
                ("P02", "P05"): JointDirection.Y_POS,
            },
        )
        self.assertTrue(all(edge.joint_type_hint is JointType.LOAD_BEARING for edge in graph.edges))
        self.assertEqual(
            [edge.id for edge in graph.edges],
            [f"E{index:02d}" for index in range(1, graph.edge_count + 1)],
        )

    def test_multilayer_band_adds_horizontal_stacks(self) -> None:
        occupied = self.ring(0) | self.ring(1) | self.ring(2)

        _, _, bands, horizontal, vertical, adjacency = self.extract_all(
            self.make_grid(occupied, depth=3)
        )

        self.assertEqual(bands.band_count, 1)
        self.assertEqual(horizontal.plate_count, 3)
        self.assertEqual(vertical.plate_count, 4)
        graph = adjacency.graph
        self.assertEqual(graph.plate_count, 7)
        self.assertEqual(graph.edge_count, 18)
        self.assertTrue(graph.is_connected())
        self.assertEqual(graph.contact_length("P01", "P02"), 8)
        self.assertEqual(graph.contact_length("P02", "P03"), 8)
        self.assertEqual(graph.neighbors("P01"), ("P02", "P04", "P05", "P06", "P07"))
        self.assertEqual(graph.neighbors("P04"), ("P01", "P02", "P03", "P05", "P07"))

    def test_l_shape_vertical_plates_form_a_cycle(self) -> None:
        occupied = {(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (0, 2, 0)}

        _, _, _, horizontal, vertical, adjacency = self.extract_all(
            self.make_grid(occupied, width=3, height=3)
        )

        self.assertEqual(horizontal.plate_count, 0)
        self.assertEqual(horizontal.skipped_count, 1)
        self.assertEqual(vertical.plate_count, 6)
        graph = adjacency.graph
        self.assertEqual(graph.edge_count, 6)
        self.assertTrue(graph.is_connected())
        self.assertTrue(
            all(edge.kind is PlateContactKind.SEGMENT_JOINT for edge in graph.edges)
        )
        self.assertTrue(all(graph.degree(plate_id) == 2 for plate_id in graph.nodes))

    def test_adjacent_bands_add_vertical_stack_contacts(self) -> None:
        occupied = self.ring(0) | self.ring(1)
        colors = {
            voxel: ("red" if voxel[2] == 0 else "blue") for voxel in occupied
        }

        _, _, bands, horizontal, vertical, adjacency = self.extract_all(
            self.make_grid(occupied, depth=2, color_by_voxel=colors)
        )

        self.assertEqual(bands.band_count, 2)
        self.assertEqual(horizontal.plate_count, 2)
        self.assertEqual(vertical.plate_count, 8)
        graph = adjacency.graph
        self.assertEqual(graph.plate_count, 10)
        self.assertEqual(graph.edge_count, 21)
        self.assertTrue(graph.is_connected())
        self.assertEqual(graph.contact_length("P01", "P02"), 8)
        self.assertTrue(graph.has_edge("P03", "P07"))
        self.assertTrue(graph.has_edge("P04", "P08"))
        self.assertTrue(graph.has_edge("P05", "P09"))
        self.assertTrue(graph.has_edge("P06", "P10"))
        self.assertEqual(graph.contact_length("P03", "P07"), 3)
        self.assertEqual(graph.neighbors("P03"), ("P01", "P04", "P06", "P07"))

    def test_empty_design_produces_empty_graph(self) -> None:
        _, _, _, horizontal, vertical, adjacency = self.extract_all(
            self.make_grid(set(), width=3, height=3, depth=1)
        )

        self.assertEqual(horizontal.plate_count, 0)
        self.assertEqual(vertical.plate_count, 0)
        self.assertEqual(adjacency.graph.nodes, frozenset())
        self.assertEqual(adjacency.graph.edges, ())
        self.assertTrue(adjacency.graph.is_connected())
        self.assertEqual(adjacency.graph.connected_components(), ())

    def test_convenience_wrapper_returns_same_graph(self) -> None:
        layers, contours, _, horizontal, vertical, adjacency = self.extract_all(
            self.make_grid(self.ring())
        )

        graph = extract_plate_contact_graph(layers, contours, horizontal, vertical)
        self.assertEqual(graph, adjacency.graph)

    def test_grid_mismatch_is_rejected(self) -> None:
        layers, contours, _, horizontal, vertical, _ = self.extract_all(
            self.make_grid(self.ring())
        )

        with self.assertRaises(PlateAdjacencyError) as context:
            extract_plate_adjacency(
                layers,
                replace(contours, width=4),
                horizontal,
                vertical,
            )
        self.assertEqual(context.exception.code, "ADJACENCY_GRID_MISMATCH")

    def test_duplicate_plate_ids_are_rejected(self) -> None:
        layers, contours, _, horizontal, vertical, _ = self.extract_all(
            self.make_grid(self.ring())
        )
        duplicate = replace(
            vertical.plates[0],
            plate=replace(vertical.plates[0].plate, id="P01"),
        )
        bad_vertical = replace(
            vertical,
            plates=(duplicate, *vertical.plates[1:]),
        )

        with self.assertRaises(PlateAdjacencyError) as context:
            extract_plate_adjacency(layers, contours, horizontal, bad_vertical)
        self.assertEqual(context.exception.code, "ADJACENCY_DUPLICATE_ID")

    def test_unknown_contour_is_rejected(self) -> None:
        layers, contours, _, horizontal, vertical, _ = self.extract_all(
            self.make_grid(self.ring())
        )
        bad_vertical = replace(
            vertical,
            plates=tuple(
                replace(record, contour_id="missing-contour")
                for record in vertical.plates
            ),
        )

        with self.assertRaises(PlateAdjacencyError) as context:
            extract_plate_adjacency(layers, contours, horizontal, bad_vertical)
        self.assertEqual(context.exception.code, "ADJACENCY_CONTOUR_MISMATCH")

    def test_contact_edge_validation(self) -> None:
        valid = PlateContactEdge(
            id="E01",
            plate_a="P01",
            plate_b="P02",
            kind=PlateContactKind.FACE,
            direction=JointDirection.X_POS,
            position=0,
            contact_length=1,
            contact_edge="test",
        )
        self.assertEqual(valid.contact_length, 1)

        for kwargs in (
            {"plate_a": "P02", "plate_b": "P01"},
            {"plate_a": "P01", "plate_b": "P01"},
            {"contact_length": 0},
            {"position": -1},
            {"contact_edge": ""},
        ):
            values = {
                "id": "E01",
                "plate_a": "P01",
                "plate_b": "P02",
                "kind": PlateContactKind.FACE,
                "direction": JointDirection.X_POS,
                "position": 0,
                "contact_length": 1,
                "contact_edge": "test",
            }
            values.update(kwargs)
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(PlateAdjacencyError) as context:
                    PlateContactEdge(**values)  # type: ignore[arg-type]
                self.assertEqual(context.exception.code, "ADJACENCY_INVALID_CONTACT")

    def test_graph_validation_and_queries(self) -> None:
        edge = PlateContactEdge(
            id="E01",
            plate_a="P01",
            plate_b="P02",
            kind=PlateContactKind.FACE,
            direction=JointDirection.X_POS,
            position=0,
            contact_length=2,
            contact_edge="test",
        )
        graph = PlateContactGraph(
            nodes=frozenset({"P01", "P02", "P03"}),
            edges=(edge,),
        )
        self.assertEqual(graph.neighbors("P01"), ("P02",))
        self.assertEqual(graph.edges_for("P02"), (edge,))
        self.assertEqual(graph.contact_length("P01", "P02"), 2)
        self.assertEqual(graph.contact_length("P01", "P01"), 0)
        self.assertEqual(graph.isolated_plates, ("P03",))
        self.assertEqual(
            graph.connected_components(),
            (("P01", "P02"), ("P03",)),
        )
        self.assertFalse(graph.is_connected())
        with self.assertRaises(PlateAdjacencyError) as context:
            graph.neighbors("P99")
        self.assertEqual(context.exception.code, "ADJACENCY_UNKNOWN_PLATE")

        with self.assertRaises(PlateAdjacencyError) as context:
            PlateContactGraph(nodes=frozenset({"P01"}), edges=(edge,))
        self.assertEqual(context.exception.code, "ADJACENCY_UNKNOWN_PLATE")

        duplicate = replace(edge, id="E02")
        with self.assertRaises(PlateAdjacencyError) as context:
            PlateContactGraph(
                nodes=frozenset({"P01", "P02"}),
                edges=(edge, duplicate),
            )
        self.assertEqual(context.exception.code, "ADJACENCY_DUPLICATE_EDGE")

    def test_adjacency_extraction_rejects_graph_node_mismatch(self) -> None:
        _, _, _, horizontal, vertical, adjacency = self.extract_all(
            self.make_grid(self.ring())
        )
        bad_graph = PlateContactGraph(
            nodes=frozenset({"P01"}),
            edges=(),
        )

        with self.assertRaises(PlateAdjacencyError) as context:
            PlateAdjacencyExtraction(
                horizontal=horizontal,
                vertical=vertical,
                graph=bad_graph,
            )
        self.assertEqual(context.exception.code, "ADJACENCY_UNKNOWN_PLATE")
        self.assertNotEqual(adjacency.graph, bad_graph)


if __name__ == "__main__":
    unittest.main()
