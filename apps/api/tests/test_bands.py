import math
import unittest

from app.domain.bands import (
    BandError,
    BandSplitReason,
    BandTransition,
    LayerBand,
    LayerBandConfig,
    LayerBandExtraction,
    LayerBandMetrics,
    detect_layer_bands,
)
from app.domain.contours import trace_horizontal_contours
from app.domain.layers import extract_horizontal_layers
from app.domain.voxel import VoxelGrid


class LayerBandTests(unittest.TestCase):
    def make_grid(
        self,
        occupied: set[tuple[int, int, int]],
        *,
        width: int = 4,
        height: int = 4,
        depth: int = 4,
        color_by_voxel: dict[tuple[int, int, int], str] | None = None,
    ) -> VoxelGrid:
        colors = (
            color_by_voxel
            if color_by_voxel is not None
            else {voxel: "red" for voxel in occupied}
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
        config: LayerBandConfig | None = None,
    ) -> LayerBandExtraction:
        layers = extract_horizontal_layers(grid)
        contours = trace_horizontal_contours(layers)
        return detect_layer_bands(layers, contours, config)

    def test_uniform_stack_is_one_band(self) -> None:
        occupied = {
            (x, y, z)
            for z in range(3)
            for x in range(2)
            for y in range(2)
        }

        result = self.extract(self.make_grid(occupied, width=2, height=2, depth=3))

        self.assertEqual(result.band_count, 1)
        self.assertEqual(result.empty_band_count, 0)
        self.assertEqual(result.bands[0].id, "B01")
        self.assertEqual(result.bands[0].z_start, 0)
        self.assertEqual(result.bands[0].z_end, 2)
        self.assertEqual(result.bands[0].layer_indices, (0, 1, 2))
        self.assertEqual(result.bands[0].layer_count, 3)
        self.assertFalse(result.bands[0].is_empty)
        self.assertEqual(result.bands[0].split_reasons, ())
        self.assertEqual(result.transitions[0].reasons, ())
        self.assertEqual(result.transitions[1].reasons, ())
        self.assertEqual(result.band_at(1), result.bands[0])
        self.assertEqual(result, self.extract(self.make_grid(occupied, width=2, height=2, depth=3)))

    def test_color_change_splits_band(self) -> None:
        occupied = {
            (x, y, z)
            for z in range(4)
            for x in range(2)
            for y in range(2)
        }
        colors = {
            voxel: "red" if voxel[2] < 2 else "blue"
            for voxel in occupied
        }
        config = LayerBandConfig(
            color_distance_threshold=0.1,
            area_change_threshold=1.0,
            radius_change_threshold=1.0,
            hole_count_change_threshold=10,
            component_count_change_threshold=10,
        )

        result = self.extract(
            self.make_grid(occupied, width=2, height=2, depth=4, color_by_voxel=colors),
            config,
        )

        self.assertEqual(result.band_count, 2)
        self.assertEqual([band.layer_indices for band in result.bands], [(0, 1), (2, 3)])
        transition = result.transition_at(1)
        self.assertEqual(transition.reasons, (BandSplitReason.COLOR_DISTANCE,))
        self.assertAlmostEqual(transition.color_distance, 1.0)
        self.assertEqual(result.bands[1].split_reasons, (BandSplitReason.COLOR_DISTANCE,))

    def test_area_change_splits_band(self) -> None:
        occupied = {
            (x, y, z)
            for z in (0, 1)
            for x in range(2)
            for y in range(2)
        } | {
            (x, y, z)
            for z in (2, 3)
            for x in range(3)
            for y in range(3)
        }
        config = LayerBandConfig(
            color_distance_threshold=1.0,
            area_change_threshold=0.2,
            radius_change_threshold=1.0,
            hole_count_change_threshold=10,
            component_count_change_threshold=10,
        )

        result = self.extract(self.make_grid(occupied, width=3, height=3, depth=4), config)

        transition = result.transition_at(1)
        self.assertAlmostEqual(transition.lower.outer_area, 4.0)
        self.assertAlmostEqual(transition.upper.outer_area, 9.0)
        self.assertAlmostEqual(transition.area_change, 5.0 / 9.0)
        self.assertAlmostEqual(transition.radius_change, 1.0 / 3.0)
        self.assertEqual(transition.reasons, (BandSplitReason.AREA_CHANGE,))
        self.assertEqual(result.band_count, 2)

    def test_hole_count_change_splits_band(self) -> None:
        full = {
            (x, y, z)
            for z in (0, 1)
            for x in range(3)
            for y in range(3)
        }
        ring = {
            (x, y, z)
            for z in (2, 3)
            for x in range(3)
            for y in range(3)
            if (x, y) != (1, 1)
        }
        config = LayerBandConfig(
            color_distance_threshold=1.0,
            area_change_threshold=1.0,
            radius_change_threshold=1.0,
            hole_count_change_threshold=0,
            component_count_change_threshold=10,
        )

        result = self.extract(
            self.make_grid(full | ring, width=3, height=3, depth=4),
            config,
        )

        transition = result.transition_at(1)
        self.assertEqual(transition.hole_count_delta, 1)
        self.assertAlmostEqual(transition.lower.outer_area, 9.0)
        self.assertAlmostEqual(transition.upper.outer_area, 9.0)
        self.assertEqual(transition.reasons, (BandSplitReason.HOLE_COUNT_CHANGE,))

    def test_component_count_change_splits_band(self) -> None:
        full = {
            (x, y, z)
            for z in (0, 1)
            for x in range(3)
            for y in range(3)
        }
        split = {
            (0, 0, 2),
            (2, 2, 2),
            (0, 0, 3),
            (2, 2, 3),
        }
        config = LayerBandConfig(
            color_distance_threshold=1.0,
            area_change_threshold=1.0,
            radius_change_threshold=1.0,
            hole_count_change_threshold=10,
            component_count_change_threshold=0,
        )

        result = self.extract(
            self.make_grid(full | split, width=3, height=3, depth=4),
            config,
        )

        transition = result.transition_at(1)
        self.assertEqual(transition.component_count_delta, 1)
        self.assertEqual(transition.reasons, (BandSplitReason.COMPONENT_COUNT_CHANGE,))

    def test_empty_layer_forms_its_own_band(self) -> None:
        lower = {
            (x, y, z)
            for z in (0, 1)
            for x in range(2)
            for y in range(2)
        }
        upper = {
            (x, y, z)
            for z in (3, 4)
            for x in range(2)
            for y in range(2)
        }

        result = self.extract(
            self.make_grid(lower | upper, width=2, height=2, depth=5)
        )

        self.assertEqual(
            [(band.z_start, band.z_end, band.is_empty) for band in result.bands],
            [(0, 1, False), (2, 2, True), (3, 4, False)],
        )
        self.assertEqual(result.empty_band_count, 1)
        self.assertEqual(result.transition_at(1).reasons, (BandSplitReason.EMPTY_LAYER,))
        self.assertEqual(result.transition_at(2).reasons, (BandSplitReason.EMPTY_LAYER,))
        self.assertTrue(result.band_at(2).is_empty)
        self.assertEqual(result.non_empty_bands(), (result.bands[0], result.bands[2]))

    def test_all_empty_layers_are_one_empty_band(self) -> None:
        result = self.extract(self.make_grid(set(), width=2, height=2, depth=3))

        self.assertEqual(result.band_count, 1)
        self.assertTrue(result.bands[0].is_empty)
        self.assertEqual(result.bands[0].layer_indices, (0, 1, 2))
        self.assertEqual(result.transitions[0].reasons, ())
        self.assertEqual(result.transitions[1].reasons, ())

    def test_threshold_is_strict_and_histogram_handles_uncolored_cells(self) -> None:
        occupied = {(0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 0, 1)}
        colors = {
            (0, 0, 0): "red",
            (0, 0, 1): "red",
            (1, 0, 1): "red",
        }
        grid = self.make_grid(
            occupied,
            width=2,
            height=1,
            depth=2,
            color_by_voxel=colors,
        )
        at_threshold = LayerBandConfig(
            color_distance_threshold=0.5,
            area_change_threshold=1.0,
            radius_change_threshold=1.0,
            hole_count_change_threshold=10,
            component_count_change_threshold=10,
        )
        below_threshold = LayerBandConfig(
            color_distance_threshold=0.49,
            area_change_threshold=1.0,
            radius_change_threshold=1.0,
            hole_count_change_threshold=10,
            component_count_change_threshold=10,
        )

        at_result = self.extract(grid, at_threshold)
        below_result = self.extract(grid, below_threshold)

        self.assertEqual(at_result.band_count, 1)
        self.assertAlmostEqual(at_result.transition_at(0).color_distance, 0.5)
        self.assertEqual(below_result.band_count, 2)
        self.assertEqual(
            below_result.transition_at(0).reasons,
            (BandSplitReason.COLOR_DISTANCE,),
        )

    def test_invalid_thresholds_have_stable_error_code(self) -> None:
        invalid_configs = (
            {"color_distance_threshold": -0.1},
            {"area_change_threshold": float("nan")},
            {"radius_change_threshold": 1.1},
            {"hole_count_change_threshold": -1},
            {"hole_count_change_threshold": 1.0},
            {"component_count_change_threshold": True},
        )

        for kwargs in invalid_configs:
            with self.assertRaises(BandError) as raised:
                LayerBandConfig(**kwargs)
            self.assertEqual(raised.exception.code, "BAND_INVALID_CONFIG")

    def test_grid_and_contour_mismatches_are_rejected(self) -> None:
        layers = extract_horizontal_layers(
            self.make_grid({(0, 0, 0)}, width=2, height=2, depth=1)
        )
        wrong_grid_contours = trace_horizontal_contours(
            extract_horizontal_layers(
                self.make_grid({(0, 0, 0)}, width=3, height=2, depth=1)
            )
        )
        wrong_area_contours = trace_horizontal_contours(
            extract_horizontal_layers(
                self.make_grid({(0, 0, 0), (1, 0, 0)}, width=2, height=2, depth=1)
            )
        )

        with self.assertRaises(BandError) as grid_error:
            detect_layer_bands(layers, wrong_grid_contours)
        self.assertEqual(grid_error.exception.code, "BAND_GRID_MISMATCH")

        with self.assertRaises(BandError) as contour_error:
            detect_layer_bands(layers, wrong_area_contours)
        self.assertEqual(contour_error.exception.code, "BAND_CONTOUR_MISMATCH")

    def test_component_ids_must_match_between_inputs(self) -> None:
        layers = extract_horizontal_layers(
            self.make_grid({(0, 0, 0), (2, 0, 0)}, width=3, height=1, depth=1)
        )
        contours = trace_horizontal_contours(
            extract_horizontal_layers(
                self.make_grid({(0, 0, 0), (1, 0, 0)}, width=3, height=1, depth=1)
            )
        )

        with self.assertRaises(BandError) as raised:
            detect_layer_bands(layers, contours)
        self.assertEqual(raised.exception.code, "BAND_COMPONENT_MISMATCH")

    def test_band_and_transition_validation(self) -> None:
        with self.assertRaises(BandError) as band_error:
            LayerBand(id="B01", z_start=2, z_end=1, is_empty=False)
        self.assertEqual(band_error.exception.code, "BAND_INVALID_BAND")

        metrics = LayerBandMetrics(
            z=0,
            cell_count=1,
            outer_area=1.0,
            equivalent_radius=math.sqrt(1.0 / math.pi),
            hole_count=0,
            component_count=1,
        )
        with self.assertRaises(BandError) as transition_error:
            BandTransition(
                lower=metrics,
                upper=metrics,
                color_distance=0.0,
                area_change=0.0,
                radius_change=0.0,
                hole_count_delta=0,
                component_count_delta=0,
            )
        self.assertEqual(transition_error.exception.code, "BAND_INVALID_TRANSITION")


if __name__ == "__main__":
    unittest.main()
