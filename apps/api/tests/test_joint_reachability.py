import unittest
from dataclasses import replace

from app.domain.decomposition import decompose_voxel_grid
from app.domain.joint_booleans import (
    JointBooleanExtraction,
    generate_joint_booleans,
)
from app.domain.joint_candidates import generate_joint_candidates
from app.domain.joint_reachability import (
    JointReachabilityConfig,
    JointReachabilityError,
    JointReachabilitySkipReason,
    SkippedJointReachability,
    generate_joint_reachability,
)
from app.domain.voxel import VoxelGrid


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


def make_booleans(*, depth: int) -> JointBooleanExtraction:
    decomposition = decompose_voxel_grid(ring_grid(depth=depth))
    candidates = generate_joint_candidates(decomposition.adjacency)
    return generate_joint_booleans(candidates)


class JointReachabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.thin_booleans = make_booleans(depth=1)
        cls.thin = generate_joint_reachability(cls.thin_booleans)
        cls.thick_booleans = make_booleans(depth=3)
        cls.thick = generate_joint_reachability(cls.thick_booleans)

    def test_11x11x1_has_four_reachable_booleans(self) -> None:
        self.assertEqual(self.thin_booleans.boolean_count, 4)
        self.assertEqual(self.thin.reachable_count, 4)
        self.assertEqual(self.thin.skipped_count, 0)
        self.assertEqual(self.thin.unhandled_booleans, ())
        self.assertEqual(
            [record.boolean_id for record in self.thin.reachable],
            ["J01", "J02", "J03", "J04"],
        )
        self.assertTrue(
            all(record.required_width_cells == 2 for record in self.thin.reachable)
        )
        self.assertTrue(
            all(record.path_width_cells >= 2 for record in self.thin.reachable)
        )

    def test_11x11x1_j01_has_exact_opening_and_slot_plane(self) -> None:
        record = self.thin.reachability_by_id("J01")
        boolean = self.thin_booleans.boolean_by_id("J01")

        self.assertEqual(record.id, "J01")
        self.assertTrue(record.is_reachable)
        self.assertEqual(record.required_width_cells, 2)
        self.assertEqual(record.path_width_cells, 3)
        self.assertEqual(record.plate_axes, (0, 1))
        self.assertEqual(record.thickness_axis, 2)
        self.assertEqual(record.thickness_value, 0)
        self.assertEqual(
            record.opening_cells,
            frozenset({(4, 0, 0), (5, 0, 0), (6, 0, 0)}),
        )
        self.assertTrue(record.opening_cells <= record.path_cells)
        self.assertTrue(record.path_cells.isdisjoint(boolean.plate_b_remaining_cells))
        self.assertTrue(all(cell[2] == 0 for cell in record.path_cells))

    def test_11x11x3_has_twelve_reachable_booleans(self) -> None:
        self.assertEqual(self.thick_booleans.boolean_count, 12)
        self.assertEqual(self.thick.reachable_count, 12)
        self.assertEqual(self.thick.skipped_count, 0)
        self.assertEqual(self.thick.unhandled_booleans, ())
        self.assertEqual(
            [record.boolean_id for record in self.thick.reachable],
            [
                "J02",
                "J03",
                "J04",
                "J05",
                "J07",
                "J08",
                "J09",
                "J10",
                "J11",
                "J12",
                "J13",
                "J14",
            ],
        )
        self.assertTrue(
            all(record.required_width_cells == 2 for record in self.thick.reachable)
        )
        self.assertTrue(
            all(record.path_width_cells == 3 for record in self.thick.reachable)
        )

    def test_vertical_through_slots_are_reachable(self) -> None:
        for boolean_id, z in (("J07", 1), ("J11", 2)):
            with self.subTest(boolean_id=boolean_id):
                record = self.thick.reachability_by_id(boolean_id)
                self.assertEqual(record.thickness_axis, 2)
                self.assertEqual(record.thickness_value, z)
                self.assertTrue(all(cell[2] == z for cell in record.path_cells))
                self.assertEqual(len(record.opening_cells), 3)

    def test_config_validation(self) -> None:
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(JointReachabilityError) as context:
                    JointReachabilityConfig(min_path_width_cells=value)  # type: ignore[arg-type]
                self.assertEqual(
                    context.exception.code,
                    "JOINT_REACHABILITY_INVALID_CONFIG",
                )

    def test_required_width_uses_config_and_reports_narrow_mouth(self) -> None:
        result = generate_joint_reachability(
            self.thin_booleans,
            JointReachabilityConfig(min_path_width_cells=4),
        )

        self.assertEqual(result.reachable_count, 0)
        self.assertEqual(result.skipped_count, 4)
        self.assertTrue(
            all(
                skipped.required_width_cells == 4
                and skipped.max_path_width_cells == 3
                and skipped.reason
                is JointReachabilitySkipReason.SLOT_OPENING_TOO_NARROW
                for skipped in result.skipped
            )
        )

    def test_empty_boolean_extraction_produces_empty_reachability(self) -> None:
        decomposition = decompose_voxel_grid(
            VoxelGrid(width=3, height=3, depth=1, occupied=frozenset())
        )
        booleans = generate_joint_booleans(
            generate_joint_candidates(decomposition.adjacency)
        )
        result = generate_joint_reachability(booleans)

        self.assertEqual(result.reachable, ())
        self.assertEqual(result.skipped, ())
        self.assertEqual(result.unhandled_booleans, ())
        self.assertEqual(result.source, booleans)
        self.assertEqual(result.boolean_extraction, booleans)
        with self.assertRaises(KeyError):
            result.reachability_by_id("J01")
        with self.assertRaises(JointReachabilityError) as context:
            result.reachable_for_plate("P01")
        self.assertEqual(context.exception.code, "JOINT_REACHABILITY_UNKNOWN_PLATE")

    def test_reachable_queries_by_edge_and_plate(self) -> None:
        self.assertEqual(
            [record.boolean_id for record in self.thick.reachable_for_edge("E02")],
            ["J02"],
        )
        self.assertEqual(
            [record.boolean_id for record in self.thick.reachable_for_plate("P01")],
            ["J02", "J03", "J04", "J05"],
        )
        self.assertEqual(self.thick.reachable_for_plate("P08"), ())
        self.assertEqual(self.thick.reachable_for_edge("E99"), ())
        self.assertEqual(self.thick.skipped_for_edge("E02"), ())
        with self.assertRaises(JointReachabilityError) as context:
            self.thick.reachable_for_plate("P99")
        self.assertEqual(context.exception.code, "JOINT_REACHABILITY_UNKNOWN_PLATE")

    def test_unhandled_booleans_are_reported(self) -> None:
        partial = replace(
            self.thick,
            reachable=(self.thick.reachable[0],),
            skipped=(),
        )

        self.assertEqual(
            [boolean.id for boolean in partial.unhandled_booleans],
            [
                "J03",
                "J04",
                "J05",
                "J07",
                "J08",
                "J09",
                "J10",
                "J11",
                "J12",
                "J13",
                "J14",
            ],
        )

    def test_reachability_record_validation(self) -> None:
        record = self.thin.reachability_by_id("J01")
        for kwargs in (
            {"boolean_id": ""},
            {"candidate_id": ""},
            {"contact_edge_id": ""},
            {"plate_a": "P02", "plate_b": "P01"},
            {"required_width_cells": 0},
            {"path_width_cells": 0},
            {"path_width_cells": 1},
            {"plate_axes": (0, 0)},
            {"plate_axes": (0, 3)},
            {"thickness_axis": 1},
            {"thickness_axis": 3},
            {"thickness_value": True},
            {"path_cells": frozenset()},
            {"opening_cells": frozenset()},
            {"opening_cells": frozenset({(99, 99, 0)})},
            {"path_cells": frozenset({(4, 0, 0)})},
            {"path_cells": frozenset({(4, 0, 1)})},
            {"path_cells": {(4, 0, 0)}},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(JointReachabilityError) as context:
                    replace(record, **kwargs)
                self.assertEqual(
                    context.exception.code,
                    "JOINT_REACHABILITY_INVALID_RECORD",
                )

    def test_skipped_record_validation(self) -> None:
        result = generate_joint_reachability(
            self.thin_booleans,
            JointReachabilityConfig(min_path_width_cells=4),
        )
        skipped = result.skipped[0]
        for kwargs in (
            {"boolean_id": ""},
            {"candidate_id": ""},
            {"contact_edge_id": ""},
            {"plate_a": "P02", "plate_b": "P01"},
            {"required_width_cells": 0},
            {"max_path_width_cells": -1},
            {"max_path_width_cells": True},
            {"reason": "path_too_narrow"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(JointReachabilityError) as context:
                    replace(skipped, **kwargs)
                self.assertEqual(
                    context.exception.code,
                    "JOINT_REACHABILITY_INVALID_RECORD",
                )

    def test_extraction_rejects_duplicate_reachable_id(self) -> None:
        first, second = self.thin.reachable[:2]
        duplicate = replace(second, boolean_id=first.boolean_id)

        with self.assertRaises(JointReachabilityError) as context:
            replace(self.thin, reachable=(first, duplicate))
        self.assertEqual(context.exception.code, "JOINT_REACHABILITY_DUPLICATE_ID")

    def test_extraction_rejects_unknown_boolean(self) -> None:
        record = replace(self.thin.reachable[0], boolean_id="J99")

        with self.assertRaises(JointReachabilityError) as context:
            replace(self.thin, reachable=(record,))
        self.assertEqual(context.exception.code, "JOINT_REACHABILITY_UNKNOWN_BOOLEAN")

    def test_extraction_rejects_duplicate_boolean(self) -> None:
        record = self.thin.reachable[0]
        skipped = SkippedJointReachability(
            boolean_id=record.boolean_id,
            candidate_id=record.candidate_id,
            contact_edge_id=record.contact_edge_id,
            plate_a=record.plate_a,
            plate_b=record.plate_b,
            required_width_cells=record.required_width_cells,
            max_path_width_cells=record.path_width_cells,
            reason=JointReachabilitySkipReason.PATH_TOO_NARROW,
        )

        with self.assertRaises(JointReachabilityError) as context:
            replace(self.thin, reachable=(record,), skipped=(skipped,))
        self.assertEqual(
            context.exception.code,
            "JOINT_REACHABILITY_DUPLICATE_BOOLEAN",
        )

    def test_extraction_rejects_boolean_metadata_mismatch(self) -> None:
        record = replace(self.thin.reachable[0], contact_edge_id="E99")

        with self.assertRaises(JointReachabilityError) as context:
            replace(self.thin, reachable=(record,))
        self.assertEqual(
            context.exception.code,
            "JOINT_REACHABILITY_BOOLEAN_MISMATCH",
        )

    def test_extraction_rejects_skipped_metadata_mismatch(self) -> None:
        result = generate_joint_reachability(
            self.thin_booleans,
            JointReachabilityConfig(min_path_width_cells=4),
        )
        skipped = replace(result.skipped[0], contact_edge_id="E99")

        with self.assertRaises(JointReachabilityError) as context:
            replace(result, skipped=(skipped,))
        self.assertEqual(
            context.exception.code,
            "JOINT_REACHABILITY_BOOLEAN_MISMATCH",
        )

    def test_extraction_rejects_unknown_skipped_boolean(self) -> None:
        result = generate_joint_reachability(
            self.thin_booleans,
            JointReachabilityConfig(min_path_width_cells=4),
        )
        skipped = replace(result.skipped[0], boolean_id="J99")

        with self.assertRaises(JointReachabilityError) as context:
            replace(result, skipped=(skipped,))
        self.assertEqual(context.exception.code, "JOINT_REACHABILITY_UNKNOWN_BOOLEAN")

    def test_slot_opening_must_be_on_plate_boundary(self) -> None:
        boolean = self.thin_booleans.boolean_by_id("J01")
        center = (1, 1, 0)
        remaining = frozenset(
            (x, y, 0)
            for x in range(3)
            for y in range(3)
            if (x, y, 0) != center
        )
        custom = replace(
            boolean,
            tongue_cells=frozenset({center}),
            tongue_root_cells=frozenset({center}),
            slot_cells=frozenset({center, (4, 0, 0)}),
            slot_opening_cells=frozenset({center}),
            slot_solid_cells=frozenset({center}),
            slot_air_cells=frozenset({(4, 0, 0)}),
            plate_b_remaining_cells=remaining,
            plate_intersection_cells=frozenset(),
        )
        extraction = JointBooleanExtraction(
            candidates=self.thin_booleans.candidates,
            booleans=(custom,),
        )

        result = generate_joint_reachability(extraction)

        self.assertEqual(result.reachable_count, 0)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(
            result.skipped[0].reason,
            JointReachabilitySkipReason.SLOT_OPENING_NOT_ON_PLATE_BOUNDARY,
        )

    def test_slot_opening_in_closed_hole_has_no_free_path(self) -> None:
        boolean = self.thin_booleans.boolean_by_id("J01")
        opening = (1, 2, 0)
        hole = (2, 2, 0)
        remaining = frozenset(
            (x, y, 0)
            for x in range(5)
            for y in range(5)
            if (x, y, 0) not in {opening, hole}
        )
        custom = replace(
            boolean,
            tongue_cells=frozenset({opening}),
            tongue_root_cells=frozenset({opening}),
            slot_cells=frozenset({opening, (4, 0, 0)}),
            slot_opening_cells=frozenset({opening}),
            slot_solid_cells=frozenset({opening}),
            slot_air_cells=frozenset({(4, 0, 0)}),
            plate_b_remaining_cells=remaining,
            plate_intersection_cells=frozenset(),
        )
        extraction = JointBooleanExtraction(
            candidates=self.thin_booleans.candidates,
            booleans=(custom,),
        )

        result = generate_joint_reachability(extraction)

        self.assertEqual(result.reachable_count, 0)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(
            result.skipped[0].reason,
            JointReachabilitySkipReason.NO_FREE_PATH_TO_PLATE_BOUNDARY,
        )


if __name__ == "__main__":
    unittest.main()
