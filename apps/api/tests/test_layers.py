import unittest

from app.domain.layers import BoundaryEdge, LayerComponent, extract_horizontal_layers
from app.domain.voxel import VoxelGrid


class LayerExtractionTests(unittest.TestCase):
    def make_grid(
        self,
        occupied: set[tuple[int, int, int]],
        *,
        width: int = 3,
        height: int = 3,
        depth: int = 1,
    ) -> VoxelGrid:
        return VoxelGrid(
            width=width,
            height=height,
            depth=depth,
            occupied=frozenset(occupied),
            color_by_voxel={voxel: "orange" for voxel in occupied},
        )

    def test_extracts_all_layers_and_preserves_empty_depth(self) -> None:
        grid = self.make_grid(
            {(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0)},
            width=3,
            height=2,
            depth=3,
        )

        extraction = extract_horizontal_layers(grid)

        self.assertEqual(extraction.depth, 3)
        self.assertEqual(len(extraction.layers), 3)
        self.assertEqual(extraction.layers[0].cells, frozenset({(0, 0), (1, 0), (2, 0), (0, 1)}))
        self.assertTrue(extraction.layers[1].is_empty)
        self.assertTrue(extraction.layers[2].is_empty)
        self.assertEqual(extraction.layers[0].color_counts(), {"orange": 4})
        self.assertEqual(extraction.layers[0].components[0].color_counts(), {"orange": 4})
        self.assertEqual(extraction.component_count, 1)
        self.assertEqual(extraction.boundary_edge_count, 10)

    def test_diagonal_cells_are_separate_components(self) -> None:
        grid = self.make_grid({(0, 0, 0), (2, 0, 0), (1, 1, 0)}, width=3, height=2)

        extraction = extract_horizontal_layers(grid)
        layer = extraction.layer_at(0)

        self.assertEqual(layer.component_count, 3)
        self.assertEqual(
            [component.id for component in layer.components],
            ["L000-C001", "L000-C002", "L000-C003"],
        )
        self.assertEqual(
            [component.cells for component in layer.components],
            [frozenset({(0, 0)}), frozenset({(2, 0)}), frozenset({(1, 1)})],
        )
        self.assertTrue(all(component.is_4_connected() for component in layer.components))

    def test_ring_boundary_includes_inner_hole(self) -> None:
        occupied = {
            (x, y, 0)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }
        grid = self.make_grid(occupied)

        layer = extract_horizontal_layers(grid).layer_at(0)

        self.assertEqual(layer.component_count, 1)
        self.assertEqual(len(layer.boundary_cells), 8)
        self.assertEqual(len(layer.boundary_edges), 16)
        self.assertTrue(
            all(
                abs(edge.end[0] - edge.start[0]) + abs(edge.end[1] - edge.start[1]) == 1
                for edge in layer.boundary_edges
            )
        )

    def test_component_metrics_and_connectivity(self) -> None:
        grid = self.make_grid({(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0)}, width=3, height=2)

        component = extract_horizontal_layers(grid).layer_at(0).components[0]

        self.assertTrue(component.is_4_connected())
        self.assertEqual(component.bounding_box(), (0, 0, 2, 1))
        self.assertEqual(component.width(), 3)
        self.assertEqual(component.height(), 2)
        self.assertEqual(component.area, 4)
        self.assertEqual(len(component.boundary_cells), 4)
        self.assertEqual(component.color_counts(), {"orange": 4})

    def test_empty_grid_has_empty_layers(self) -> None:
        extraction = extract_horizontal_layers(self.make_grid(set(), width=1, height=1, depth=2))

        self.assertEqual(extraction.component_count, 0)
        self.assertEqual(extraction.boundary_edge_count, 0)
        self.assertEqual(len(extraction.non_empty_layers()), 0)
        self.assertTrue(all(layer.is_empty for layer in extraction.layers))

    def test_boundary_edge_rejects_non_unit_segments(self) -> None:
        with self.assertRaises(ValueError):
            BoundaryEdge((0, 0), (0, 0))
        with self.assertRaises(ValueError):
            BoundaryEdge((0, 0), (1, 1))

    def test_component_from_cells_computes_boundary_and_checks_colors(self) -> None:
        component = LayerComponent.from_cells(
            id="L000-C001",
            z=0,
            cells={(0, 0), (1, 0)},
            color_by_cell={(0, 0): "red", (1, 0): "red"},
        )

        self.assertEqual(component.boundary_cells, frozenset({(0, 0), (1, 0)}))
        self.assertEqual(len(component.boundary_edges), 6)
        with self.assertRaises(ValueError):
            LayerComponent.from_cells(
                id="L000-C002",
                z=0,
                cells={(0, 0)},
                color_by_cell={(1, 1): "red"},
            )
        with self.assertRaises(ValueError):
            LayerComponent.from_cells(
                id="L000-C003",
                z=0,
                cells={(0, 0), (2, 0)},
            )

    def test_layer_at_rejects_out_of_range_index(self) -> None:
        extraction = extract_horizontal_layers(self.make_grid(set(), width=1, height=1, depth=1))

        with self.assertRaises(IndexError):
            extraction.layer_at(1)


if __name__ == "__main__":
    unittest.main()
