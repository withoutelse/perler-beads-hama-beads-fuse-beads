import unittest
from dataclasses import replace

from app.domain.bands import LayerBandConfig, LayerBandExtraction, detect_layer_bands
from app.domain.contours import (
    Contour,
    ContourKind,
    LayerContourExtraction,
    trace_horizontal_contours,
)
from app.domain.horizontal_plates import (
    HorizontalPlate,
    HorizontalPlateError,
    HorizontalPlateExtraction,
    HorizontalPlateSkipReason,
    SkippedHorizontalComponent,
    extract_horizontal_plates,
)
from app.domain.layers import (
    Layer,
    LayerComponent,
    LayerExtraction,
    extract_horizontal_layers,
)
from app.domain.plate import Plate, PlateKind
from app.domain.voxel import VoxelGrid


class HorizontalPlateTests(unittest.TestCase):
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
        config: LayerBandConfig | None = None,
    ) -> tuple[
        LayerExtraction,
        LayerContourExtraction,
        LayerBandExtraction,
        HorizontalPlateExtraction,
    ]:
        layers = extract_horizontal_layers(grid)
        contours = trace_horizontal_contours(layers)
        bands = detect_layer_bands(layers, contours, config)
        return layers, contours, bands, extract_horizontal_plates(layers, contours, bands)

    def test_ring_component_generates_ring_plate_with_hole(self) -> None:
        occupied = {
            (x, y, 0)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }

        _, _, bands, result = self.extract_all(self.make_grid(occupied))

        self.assertEqual(bands.band_count, 1)
        self.assertEqual(result.plate_count, 1)
        self.assertEqual(result.skipped_count, 0)
        plate = result.plates[0]
        self.assertEqual(plate.id, "P01")
        self.assertEqual(plate.plate.kind, PlateKind.RING)
        self.assertEqual(plate.plate.cells, frozenset((x, y) for x, y, _ in occupied))
        self.assertEqual(plate.plate.holes, frozenset({(1, 1)}))
        self.assertEqual(plate.band_id, "B01")
        self.assertEqual(plate.z, 0)
        self.assertEqual(plate.component_id, "L000-C001")
        self.assertEqual(plate.outer_contour_id, "L000-C001-O")
        self.assertEqual(plate.hole_contour_ids, ("L000-C001-H001",))
        self.assertEqual(plate.hole_count, 1)
        self.assertTrue(plate.plate.is_4_connected())
        self.assertEqual(result.plates_at_z(0), (plate,))
        self.assertEqual(result.plates_in_band("B01"), (plate,))
        self.assertEqual(result.plate_by_id("P01"), plate)

    def test_solid_component_is_skipped_not_turned_into_solid_slice(self) -> None:
        occupied = {(x, y, 0) for x in range(2) for y in range(2)}

        _, _, _, result = self.extract_all(
            self.make_grid(occupied, width=2, height=2)
        )

        self.assertEqual(result.plates, ())
        self.assertEqual(result.plate_count, 0)
        self.assertEqual(result.skipped_count, 1)
        skipped = result.skipped[0]
        self.assertIsInstance(skipped, SkippedHorizontalComponent)
        self.assertEqual(skipped.reason, HorizontalPlateSkipReason.NO_INNER_HOLE)
        self.assertEqual(skipped.component_id, "L000-C001")
        self.assertEqual(skipped.outer_contour_id, "L000-C001-O")

    def test_multiple_holes_are_preserved(self) -> None:
        occupied = {
            (x, y, 0)
            for x in range(5)
            for y in range(3)
            if (x, y) not in {(1, 1), (3, 1)}
        }

        _, _, _, result = self.extract_all(
            self.make_grid(occupied, width=5, height=3)
        )

        self.assertEqual(result.plate_count, 1)
        plate = result.plates[0]
        self.assertEqual(plate.plate.holes, frozenset({(1, 1), (3, 1)}))
        self.assertEqual(
            plate.hole_contour_ids,
            ("L000-C001-H001", "L000-C001-H002"),
        )
        self.assertEqual(plate.hole_count, 2)
        self.assertEqual(len(plate.plate.cells), 13)

    def test_multiple_components_and_bands_have_stable_ids(self) -> None:
        def ring(offset_x: int, z: int) -> set[tuple[int, int, int]]:
            return {
                (offset_x + x, y, z)
                for x in range(3)
                for y in range(3)
                if (x, y) != (1, 1)
            }

        occupied = ring(0, 0) | ring(4, 0) | ring(0, 1) | ring(4, 1)
        colors = {voxel: "red" if voxel[2] == 0 else "blue" for voxel in occupied}
        grid = self.make_grid(
            occupied,
            width=7,
            height=3,
            depth=2,
            color_by_voxel=colors,
        )

        _, _, bands, result = self.extract_all(grid)

        self.assertEqual(
            [(band.id, band.z_start, band.z_end) for band in bands.bands],
            [("B01", 0, 0), ("B02", 1, 1)],
        )
        self.assertEqual(
            [plate.id for plate in result.plates],
            ["P01", "P02", "P03", "P04"],
        )
        self.assertEqual(
            [plate.component_id for plate in result.plates],
            ["L000-C001", "L000-C002", "L001-C001", "L001-C002"],
        )
        self.assertEqual(
            [plate.hole_contour_ids for plate in result.plates],
            [
                ("L000-C001-H001",),
                ("L000-C002-H001",),
                ("L001-C001-H001",),
                ("L001-C002-H001",),
            ],
        )
        self.assertEqual(result.plates_in_band("B01"), result.plates[:2])
        self.assertEqual(result.plates_in_band("B02"), result.plates[2:])
        self.assertEqual(result, self.extract_all(grid)[3])

    def test_empty_layers_are_ignored(self) -> None:
        occupied = {
            (x, y, 1)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }

        _, _, bands, result = self.extract_all(
            self.make_grid(occupied, depth=3)
        )

        self.assertEqual(
            [(band.id, band.is_empty) for band in bands.bands],
            [("B01", True), ("B02", False), ("B03", True)],
        )
        self.assertEqual(result.plate_count, 1)
        self.assertEqual(result.plates[0].z, 1)
        self.assertEqual(result.skipped, ())

    def test_all_empty_grid_has_no_records(self) -> None:
        _, _, _, result = self.extract_all(
            self.make_grid(set(), width=2, height=2, depth=2)
        )

        self.assertEqual(result.plates, ())
        self.assertEqual(result.skipped, ())
        self.assertEqual(result.plate_count, 0)
        self.assertEqual(result.skipped_count, 0)

    def test_grid_dimension_mismatch_is_rejected(self) -> None:
        ring = {
            (x, y, 0)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }
        layers, _, bands, _ = self.extract_all(self.make_grid(ring))
        other_layers = extract_horizontal_layers(
            self.make_grid(ring, width=4, height=4)
        )
        other_contours = trace_horizontal_contours(other_layers)

        with self.assertRaises(HorizontalPlateError) as context:
            extract_horizontal_plates(layers, other_contours, bands)
        self.assertEqual(context.exception.code, "PLATE_GRID_MISMATCH")

        with self.assertRaises(HorizontalPlateError) as context:
            extract_horizontal_plates(
                layers,
                trace_horizontal_contours(layers),
                replace(bands, width=4),
            )
        self.assertEqual(context.exception.code, "PLATE_GRID_MISMATCH")

    def test_component_id_mismatch_is_rejected(self) -> None:
        ring = {
            (x, y, 0)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }
        layers, contours, bands, _ = self.extract_all(self.make_grid(ring))
        component = contours.layers[0].components[0]
        bad_outer = replace(component.outer, component_id="L000-C999")
        bad_holes = tuple(
            replace(hole, component_id="L000-C999") for hole in component.holes
        )
        bad_component = replace(
            component,
            component_id="L000-C999",
            outer=bad_outer,
            holes=bad_holes,
        )
        bad_contours = replace(
            contours,
            layers=(replace(contours.layers[0], components=(bad_component,)),),
        )

        with self.assertRaises(HorizontalPlateError) as context:
            extract_horizontal_plates(layers, bad_contours, bands)
        self.assertEqual(context.exception.code, "PLATE_COMPONENT_MISMATCH")

    def test_hole_outside_outer_contour_is_rejected(self) -> None:
        solid = {(x, y, 0) for x in range(3) for y in range(3)}
        layers, contours, bands, _ = self.extract_all(self.make_grid(solid))
        component = contours.layers[0].components[0]
        outside_hole = Contour(
            id="L000-C001-H001",
            z=0,
            component_id=component.component_id,
            kind=ContourKind.HOLE,
            vertices=((3, 3), (3, 4), (4, 4), (4, 3)),
            simplified_vertices=((3, 3), (3, 4), (4, 4), (4, 3)),
        )
        bad_component = replace(component, holes=(outside_hole,))
        bad_contours = replace(
            contours,
            layers=(replace(contours.layers[0], components=(bad_component,)),),
        )

        with self.assertRaises(HorizontalPlateError) as context:
            extract_horizontal_plates(layers, bad_contours, bands)
        self.assertEqual(context.exception.code, "PLATE_HOLE_OUTSIDE")

    def test_hole_touching_outer_boundary_is_rejected(self) -> None:
        solid = {(x, y, 0) for x in range(3) for y in range(3)}
        layers, contours, bands, _ = self.extract_all(self.make_grid(solid))
        component = contours.layers[0].components[0]
        boundary_hole = Contour(
            id="L000-C001-H001",
            z=0,
            component_id=component.component_id,
            kind=ContourKind.HOLE,
            vertices=((0, 0), (0, 1), (1, 1), (1, 0)),
            simplified_vertices=((0, 0), (0, 1), (1, 1), (1, 0)),
        )
        bad_component = replace(component, holes=(boundary_hole,))
        bad_contours = replace(
            contours,
            layers=(replace(contours.layers[0], components=(bad_component,)),),
        )

        with self.assertRaises(HorizontalPlateError) as context:
            extract_horizontal_plates(layers, bad_contours, bands)
        self.assertEqual(context.exception.code, "PLATE_HOLE_OUTSIDE")

    def test_hole_overlapping_solid_cells_is_rejected(self) -> None:
        solid = {(x, y, 0) for x in range(3) for y in range(3)}
        ring = {
            (x, y, 0)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }
        solid_layers, _, solid_bands, _ = self.extract_all(self.make_grid(solid))
        _, ring_contours, _, _ = self.extract_all(self.make_grid(ring))

        with self.assertRaises(HorizontalPlateError) as context:
            extract_horizontal_plates(solid_layers, ring_contours, solid_bands)
        self.assertEqual(context.exception.code, "PLATE_HOLE_OVERLAP")

    def test_contour_cell_mismatch_is_rejected(self) -> None:
        ring = {
            (x, y, 0)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }
        _, ring_contours, ring_bands, _ = self.extract_all(self.make_grid(ring))
        cells = frozenset(
            {
                (1, 0),
                (2, 0),
                (0, 1),
                (2, 1),
                (0, 2),
                (1, 2),
                (2, 2),
            }
        )
        component = LayerComponent.from_cells(
            id="L000-C001",
            z=0,
            cells=cells,
            color_by_cell={cell: "orange" for cell in cells},
        )
        layer = Layer(
            z=0,
            cells=cells,
            color_by_cell={cell: "orange" for cell in cells},
            components=(component,),
            boundary_cells=component.boundary_cells,
            boundary_edges=component.boundary_edges,
        )
        layers = LayerExtraction(width=3, height=3, depth=1, layers=(layer,))

        with self.assertRaises(HorizontalPlateError) as context:
            extract_horizontal_plates(layers, ring_contours, ring_bands)
        self.assertEqual(context.exception.code, "PLATE_CONTOUR_MISMATCH")

    def test_overlapping_inner_holes_are_rejected(self) -> None:
        ring = {
            (x, y, 0)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }
        layers, contours, bands, _ = self.extract_all(self.make_grid(ring))
        component = contours.layers[0].components[0]
        first_hole = component.holes[0]
        second_hole = replace(first_hole, id="L000-C001-H002")
        bad_component = replace(component, holes=(first_hole, second_hole))
        bad_contours = replace(
            contours,
            layers=(replace(contours.layers[0], components=(bad_component,)),),
        )

        with self.assertRaises(HorizontalPlateError) as context:
            extract_horizontal_plates(layers, bad_contours, bands)
        self.assertEqual(context.exception.code, "PLATE_HOLE_OVERLAP")

    def test_horizontal_plate_record_rejects_invalid_kind(self) -> None:
        plate = Plate(
            id="P01",
            kind=PlateKind.CAP,
            cells=frozenset({(0, 0), (1, 0), (0, 1), (1, 1)}),
            holes=frozenset({(2, 2)}),
        )

        with self.assertRaises(HorizontalPlateError) as context:
            HorizontalPlate(
                plate=plate,
                band_id="B01",
                z=0,
                component_id="C1",
                outer_contour_id="O1",
                hole_contour_ids=("H1",),
            )
        self.assertEqual(context.exception.code, "PLATE_KIND_INVALID")

    def test_horizontal_plate_record_rejects_solid_slice(self) -> None:
        plate = Plate(
            id="P01",
            kind=PlateKind.RING,
            cells=frozenset({(0, 0), (1, 0), (0, 1), (1, 1)}),
        )

        with self.assertRaises(HorizontalPlateError) as context:
            HorizontalPlate(
                plate=plate,
                band_id="B01",
                z=0,
                component_id="C1",
                outer_contour_id="O1",
                hole_contour_ids=(),
            )
        self.assertEqual(context.exception.code, "PLATE_SOLID_SLICE_FORBIDDEN")

    def test_horizontal_plate_record_rejects_disconnected_cells(self) -> None:
        plate = Plate(
            id="P01",
            kind=PlateKind.RING,
            cells=frozenset({(0, 0), (2, 0)}),
            holes=frozenset({(1, 1)}),
        )

        with self.assertRaises(HorizontalPlateError) as context:
            HorizontalPlate(
                plate=plate,
                band_id="B01",
                z=0,
                component_id="C1",
                outer_contour_id="O1",
                hole_contour_ids=("H1",),
            )
        self.assertEqual(context.exception.code, "PLATE_DISCONNECTED")

    def test_horizontal_plate_record_rejects_duplicate_hole_ids(self) -> None:
        plate = Plate(
            id="P01",
            kind=PlateKind.RING,
            cells=frozenset({(0, 0), (1, 0), (0, 1), (1, 1)}),
            holes=frozenset({(2, 2), (3, 3)}),
        )

        with self.assertRaises(HorizontalPlateError) as context:
            HorizontalPlate(
                plate=plate,
                band_id="B01",
                z=0,
                component_id="C1",
                outer_contour_id="O1",
                hole_contour_ids=("H1", "H1"),
            )
        self.assertEqual(context.exception.code, "PLATE_INVALID_RECORD")

    def test_extraction_rejects_duplicate_plate_ids(self) -> None:
        ring = {
            (x, y, 0)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }
        _, _, _, result = self.extract_all(self.make_grid(ring))

        with self.assertRaises(HorizontalPlateError) as context:
            replace(result, plates=(result.plates[0], result.plates[0]))
        self.assertEqual(context.exception.code, "PLATE_DUPLICATE_ID")

    def test_extraction_rejects_plate_from_empty_band(self) -> None:
        ring = {
            (x, y, 0)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }
        _, _, bands, result = self.extract_all(self.make_grid(ring))
        empty_band = replace(bands.bands[0], is_empty=True)
        bad_bands = replace(bands, bands=(empty_band,))

        with self.assertRaises(HorizontalPlateError) as context:
            replace(result, bands=bad_bands)
        self.assertEqual(context.exception.code, "PLATE_BAND_MISMATCH")

    def test_horizontal_plate_record_rejects_more_hole_ids_than_cells(self) -> None:
        plate = Plate(
            id="P01",
            kind=PlateKind.RING,
            cells=frozenset({(0, 0), (1, 0), (0, 1), (1, 1)}),
            holes=frozenset({(2, 2)}),
        )

        with self.assertRaises(HorizontalPlateError) as context:
            HorizontalPlate(
                plate=plate,
                band_id="B01",
                z=0,
                component_id="C1",
                outer_contour_id="O1",
                hole_contour_ids=("H1", "H2"),
            )
        self.assertEqual(context.exception.code, "PLATE_INVALID_RECORD")


if __name__ == "__main__":
    unittest.main()
