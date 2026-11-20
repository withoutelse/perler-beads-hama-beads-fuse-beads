import unittest

from app.domain.contours import (
    Contour,
    ContourError,
    ContourKind,
    simplify_rectilinear_polygon,
    trace_horizontal_contours,
)
from app.domain.layers import extract_horizontal_layers
from app.domain.voxel import VoxelGrid


class ContourTests(unittest.TestCase):
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
        )

    def test_single_cell_traces_outer_square(self) -> None:
        extraction = trace_horizontal_contours(
            extract_horizontal_layers(self.make_grid({(0, 0, 0)}, width=1, height=1))
        )

        component = extraction.layer_at(0).components[0]
        self.assertEqual(component.contour_count, 1)
        self.assertEqual(component.hole_count, 0)
        self.assertEqual(component.outer.kind, ContourKind.OUTER)
        self.assertEqual(len(component.outer.vertices), 4)
        self.assertEqual(len(component.outer.simplified_vertices), 4)
        self.assertEqual(component.outer.area, 1.0)
        self.assertEqual(component.outer.closed_vertices()[0], component.outer.closed_vertices()[-1])

    def test_rectangle_simplifies_collinear_vertices(self) -> None:
        extraction = trace_horizontal_contours(
            extract_horizontal_layers(
                self.make_grid(
                    {(x, y, 0) for x in range(3) for y in range(2)},
                    width=3,
                    height=2,
                )
            )
        )

        outer = extraction.layer_at(0).components[0].outer
        self.assertEqual(len(outer.vertices), 10)
        self.assertEqual(len(outer.simplified_vertices), 4)
        self.assertEqual(outer.area, 6.0)
        self.assertEqual(outer.simplified_vertices, ((0, 0), (3, 0), (3, 2), (0, 2)))

    def test_ring_traces_outer_and_inner_hole(self) -> None:
        occupied = {
            (x, y, 0)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }
        extraction = trace_horizontal_contours(
            extract_horizontal_layers(self.make_grid(occupied, width=3, height=3))
        )

        component = extraction.layer_at(0).components[0]
        self.assertEqual(component.contour_count, 2)
        self.assertEqual(component.hole_count, 1)
        self.assertEqual(component.area, 8.0)
        self.assertEqual(component.outer.area, 9.0)
        self.assertEqual(component.holes[0].area, 1.0)
        self.assertEqual(component.holes[0].kind, ContourKind.HOLE)
        self.assertEqual(len(component.outer.simplified_vertices), 4)
        self.assertEqual(len(component.holes[0].simplified_vertices), 4)

    def test_l_shape_keeps_concave_vertices(self) -> None:
        extraction = trace_horizontal_contours(
            extract_horizontal_layers(
                self.make_grid(
                    {(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0)},
                    width=3,
                    height=2,
                )
            )
        )

        outer = extraction.layer_at(0).components[0].outer
        self.assertEqual(len(outer.vertices), 10)
        self.assertEqual(len(outer.simplified_vertices), 6)
        self.assertEqual(outer.area, 4.0)
        self.assertIn((1, 1), outer.simplified_vertices)

    def test_multiple_components_have_stable_ids(self) -> None:
        extraction = trace_horizontal_contours(
            extract_horizontal_layers(
                self.make_grid({(0, 0, 0), (2, 0, 0), (1, 1, 0)}, width=3, height=2)
            )
        )

        components = extraction.layer_at(0).components
        self.assertEqual(
            [component.component_id for component in components],
            ["L000-C001", "L000-C002", "L000-C003"],
        )
        self.assertEqual(
            [component.outer.id for component in components],
            ["L000-C001-O", "L000-C002-O", "L000-C003-O"],
        )
        self.assertEqual(extraction.contour_count, 3)

    def test_empty_layers_have_no_contours(self) -> None:
        extraction = trace_horizontal_contours(
            extract_horizontal_layers(self.make_grid(set(), width=1, height=1, depth=2))
        )

        self.assertEqual(extraction.contour_count, 0)
        self.assertEqual(extraction.hole_count, 0)
        self.assertEqual(extraction.area, 0.0)
        self.assertEqual(len(extraction.non_empty_layers()), 0)

    def test_multiple_holes_are_sorted_stably(self) -> None:
        occupied = {
            (x, y, 0)
            for x in range(5)
            for y in range(3)
            if (x, y) not in {(1, 1), (3, 1)}
        }
        extraction = trace_horizontal_contours(
            extract_horizontal_layers(self.make_grid(occupied, width=5, height=3))
        )

        component = extraction.layer_at(0).components[0]
        self.assertEqual(component.contour_count, 3)
        self.assertEqual(component.hole_count, 2)
        self.assertEqual(
            [hole.id for hole in component.holes],
            ["L000-C001-H001", "L000-C001-H002"],
        )
        self.assertEqual(component.area, 13.0)

    def test_simplification_removes_duplicate_and_collinear_vertices(self) -> None:
        simplified = simplify_rectilinear_polygon(
            (
                (0, 0),
                (1, 0),
                (2, 0),
                (2, 1),
                (2, 2),
                (1, 2),
                (0, 2),
                (0, 1),
                (0, 0),
            )
        )

        self.assertEqual(simplified, ((0, 0), (2, 0), (2, 2), (0, 2)))

    def test_contour_rejects_degenerate_or_invalid_vertices(self) -> None:
        with self.assertRaises(ContourError) as degenerate:
            Contour(
                id="C1",
                z=0,
                component_id="L000-C001",
                kind=ContourKind.OUTER,
                vertices=((0, 0), (1, 0), (2, 0), (3, 0)),
                simplified_vertices=((0, 0), (1, 0), (2, 0), (3, 0)),
            )
        self.assertEqual(degenerate.exception.code, "CONTOUR_DEGENERATE")

        with self.assertRaises(ContourError) as invalid:
            simplify_rectilinear_polygon(((0, 0), (1, 0), (2, 0)))
        self.assertEqual(invalid.exception.code, "CONTOUR_INVALID_VERTICES")


if __name__ == "__main__":
    unittest.main()
