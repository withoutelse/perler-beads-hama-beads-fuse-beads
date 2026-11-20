import unittest
from dataclasses import replace

from app.domain.bands import LayerBandExtraction, detect_layer_bands
from app.domain.contours import (
    LayerContourExtraction,
    trace_horizontal_contours,
)
from app.domain.layers import LayerExtraction, extract_horizontal_layers
from app.domain.plate import Plate, PlateKind
from app.domain.vertical_plates import (
    VerticalPlate,
    VerticalPlateConfig,
    VerticalPlateError,
    VerticalPlateExtraction,
    extract_vertical_plates,
)
from app.domain.voxel import VoxelGrid


class VerticalPlateTests(unittest.TestCase):
    def make_grid(
        self,
        occupied: set[tuple[int, int, int]],
        *,
        width: int = 5,
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
        config: VerticalPlateConfig | None = None,
        *,
        start_plate_index: int = 1,
    ) -> tuple[
        LayerExtraction,
        LayerContourExtraction,
        LayerBandExtraction,
        VerticalPlateExtraction,
    ]:
        layers = extract_horizontal_layers(grid)
        contours = trace_horizontal_contours(layers)
        bands = detect_layer_bands(layers, contours)
        return (
            layers,
            contours,
            bands,
            extract_vertical_plates(
                layers,
                contours,
                bands,
                config,
                start_plate_index=start_plate_index,
            ),
        )

    def test_rectangle_generates_four_straight_plates(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}

        _, _, bands, result = self.extract_all(self.make_grid(occupied))

        self.assertEqual(bands.band_count, 1)
        self.assertEqual(result.plate_count, 4)
        self.assertEqual([plate.width for plate in result.plates], [5, 3, 5, 3])
        self.assertEqual([plate.height for plate in result.plates], [1, 1, 1, 1])
        self.assertEqual(
            [plate.plate.id for plate in result.plates],
            ["P01", "P02", "P03", "P04"],
        )
        self.assertEqual(
            [plate.segment_index for plate in result.plates],
            [0, 1, 2, 3],
        )
        self.assertEqual(
            [plate.segment_count for plate in result.plates],
            [4, 4, 4, 4],
        )
        self.assertEqual(
            [plate.segment_number for plate in result.plates],
            [1, 2, 3, 4],
        )
        self.assertEqual(
            [(plate.start_vertex, plate.end_vertex) for plate in result.plates],
            [
                ((0, 0), (5, 0)),
                ((5, 0), (5, 3)),
                ((5, 3), (0, 3)),
                ((0, 3), (0, 0)),
            ],
        )
        self.assertTrue(all(plate.plate.kind is PlateKind.PERIMETER for plate in result.plates))
        self.assertTrue(all(plate.plate.holes == frozenset() for plate in result.plates))
        self.assertTrue(all(plate.plate.is_4_connected() for plate in result.plates))
        self.assertEqual(result.plates[0].plate.cells, frozenset((u, 0) for u in range(5)))
        self.assertEqual(result.plates[0].band_id, "B01")
        self.assertEqual(result.plates[0].component_id, "L000-C001")
        self.assertEqual(result.plates[0].contour_id, "L000-C001-O")
        self.assertEqual(result.plates[0].source_z, 0)
        self.assertEqual(result.plates[0].z, 0)
        self.assertEqual(result.plates[0].joint_margin_cells, 2)
        self.assertEqual(result.plates_in_band("B01"), result.plates)
        self.assertEqual(result.plates_at_z(0), result.plates)
        self.assertEqual(result.plates_for_component("L000-C001"), result.plates)
        self.assertEqual(result.plates_for_contour("L000-C001-O"), result.plates)
        self.assertEqual(result.plate_by_id("P01"), result.plates[0])

    def test_ring_uses_outer_contour_and_does_not_emit_hole_cells(self) -> None:
        occupied = {
            (x, y, 0)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }

        _, _, _, result = self.extract_all(
            self.make_grid(occupied, width=3, height=3)
        )

        self.assertEqual(result.plate_count, 4)
        self.assertEqual([plate.width for plate in result.plates], [3, 3, 3, 3])
        self.assertTrue(all(plate.plate.holes == frozenset() for plate in result.plates))
        self.assertEqual(result.plates[0].contour_id, "L000-C001-O")

    def test_l_shape_keeps_all_six_straight_edges(self) -> None:
        occupied = {
            (0, 0, 0),
            (1, 0, 0),
            (2, 0, 0),
            (0, 1, 0),
            (0, 2, 0),
        }

        _, _, _, result = self.extract_all(
            self.make_grid(occupied, width=3, height=3)
        )

        self.assertEqual(result.plate_count, 6)
        self.assertEqual([plate.width for plate in result.plates], [3, 1, 2, 2, 1, 3])
        self.assertEqual([plate.segment_index for plate in result.plates], list(range(6)))

    def test_cross_shape_is_capped_at_eight_segments(self) -> None:
        occupied = {
            (1, 0, 0),
            (0, 1, 0),
            (1, 1, 0),
            (2, 1, 0),
            (1, 2, 0),
        }

        _, _, _, result = self.extract_all(
            self.make_grid(occupied, width=3, height=3)
        )

        self.assertEqual(result.plate_count, 8)
        self.assertEqual([plate.width for plate in result.plates], [1, 2, 1, 2, 1, 2, 1, 2])
        self.assertEqual(sum(plate.width for plate in result.plates), 12)
        self.assertEqual([plate.segment_index for plate in result.plates], list(range(8)))

    def test_band_height_is_propagated_to_every_plate(self) -> None:
        occupied = {
            (x, y, z)
            for z in range(3)
            for x in range(5)
            for y in range(3)
        }

        _, _, bands, result = self.extract_all(self.make_grid(occupied, depth=3))

        self.assertEqual(bands.band_count, 1)
        self.assertEqual([plate.height for plate in result.plates], [3, 3, 3, 3])
        self.assertEqual([plate.source_z for plate in result.plates], [0, 0, 0, 0])
        self.assertEqual(len(result.plates[0].plate.color_by_cell), 15)
        self.assertEqual(len(result.plates[1].plate.color_by_cell), 9)
        self.assertEqual(result.plates_at_z(1), ())

    def test_multiple_bands_are_emitted_in_stable_order(self) -> None:
        occupied = {
            (x, y, z)
            for z in range(2)
            for x in range(5)
            for y in range(3)
        }
        colors = {voxel: "red" if voxel[2] == 0 else "blue" for voxel in occupied}

        _, _, bands, result = self.extract_all(
            self.make_grid(occupied, depth=2, color_by_voxel=colors)
        )

        self.assertEqual(
            [(band.id, band.z_start, band.z_end) for band in bands.bands],
            [("B01", 0, 0), ("B02", 1, 1)],
        )
        self.assertEqual(result.plate_count, 8)
        self.assertEqual(
            [plate.id for plate in result.plates],
            ["P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08"],
        )
        self.assertEqual(
            [plate.source_z for plate in result.plates],
            [0, 0, 0, 0, 1, 1, 1, 1],
        )
        self.assertEqual(
            [next(iter(plate.plate.color_by_cell.values())) for plate in result.plates],
            ["red", "red", "red", "red", "blue", "blue", "blue", "blue"],
        )
        self.assertEqual(result.plates_in_band("B01"), result.plates[:4])
        self.assertEqual(result.plates_in_band("B02"), result.plates[4:])

    def test_empty_bands_are_skipped(self) -> None:
        occupied = {
            (x, y, 1)
            for x in range(5)
            for y in range(3)
        }

        _, _, bands, result = self.extract_all(self.make_grid(occupied, depth=3))

        self.assertEqual(
            [(band.id, band.is_empty) for band in bands.bands],
            [("B01", True), ("B02", False), ("B03", True)],
        )
        self.assertEqual(result.plate_count, 4)
        self.assertEqual([plate.source_z for plate in result.plates], [1, 1, 1, 1])
        self.assertEqual(result.plates_at_z(0), ())
        self.assertEqual(result.plates_at_z(2), ())

    def test_multiple_components_have_stable_plate_and_component_ids(self) -> None:
        def ring(offset_x: int) -> set[tuple[int, int, int]]:
            return {
                (offset_x + x, y, 0)
                for x in range(3)
                for y in range(3)
                if (x, y) != (1, 1)
            }

        occupied = ring(0) | ring(4)

        _, _, _, result = self.extract_all(
            self.make_grid(occupied, width=7, height=3)
        )

        self.assertEqual(result.plate_count, 8)
        self.assertEqual(
            [plate.component_id for plate in result.plates],
            ["L000-C001"] * 4 + ["L000-C002"] * 4,
        )
        self.assertEqual(
            [plate.plate.id for plate in result.plates],
            [f"P{index:02d}" for index in range(1, 9)],
        )
        self.assertEqual(len(result.plates_for_component("L000-C001")), 4)
        self.assertEqual(len(result.plates_for_component("L000-C002")), 4)
        self.assertEqual(len(result.plates_for_contour("L000-C001-O")), 4)

    def test_colors_follow_the_interior_cell_of_each_contour_edge(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}
        colors = {
            (x, y, 0): "red" if x < 2 else "blue"
            for x, y, _ in occupied
        }

        _, _, _, result = self.extract_all(
            self.make_grid(occupied, color_by_voxel=colors)
        )

        self.assertEqual(
            [result.plates[0].plate.color_by_cell[(u, 0)] for u in range(5)],
            ["red", "red", "blue", "blue", "blue"],
        )
        self.assertEqual(
            [result.plates[1].plate.color_by_cell[(u, 0)] for u in range(3)],
            ["blue", "blue", "blue"],
        )
        self.assertEqual(
            [result.plates[2].plate.color_by_cell[(u, 0)] for u in range(5)],
            ["blue", "blue", "blue", "red", "red"],
        )
        self.assertEqual(
            [result.plates[3].plate.color_by_cell[(u, 0)] for u in range(3)],
            ["red", "red", "red"],
        )

    def test_joint_margins_are_recorded_and_reserved_cells_are_bounded(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}

        _, _, _, result = self.extract_all(
            self.make_grid(occupied),
            VerticalPlateConfig(joint_margin_cells=2),
        )

        first = result.plates[0]
        self.assertEqual(first.joint_margin_cells, 2)
        self.assertEqual(
            first.joint_reserved_cells,
            frozenset({(0, 0), (1, 0), (3, 0), (4, 0)}),
        )
        self.assertTrue(first.joint_reserved_cells <= first.plate.cells)

    def test_start_plate_index_offsets_ids(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}

        _, _, _, result = self.extract_all(
            self.make_grid(occupied),
            start_plate_index=10,
        )

        self.assertEqual(
            [plate.plate.id for plate in result.plates],
            ["P10", "P11", "P12", "P13"],
        )

    def test_invalid_config_is_rejected(self) -> None:
        for kwargs in (
            {"min_segments": 3},
            {"max_segments": 9},
            {"joint_margin_cells": -1},
            {"min_segments": True},
        ):
            with self.subTest(**kwargs):
                with self.assertRaises(VerticalPlateError) as context:
                    VerticalPlateConfig(**kwargs)  # type: ignore[arg-type]
                self.assertEqual(context.exception.code, "VERTICAL_INVALID_CONFIG")

    def test_start_plate_index_must_be_positive(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}
        layers, contours, bands, _ = self.extract_all(self.make_grid(occupied))

        with self.assertRaises(VerticalPlateError) as context:
            extract_vertical_plates(
                layers,
                contours,
                bands,
                start_plate_index=0,
            )
        self.assertEqual(context.exception.code, "VERTICAL_INVALID_CONFIG")

    def test_grid_dimension_mismatch_is_rejected(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}
        layers, contours, bands, _ = self.extract_all(self.make_grid(occupied))

        with self.assertRaises(VerticalPlateError) as context:
            extract_vertical_plates(layers, replace(contours, width=6), bands)
        self.assertEqual(context.exception.code, "VERTICAL_GRID_MISMATCH")

        with self.assertRaises(VerticalPlateError) as context:
            extract_vertical_plates(layers, contours, replace(bands, width=6))
        self.assertEqual(context.exception.code, "VERTICAL_GRID_MISMATCH")

    def test_component_id_mismatch_is_rejected(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}
        layers, contours, bands, _ = self.extract_all(self.make_grid(occupied))
        component = contours.layers[0].components[0]
        bad_outer = replace(component.outer, component_id="L000-C999")
        bad_component = replace(component, component_id="L000-C999", outer=bad_outer)
        bad_contours = replace(
            contours,
            layers=(replace(contours.layers[0], components=(bad_component,)),),
        )

        with self.assertRaises(VerticalPlateError) as context:
            extract_vertical_plates(layers, bad_contours, bands)
        self.assertEqual(context.exception.code, "VERTICAL_COMPONENT_MISMATCH")

    def test_invalid_contour_geometry_is_rejected(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}
        layers, contours, bands, _ = self.extract_all(self.make_grid(occupied))
        component = contours.layers[0].components[0]
        bad_outer = replace(
            component.outer,
            simplified_vertices=((0, 0), (5, 1), (5, 3), (0, 3)),
        )
        bad_component = replace(component, outer=bad_outer)
        bad_contours = replace(
            contours,
            layers=(replace(contours.layers[0], components=(bad_component,)),),
        )

        with self.assertRaises(VerticalPlateError) as context:
            extract_vertical_plates(layers, bad_contours, bands)
        self.assertEqual(context.exception.code, "VERTICAL_INVALID_CONTOUR")

    def test_contour_must_follow_component_boundary(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}
        layers, contours, bands, _ = self.extract_all(self.make_grid(occupied))
        component = contours.layers[0].components[0]
        bad_outer = replace(
            component.outer,
            simplified_vertices=((1, 1), (4, 1), (4, 2), (1, 2)),
        )
        bad_component = replace(component, outer=bad_outer)
        bad_contours = replace(
            contours,
            layers=(replace(contours.layers[0], components=(bad_component,)),),
        )

        with self.assertRaises(VerticalPlateError) as context:
            extract_vertical_plates(layers, bad_contours, bands)
        self.assertEqual(context.exception.code, "VERTICAL_INVALID_CONTOUR")

    def test_segment_count_below_minimum_is_rejected(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}
        layers, contours, bands, _ = self.extract_all(self.make_grid(occupied))

        with self.assertRaises(VerticalPlateError) as context:
            extract_vertical_plates(
                layers,
                contours,
                bands,
                VerticalPlateConfig(min_segments=8, max_segments=8),
            )
        self.assertEqual(context.exception.code, "VERTICAL_SEGMENT_COUNT_INVALID")

    def test_vertical_plate_record_rejects_invalid_kind(self) -> None:
        plate = Plate(
            id="P01",
            kind=PlateKind.CAP,
            cells=frozenset({(0, 0), (1, 0), (2, 0), (3, 0)}),
        )

        with self.assertRaises(VerticalPlateError) as context:
            VerticalPlate(
                plate=plate,
                band_id="B01",
                component_id="L000-C001",
                source_z=0,
                contour_id="L000-C001-O",
                segment_index=0,
                segment_count=4,
                start_vertex=(0, 0),
                end_vertex=(4, 0),
            )
        self.assertEqual(context.exception.code, "VERTICAL_KIND_INVALID")

    def test_vertical_plate_record_rejects_holes(self) -> None:
        plate = Plate(
            id="P01",
            kind=PlateKind.PERIMETER,
            cells=frozenset({(0, 0), (1, 0), (2, 0), (3, 0)}),
            holes=frozenset({(9, 9)}),
        )

        with self.assertRaises(VerticalPlateError) as context:
            VerticalPlate(
                plate=plate,
                band_id="B01",
                component_id="L000-C001",
                source_z=0,
                contour_id="L000-C001-O",
                segment_index=0,
                segment_count=4,
                start_vertex=(0, 0),
                end_vertex=(4, 0),
            )
        self.assertEqual(context.exception.code, "VERTICAL_INVALID_RECORD")

    def test_vertical_plate_record_rejects_disconnected_cells(self) -> None:
        plate = Plate(
            id="P01",
            kind=PlateKind.PERIMETER,
            cells=frozenset({(0, 0), (2, 0)}),
        )

        with self.assertRaises(VerticalPlateError) as context:
            VerticalPlate(
                plate=plate,
                band_id="B01",
                component_id="L000-C001",
                source_z=0,
                contour_id="L000-C001-O",
                segment_index=0,
                segment_count=4,
                start_vertex=(0, 0),
                end_vertex=(3, 0),
            )
        self.assertEqual(context.exception.code, "VERTICAL_DISCONNECTED")

    def test_vertical_plate_record_rejects_width_shorter_than_source_span(self) -> None:
        plate = Plate(
            id="P01",
            kind=PlateKind.PERIMETER,
            cells=frozenset({(0, 0), (1, 0), (2, 0), (3, 0)}),
        )

        with self.assertRaises(VerticalPlateError) as context:
            VerticalPlate(
                plate=plate,
                band_id="B01",
                component_id="L000-C001",
                source_z=0,
                contour_id="L000-C001-O",
                segment_index=0,
                segment_count=4,
                start_vertex=(0, 0),
                end_vertex=(5, 0),
            )
        self.assertEqual(context.exception.code, "VERTICAL_INVALID_RECORD")

    def test_extraction_rejects_duplicate_plate_ids(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}
        _, _, _, result = self.extract_all(self.make_grid(occupied))

        with self.assertRaises(VerticalPlateError) as context:
            replace(result, plates=(result.plates[0], result.plates[0]))
        self.assertEqual(context.exception.code, "VERTICAL_DUPLICATE_ID")

    def test_extraction_rejects_non_contiguous_segment_indices(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}
        _, _, _, result = self.extract_all(self.make_grid(occupied))

        with self.assertRaises(VerticalPlateError) as context:
            replace(result, plates=result.plates[:3])
        self.assertEqual(context.exception.code, "VERTICAL_SEGMENT_COUNT_INVALID")

    def test_extraction_rejects_duplicate_segment(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}
        _, _, _, result = self.extract_all(self.make_grid(occupied))
        duplicate = replace(result.plates[1], segment_index=0)

        with self.assertRaises(VerticalPlateError) as context:
            replace(result, plates=(result.plates[0], duplicate, *result.plates[2:]))
        self.assertEqual(context.exception.code, "VERTICAL_DUPLICATE_SEGMENT")

    def test_extraction_rejects_unknown_band(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}
        _, _, _, result = self.extract_all(self.make_grid(occupied))
        bad_record = replace(result.plates[0], band_id="B99")

        with self.assertRaises(VerticalPlateError) as context:
            replace(result, plates=(bad_record,))
        self.assertEqual(context.exception.code, "VERTICAL_BAND_MISMATCH")

    def test_extraction_rejects_source_z_outside_band(self) -> None:
        occupied = {(x, y, 0) for x in range(5) for y in range(3)}
        _, _, _, result = self.extract_all(self.make_grid(occupied))
        bad_record = replace(result.plates[0], source_z=1)

        with self.assertRaises(VerticalPlateError) as context:
            replace(result, plates=(bad_record,))
        self.assertEqual(context.exception.code, "VERTICAL_BAND_MISMATCH")

    def test_empty_extraction_is_valid(self) -> None:
        grid = self.make_grid(set(), width=2, height=2, depth=2)
        _, _, _, result = self.extract_all(grid)

        self.assertEqual(result.plates, ())
        self.assertEqual(result.plate_count, 0)
        self.assertEqual(result.segment_count, 0)


if __name__ == "__main__":
    unittest.main()
