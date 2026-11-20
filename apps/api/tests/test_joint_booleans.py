import json
import unittest
from dataclasses import replace
from pathlib import Path

from app.domain.bands import LayerBandConfig
from app.domain.cross_skeletons import CrossSkeletonConfig
from app.domain.decomposition import DecompositionConfig, decompose_voxel_grid
from app.domain.joint import JointDirection, JointType
from app.domain.joint_booleans import (
    JointBooleanConfig,
    JointBooleanError,
    JointBooleanExtraction,
    JointBooleanSkipReason,
    SkippedJointBoolean,
    generate_joint_booleans,
)
from app.domain.joint_candidates import (
    generate_joint_candidates,
)
from app.domain.plate_adjacency import PlateContactKind
from app.domain.vertical_plates import VerticalPlateConfig
from app.domain.voxel import VoxelGrid

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "fixtures" / "m3-decomposition.json"
)


def parse_cell3(value: list[int]) -> tuple[int, int, int]:
    return int(value[0]), int(value[1]), int(value[2])


def ring_grid(
    *,
    size: int = 11,
    hole_size: int = 3,
    depth: int = 1,
) -> VoxelGrid:
    start = (size - hole_size) // 2
    occupied = {
        (x, y, z)
        for z in range(depth)
        for x in range(size)
        for y in range(size)
        if not (
            start <= x < start + hole_size
            and start <= y < start + hole_size
        )
    }
    return VoxelGrid(
        width=size,
        height=size,
        depth=depth,
        occupied=frozenset(occupied),
        color_by_voxel={voxel: "orange" for voxel in occupied},
    )


class JointBooleanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        voxel_payload = payload["voxel_grid"]
        grid = VoxelGrid(
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
        config = payload["config"]
        decomposition = decompose_voxel_grid(
            grid,
            DecompositionConfig(
                band=LayerBandConfig(**config["band"]),
                vertical=VerticalPlateConfig(**config["vertical"]),
                cross_skeleton=CrossSkeletonConfig(**config["cross_skeleton"]),
            ),
        )
        cls.golden_candidates = generate_joint_candidates(decomposition.adjacency)
        cls.golden = generate_joint_booleans(cls.golden_candidates)

        thick_decomposition = decompose_voxel_grid(ring_grid())
        cls.thick_candidates = generate_joint_candidates(
            thick_decomposition.adjacency
        )
        cls.thick = generate_joint_booleans(cls.thick_candidates)

    def test_5x5_thin_wall_candidates_are_all_skipped(self) -> None:
        self.assertEqual(self.golden_candidates.candidate_count, 16)
        self.assertEqual(self.golden.boolean_count, 0)
        self.assertEqual(self.golden.skipped_count, 16)
        self.assertEqual(self.golden.unhandled_candidates, ())
        self.assertTrue(
            all(
                skipped.reason is JointBooleanSkipReason.WALL_TOO_THIN
                for skipped in self.golden.skipped
            )
        )
        self.assertEqual(
            [skipped.candidate_id for skipped in self.golden.skipped],
            [f"J{index:02d}" for index in range(1, 17)],
        )

    def test_11x11_thick_wall_generates_four_load_bearing_booleans(self) -> None:
        self.assertEqual(self.thick_candidates.candidate_count, 4)
        self.assertEqual(self.thick.boolean_count, 4)
        self.assertEqual(self.thick.skipped_count, 0)
        self.assertEqual(self.thick.unhandled_candidates, ())
        self.assertTrue(
            all(boolean.joint_type is JointType.LOAD_BEARING for boolean in self.thick.booleans)
        )
        self.assertTrue(
            all(boolean.wall_depth_cells == 4 for boolean in self.thick.booleans)
        )
        self.assertTrue(
            all(boolean.root_depth_cells == 4 for boolean in self.thick.booleans)
        )

    def test_11x11_j01_has_exact_tongue_slot_and_clearance(self) -> None:
        boolean = self.thick.boolean_by_id("J01")
        self.assertEqual(boolean.candidate_id, "J01")
        self.assertEqual(boolean.contact_edge_id, "E01")
        self.assertEqual((boolean.plate_a, boolean.plate_b), ("P01", "P02"))
        self.assertIs(boolean.contact_kind, PlateContactKind.FACE)
        self.assertIs(boolean.direction, JointDirection.Y_NEG)
        self.assertEqual((boolean.position, boolean.width, boolean.length), (4, 2, 3))
        self.assertEqual((boolean.slot_width, boolean.slot_length), (3, 4))
        self.assertEqual(
            boolean.tongue_cells,
            frozenset(
                {
                    (4, 0, 0),
                    (5, 0, 0),
                    (4, -1, 0),
                    (5, -1, 0),
                    (4, -2, 0),
                    (5, -2, 0),
                }
            ),
        )
        self.assertEqual(
            boolean.slot_cells,
            frozenset(
                (u, v, 0)
                for u in range(4, 7)
                for v in range(-3, 1)
            ),
        )
        self.assertEqual(boolean.clearance_count, 6)
        self.assertTrue(boolean.tongue_cells <= boolean.slot_cells)
        self.assertEqual(
            boolean.tongue_root_cells,
            frozenset(
                (u, v, 0)
                for u in range(4, 6)
                for v in range(4)
            ),
        )
        self.assertEqual(
            boolean.slot_opening_cells,
            frozenset({(4, 0, 0), (5, 0, 0), (6, 0, 0)}),
        )
        self.assertEqual(boolean.plate_intersection_cells, frozenset())
        self.assertTrue(
            boolean.tongue_cells.isdisjoint(boolean.plate_b_remaining_cells)
        )
        self.assertTrue(boolean.is_complementary)

    def test_11x11x3_emits_twelve_booleans_and_four_thin_pins(self) -> None:
        decomposition = decompose_voxel_grid(ring_grid(depth=3))
        candidates = generate_joint_candidates(decomposition.adjacency)
        result = generate_joint_booleans(candidates)

        self.assertEqual(candidates.candidate_count, 16)
        self.assertEqual(result.boolean_count, 12)
        self.assertEqual(result.skipped_count, 4)
        self.assertEqual(
            [skipped.candidate_id for skipped in result.skipped],
            ["J01", "J06", "J15", "J16"],
        )
        self.assertTrue(
            all(
                skipped.reason is JointBooleanSkipReason.WALL_TOO_THIN
                for skipped in result.skipped
            )
        )

    def test_7x7_ring_is_still_too_thin(self) -> None:
        decomposition = decompose_voxel_grid(ring_grid(size=7, depth=3))
        result = generate_joint_booleans(
            generate_joint_candidates(decomposition.adjacency)
        )

        self.assertEqual(result.boolean_count, 0)
        self.assertEqual(result.skipped_count, 16)
        self.assertTrue(
            all(
                skipped.reason is JointBooleanSkipReason.WALL_TOO_THIN
                for skipped in result.skipped
            )
        )

    def test_empty_candidate_extraction_produces_empty_boolean_extraction(self) -> None:
        empty_decomposition = decompose_voxel_grid(
            VoxelGrid(
                width=3,
                height=3,
                depth=1,
                occupied=frozenset(),
            )
        )
        candidates = generate_joint_candidates(empty_decomposition.adjacency)
        result = generate_joint_booleans(candidates)

        self.assertEqual(result.booleans, ())
        self.assertEqual(result.skipped, ())
        self.assertEqual(result.unhandled_candidates, ())
        with self.assertRaises(JointBooleanError) as context:
            result.booleans_for_plate("P01")
        self.assertEqual(context.exception.code, "JOINT_BOOLEAN_UNKNOWN_PLATE")

    def test_config_validation(self) -> None:
        for kwargs in (
            {"min_root_depth_cells": 1},
            {"pin_root_depth_cells": 0},
            {"min_slot_opening_cells": 0},
            {"require_wall_depth_cells": 1},
            {"allow_slot_air_cells": 0},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(JointBooleanError) as context:
                    JointBooleanConfig(**kwargs)  # type: ignore[arg-type]
                self.assertEqual(
                    context.exception.code,
                    "JOINT_BOOLEAN_INVALID_CONFIG",
                )

    def test_slot_air_cells_can_be_rejected(self) -> None:
        result = generate_joint_booleans(
            self.thick_candidates,
            JointBooleanConfig(allow_slot_air_cells=False),
        )

        self.assertEqual(result.boolean_count, 0)
        self.assertEqual(result.skipped_count, 4)
        self.assertTrue(
            all(
                skipped.reason is JointBooleanSkipReason.SLOT_NOT_OPEN_TO_BOUNDARY
                for skipped in result.skipped
            )
        )

    def test_wall_depth_can_be_disabled_to_expose_root_rule(self) -> None:
        result = generate_joint_booleans(
            self.golden_candidates,
            JointBooleanConfig(require_wall_depth_cells=False),
        )

        self.assertEqual(result.boolean_count, 4)
        self.assertEqual(result.skipped_count, 12)
        self.assertTrue(
            all(
                skipped.reason is JointBooleanSkipReason.TONGUE_ROOT_TOO_SHORT
                for skipped in result.skipped
            )
        )

    def test_boolean_record_validation(self) -> None:
        boolean = self.thick.boolean_by_id("J01")
        for kwargs in (
            {"id": ""},
            {"candidate_id": ""},
            {"contact_edge_id": ""},
            {"plate_a": "P02", "plate_b": "P01"},
            {"position": -1},
            {"width": 0},
            {"length": 0},
            {"slot_clearance_cells": 0},
            {"contact_length": 0},
            {"edge_margin_cells": -1},
            {"tongue_cells": frozenset()},
            {"slot_cells": frozenset()},
            {"tongue_cells": frozenset({(99, 99, 99)})},
            {"slot_cells": boolean.tongue_cells},
            {"tongue_root_cells": frozenset()},
            {"slot_opening_cells": frozenset()},
            {"slot_solid_cells": frozenset()},
            {"plate_intersection_cells": frozenset({(4, 0, 0)})},
            {"root_depth_cells": 99},
            {"wall_depth_cells": 1},
            {"u_axis": (1, 1, 0)},
            {"v_axis": (1, 0, 0)},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(JointBooleanError) as context:
                    replace(boolean, **kwargs)
                self.assertEqual(
                    context.exception.code,
                    "JOINT_BOOLEAN_INVALID_RECORD",
                )

    def test_skipped_record_validation(self) -> None:
        skipped = self.golden.skipped[0]
        for kwargs in (
            {"candidate_id": ""},
            {"contact_edge_id": ""},
            {"plate_a": "P02", "plate_b": "P01"},
            {"contact_length": 0},
            {"reason": "wall_too_thin"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(JointBooleanError) as context:
                    replace(skipped, **kwargs)
                self.assertEqual(
                    context.exception.code,
                    "JOINT_BOOLEAN_INVALID_RECORD",
                )

    def test_extraction_rejects_duplicate_boolean_id(self) -> None:
        boolean = self.thick.booleans[0]
        duplicate = replace(boolean, candidate_id=self.thick.booleans[1].candidate_id)

        with self.assertRaises(JointBooleanError) as context:
            replace(self.thick, booleans=(boolean, duplicate))
        self.assertEqual(context.exception.code, "JOINT_BOOLEAN_DUPLICATE_ID")

    def test_extraction_rejects_unknown_candidate(self) -> None:
        boolean = replace(self.thick.booleans[0], candidate_id="J99")

        with self.assertRaises(JointBooleanError) as context:
            replace(self.thick, booleans=(boolean,))
        self.assertEqual(context.exception.code, "JOINT_BOOLEAN_UNKNOWN_CANDIDATE")

    def test_extraction_rejects_duplicate_candidate(self) -> None:
        boolean = self.thick.booleans[0]
        duplicate = replace(
            self.thick.booleans[1],
            id="J99",
            candidate_id=boolean.candidate_id,
        )

        with self.assertRaises(JointBooleanError) as context:
            replace(self.thick, booleans=(boolean, duplicate))
        self.assertEqual(
            context.exception.code,
            "JOINT_BOOLEAN_DUPLICATE_CANDIDATE",
        )

    def test_extraction_rejects_candidate_both_emitted_and_skipped(self) -> None:
        boolean = self.thick.booleans[0]
        skipped = SkippedJointBoolean(
            candidate_id=boolean.candidate_id,
            contact_edge_id=boolean.contact_edge_id,
            plate_a=boolean.plate_a,
            plate_b=boolean.plate_b,
            contact_kind=boolean.contact_kind,
            direction=boolean.direction,
            contact_length=boolean.contact_length,
            joint_type=boolean.joint_type,
            reason=JointBooleanSkipReason.WALL_TOO_THIN,
        )

        with self.assertRaises(JointBooleanError) as context:
            replace(self.thick, skipped=(skipped,))
        self.assertEqual(
            context.exception.code,
            "JOINT_BOOLEAN_DUPLICATE_CANDIDATE",
        )

    def test_extraction_rejects_boolean_candidate_mismatch(self) -> None:
        boolean = replace(self.thick.booleans[0], contact_edge_id="E99")

        with self.assertRaises(JointBooleanError) as context:
            replace(self.thick, booleans=(boolean,))
        self.assertEqual(
            context.exception.code,
            "JOINT_BOOLEAN_CANDIDATE_MISMATCH",
        )

    def test_extraction_rejects_skipped_candidate_mismatch(self) -> None:
        skipped = replace(self.golden.skipped[0], contact_edge_id="E99")

        with self.assertRaises(JointBooleanError) as context:
            replace(self.golden, skipped=(skipped,))
        self.assertEqual(
            context.exception.code,
            "JOINT_BOOLEAN_CANDIDATE_MISMATCH",
        )

    def test_unhandled_candidates_are_reported(self) -> None:
        partial = replace(
            self.thick,
            booleans=(self.thick.booleans[0],),
            skipped=(),
        )

        self.assertEqual(
            [candidate.id for candidate in partial.unhandled_candidates],
            ["J02", "J03", "J04"],
        )

    def test_booleans_for_plate_and_edge(self) -> None:
        self.assertEqual(
            [boolean.id for boolean in self.thick.booleans_for_plate("P01")],
            ["J01", "J02", "J03", "J04"],
        )
        self.assertEqual(
            [boolean.id for boolean in self.thick.booleans_for_edge("E01")],
            ["J01"],
        )
        self.assertEqual(self.thick.booleans_for_edge("E99"), ())
        self.assertEqual(self.thick.skipped_for_edge("E01"), ())

    def test_manual_empty_extraction(self) -> None:
        empty_decomposition = decompose_voxel_grid(
            VoxelGrid(width=3, height=3, depth=1, occupied=frozenset())
        )
        candidates = generate_joint_candidates(empty_decomposition.adjacency)
        extraction = JointBooleanExtraction(candidates=candidates)

        self.assertEqual(extraction.booleans, ())
        self.assertEqual(extraction.skipped, ())
        self.assertEqual(extraction.source, candidates)
        self.assertEqual(extraction.candidate_extraction, candidates)
        with self.assertRaises(KeyError):
            extraction.boolean_by_id("J01")


if __name__ == "__main__":
    unittest.main()
