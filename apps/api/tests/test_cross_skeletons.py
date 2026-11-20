import unittest
from dataclasses import replace

from app.domain.bands import detect_layer_bands
from app.domain.contours import trace_horizontal_contours
from app.domain.cross_skeletons import (
    CrossSkeleton,
    CrossSkeletonConfig,
    CrossSkeletonError,
    CrossSkeletonExtraction,
    CrossSkeletonSkipReason,
    extract_cross_skeletons,
)
from app.domain.horizontal_plates import extract_horizontal_plates
from app.domain.layers import extract_horizontal_layers
from app.domain.plate import Plate, PlateKind
from app.domain.voxel import VoxelGrid


class CrossSkeletonTests(unittest.TestCase):
    def make_grid(
        self,
        occupied: set[tuple[int, int, int]],
        *,
        width: int = 5,
        height: int = 5,
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

    def extract(
        self,
        grid: VoxelGrid,
        config: CrossSkeletonConfig | None = None,
        *,
        start_plate_index: int = 1,
    ) -> CrossSkeletonExtraction:
        layers = extract_horizontal_layers(grid)
        contours = trace_horizontal_contours(layers)
        bands = detect_layer_bands(layers, contours)
        horizontal = extract_horizontal_plates(layers, contours, bands)
        return extract_cross_skeletons(
            horizontal,
            config,
            start_plate_index=start_plate_index,
        )

    @staticmethod
    def ring(size: int = 5, z: int = 0, hole_size: int = 3) -> set[tuple[int, int, int]]:
        start = (size - hole_size) // 2
        return {
            (x, y, z)
            for x in range(size)
            for y in range(size)
            if not (start <= x < start + hole_size and start <= y < start + hole_size)
        }

    def test_three_by_three_hole_generates_plus_blank_with_clearance(self) -> None:
        result = self.extract(self.make_grid(self.ring(5, hole_size=3)))

        self.assertEqual(result.plate_count, 1)
        self.assertEqual(result.skipped_count, 0)
        record = result.plates[0]
        self.assertEqual(record.plate.id, "P01")
        self.assertEqual(record.plate.kind, PlateKind.CROSS_SKELETON)
        self.assertEqual(record.plate.cells, frozenset({(0, 1), (1, 0), (1, 1), (1, 2), (2, 1)}))
        self.assertEqual(record.source_cells, frozenset({(1, 2), (2, 1), (2, 2), (2, 3), (3, 2)}))
        self.assertEqual(record.clearance_cells, frozenset({(1, 1), (1, 3), (3, 1), (3, 3)}))
        self.assertEqual(record.hole_contour_ids, ("L000-C001-H001",))
        self.assertEqual(record.width, 3)
        self.assertEqual(record.height, 3)
        self.assertEqual(record.cell_count, 5)
        self.assertEqual(record.clearance_count, 4)
        self.assertEqual(record.arm_width_cells, 1)
        self.assertTrue(record.plate.is_4_connected())
        self.assertEqual(result.plates_at_z(0), (record,))
        self.assertEqual(result.plates_in_band("B01"), (record,))
        self.assertEqual(result.plate_by_id("P01"), record)

    def test_five_by_five_hole_uses_nine_cell_plus(self) -> None:
        result = self.extract(self.make_grid(self.ring(7, hole_size=5), width=7, height=7))

        record = result.plates[0]
        self.assertEqual(record.plate.cells, frozenset({(0, 2), (1, 2), (2, 0), (2, 1), (2, 2), (2, 3), (2, 4), (3, 2), (4, 2)}))
        self.assertEqual(record.cell_count, 9)
        self.assertEqual(record.clearance_count, 16)

    def test_multilayer_rings_produce_stable_stack_ids(self) -> None:
        occupied = self.ring(5, 0, 3) | self.ring(5, 1, 3) | self.ring(5, 2, 3)
        result = self.extract(self.make_grid(occupied, depth=3))

        self.assertEqual([record.plate.id for record in result.plates], ["P01", "P02", "P03"])
        self.assertEqual([record.z for record in result.plates], [0, 1, 2])
        self.assertEqual(len(result.plates_at_z(1)), 1)

    def test_start_plate_index_offsets_ids(self) -> None:
        result = self.extract(self.make_grid(self.ring(5, hole_size=3)), start_plate_index=7)

        self.assertEqual(result.plates[0].plate.id, "P07")

    def test_small_hole_is_skipped_instead_of_filling_it(self) -> None:
        occupied = self.ring(3, hole_size=1)
        result = self.extract(self.make_grid(occupied, width=3, height=3))

        self.assertEqual(result.plates, ())
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(result.skipped[0].reason, CrossSkeletonSkipReason.HOLE_TOO_SMALL)

    def test_c_shaped_hole_is_skipped_when_plus_does_not_fit(self) -> None:
        hole = {(1, 1), (2, 1), (3, 1), (1, 2), (1, 3)}
        occupied = {
            (x, y, 0)
            for x in range(5)
            for y in range(5)
            if (x, y) not in hole
        }
        result = self.extract(self.make_grid(occupied))

        self.assertEqual(result.plates, ())
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(
            result.skipped[0].reason,
            CrossSkeletonSkipReason.HOLE_SHAPE_UNSUPPORTED,
        )

    def test_largest_hole_is_selected_for_multiple_holes(self) -> None:
        occupied = {
            (x, y, 0)
            for x in range(7)
            for y in range(5)
            if not (1 <= x <= 3 and 1 <= y <= 3) and (x, y) != (5, 1)
        }
        result = self.extract(self.make_grid(occupied, width=7, height=5))

        self.assertEqual(result.plate_count, 1)
        self.assertEqual(result.plates[0].hole_contour_ids, ("L000-C001-H001",))
        self.assertEqual(result.plates[0].source_hole_cells, frozenset({(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3), (3, 1), (3, 2), (3, 3)}))

    def test_empty_horizontal_extraction_produces_empty_cross_extraction(self) -> None:
        occupied = {(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)}
        result = self.extract(self.make_grid(occupied, width=2, height=2))

        self.assertEqual(result.plates, ())
        self.assertEqual(result.skipped, ())
        self.assertEqual(result.plate_count, 0)

    def test_invalid_config_is_rejected(self) -> None:
        for kwargs in (
            {"arm_width_cells": 0},
            {"arm_width_cells": 2},
            {"min_clearance_cells": -1},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(CrossSkeletonError) as context:
                    CrossSkeletonConfig(**kwargs)  # type: ignore[arg-type]
                self.assertEqual(context.exception.code, "CROSS_INVALID_CONFIG")

    def test_record_validation(self) -> None:
        plate = Plate(
            id="P01",
            kind=PlateKind.CROSS_SKELETON,
            cells=frozenset({(0, 1), (1, 0), (1, 1), (1, 2), (2, 1)}),
        )
        valid = CrossSkeleton(
            plate=plate,
            band_id="B01",
            z=0,
            component_id="L000-C001",
            hole_contour_ids=("H1",),
            source_hole_cells=frozenset({(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3), (3, 1), (3, 2), (3, 3)}),
            source_cells=frozenset({(1, 2), (2, 1), (2, 2), (2, 3), (3, 2)}),
            clearance_cells=frozenset({(1, 1), (1, 3), (3, 1), (3, 3)}),
        )
        self.assertEqual(valid.cell_count, 5)

        for kwargs in (
            {"plate": replace(plate, kind=PlateKind.RING)},
            {"plate": replace(plate, holes=frozenset({(9, 9)}))},
            {"clearance_cells": frozenset()},
            {"source_cells": frozenset({(100, 100)})},
        ):
            values = {
                "plate": plate,
                "band_id": "B01",
                "z": 0,
                "component_id": "L000-C001",
                "hole_contour_ids": ("H1",),
                "source_hole_cells": frozenset({(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3), (3, 1), (3, 2), (3, 3)}),
                "source_cells": frozenset({(1, 2), (2, 1), (2, 2), (2, 3), (3, 2)}),
                "clearance_cells": frozenset({(1, 1), (1, 3), (3, 1), (3, 3)}),
            }
            values.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(CrossSkeletonError):
                CrossSkeleton(**values)  # type: ignore[arg-type]

    def test_extraction_rejects_duplicate_plate_ids(self) -> None:
        result = self.extract(self.make_grid(self.ring(5, hole_size=3)))

        with self.assertRaises(CrossSkeletonError) as context:
            replace(result, plates=(result.plates[0], result.plates[0]))
        self.assertEqual(context.exception.code, "CROSS_DUPLICATE_ID")

    def test_extraction_rejects_unknown_ring(self) -> None:
        result = self.extract(self.make_grid(self.ring(5, hole_size=3)))
        bad_record = replace(result.plates[0], component_id="L999-C999")

        with self.assertRaises(CrossSkeletonError) as context:
            replace(result, plates=(bad_record,))
        self.assertEqual(context.exception.code, "CROSS_PLATE_MISMATCH")


if __name__ == "__main__":
    unittest.main()
