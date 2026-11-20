import unittest
from dataclasses import replace

from app.domain.decomposition import decompose_voxel_grid
from app.domain.joint import JointDirection, JointType
from app.domain.joint_booleans import (
    JointBooleanExtraction,
    generate_joint_booleans,
)
from app.domain.joint_candidates import (
    JointCandidate,
    JointCandidateExtraction,
    generate_joint_candidates,
)
from app.domain.joint_reachability import (
    JointReachabilityConfig,
    generate_joint_reachability,
)
from app.domain.joint_spacing import (
    JointSpacingConfig,
    JointSpacingError,
    JointSpacingSkipReason,
    SkippedJointSpacing,
    generate_joint_spacing,
)
from app.domain.plate_adjacency import (
    PlateContactEdge,
    PlateContactGraph,
    PlateContactKind,
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


def make_reachability(*, depth: int = 1):
    decomposition = decompose_voxel_grid(ring_grid(depth=depth))
    candidates = generate_joint_candidates(decomposition.adjacency)
    booleans = generate_joint_booleans(candidates)
    return generate_joint_reachability(booleans)


def make_same_edge_reachability(
    *,
    positions: tuple[int, ...] = (2, 6),
    widths: tuple[int, ...] | None = None,
    edge_margin_cells: int = 2,
):
    if widths is None:
        widths = tuple(2 for _ in positions)
    decomposition = decompose_voxel_grid(ring_grid(size=12))
    adjacency = decomposition.adjacency
    edges = tuple(
        PlateContactEdge(
            id=f"E{index:02d}",
            plate_a="P01",
            plate_b="P02",
            kind=PlateContactKind.FACE,
            direction=JointDirection.Y_NEG,
            position=index,
            contact_length=12,
            contact_edge="same-edge",
        )
        for index in range(1, len(positions) + 1)
    )
    graph = PlateContactGraph(nodes=adjacency.graph.nodes, edges=edges)
    custom_adjacency = replace(adjacency, graph=graph)
    candidates = tuple(
        JointCandidate(
            id=f"J{index:02d}",
            contact_edge_id=f"E{index:02d}",
            plate_a="P01",
            plate_b="P02",
            contact_kind=PlateContactKind.FACE,
            direction=JointDirection.Y_NEG,
            position=position,
            width=width,
            length=3,
            joint_type=JointType.LOAD_BEARING,
            slot_clearance_cells=1,
            contact_length=12,
            edge_margin_cells=edge_margin_cells,
        )
        for index, (position, width) in enumerate(
            zip(positions, widths, strict=True),
            start=1,
        )
    )
    candidate_extraction = JointCandidateExtraction(
        adjacency=custom_adjacency,
        candidates=candidates,
    )
    booleans = generate_joint_booleans(candidate_extraction)
    return generate_joint_reachability(booleans)


def make_shared_plate_b_reachability():
    """Two tongues on different plates sharing one slot-plate edge."""

    base = make_same_edge_reachability(positions=(2, 5))
    plate_by_joint = {"J01": "P01", "J02": "P02"}
    edges = tuple(
        replace(
            edge,
            plate_a=plate_by_joint[edge.id.replace("E", "J")],
            plate_b="P03",
            contact_edge="shared-b-edge",
        )
        for edge in base.graph.edges
    )
    graph = PlateContactGraph(nodes=base.graph.nodes, edges=edges)
    adjacency = replace(base.booleans.candidates.adjacency, graph=graph)
    candidates = tuple(
        replace(
            candidate,
            plate_a=plate_by_joint[candidate.id],
            plate_b="P03",
        )
        for candidate in base.booleans.candidates.candidates
    )
    candidate_extraction = JointCandidateExtraction(
        adjacency=adjacency,
        candidates=candidates,
    )
    booleans = tuple(
        replace(
            boolean,
            plate_a=plate_by_joint[boolean.id],
            plate_b="P03",
        )
        for boolean in base.booleans.booleans
    )
    boolean_extraction = JointBooleanExtraction(
        candidates=candidate_extraction,
        booleans=booleans,
    )
    reachable = tuple(
        replace(
            record,
            plate_a=plate_by_joint[record.boolean_id],
            plate_b="P03",
        )
        for record in base.reachable
    )
    return replace(
        base,
        booleans=boolean_extraction,
        reachable=reachable,
    )


class JointSpacingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reachability = make_reachability()
        cls.spacing = generate_joint_spacing(cls.reachability)

    def test_11x11x1_accepts_all_reachable_joints(self) -> None:
        self.assertEqual(self.reachability.reachable_count, 4)
        self.assertEqual(self.spacing.accepted_count, 4)
        self.assertEqual(self.spacing.skipped_count, 0)
        self.assertEqual(self.spacing.unhandled_reachable, ())
        self.assertEqual(
            [record.boolean_id for record in self.spacing.accepted],
            ["J01", "J02", "J03", "J04"],
        )
        self.assertTrue(
            all(record.required_gap_before_cells is None for record in self.spacing.accepted)
        )
        self.assertTrue(
            all(record.required_gap_after_cells is None for record in self.spacing.accepted)
        )

    def test_same_edge_exact_spacing_is_accepted(self) -> None:
        reachability = make_same_edge_reachability(positions=(2, 6))
        result = generate_joint_spacing(reachability)

        self.assertEqual(result.accepted_count, 2)
        self.assertEqual(result.skipped_count, 0)
        first, second = result.accepted
        self.assertEqual(first.previous_joint_id, None)
        self.assertEqual(first.next_joint_id, "J02")
        self.assertEqual(first.gap_after_cells, 4)
        self.assertEqual(first.slot_gap_after_cells, 1)
        self.assertEqual(first.required_gap_after_cells, 4)
        self.assertEqual(second.previous_joint_id, "J01")
        self.assertEqual(second.next_joint_id, None)
        self.assertEqual(second.gap_before_cells, 4)
        self.assertEqual(second.slot_gap_before_cells, 1)
        self.assertEqual(second.required_gap_before_cells, 4)

    def test_same_edge_too_close_records_spacing_skip(self) -> None:
        reachability = make_same_edge_reachability(positions=(2, 5))
        result = generate_joint_spacing(reachability)

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(result.accepted[0].boolean_id, "J01")
        skipped = result.skipped[0]
        self.assertEqual(skipped.boolean_id, "J02")
        self.assertEqual(skipped.reason, JointSpacingSkipReason.CONTINUOUS_SLOT)
        self.assertEqual(skipped.conflict_joint_id, "J01")
        self.assertEqual(skipped.actual_gap_cells, 3)
        self.assertEqual(skipped.slot_gap_cells, 0)
        self.assertEqual(skipped.required_gap_cells, 4)

    def test_same_edge_spacing_uses_max_width(self) -> None:
        reachability = make_same_edge_reachability(
            positions=(2, 7),
            widths=(3, 2),
        )
        result = generate_joint_spacing(reachability)

        self.assertEqual(result.accepted_count, 2)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(result.accepted[0].required_gap_after_cells, 5)
        self.assertEqual(result.accepted[1].required_gap_before_cells, 5)

    def test_same_edge_spacing_too_narrow_records_reason(self) -> None:
        reachability = make_same_edge_reachability(
            positions=(2, 6),
            widths=(2, 3),
        )
        result = generate_joint_spacing(reachability)

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.skipped_count, 1)
        skipped = result.skipped[0]
        self.assertEqual(skipped.boolean_id, "J02")
        self.assertEqual(skipped.reason, JointSpacingSkipReason.SPACING_TOO_NARROW)
        self.assertEqual(skipped.required_gap_cells, 5)
        self.assertEqual(skipped.actual_gap_cells, 4)
        self.assertEqual(skipped.slot_gap_cells, 1)

    def test_edge_margin_insufficient_records_reason(self) -> None:
        reachability = make_same_edge_reachability(
            positions=(1, 6),
            edge_margin_cells=1,
        )
        result = generate_joint_spacing(reachability)

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.skipped_count, 1)
        skipped = result.skipped[0]
        self.assertEqual(skipped.boolean_id, "J01")
        self.assertEqual(
            skipped.reason,
            JointSpacingSkipReason.EDGE_MARGIN_INSUFFICIENT,
        )
        self.assertEqual(skipped.required_gap_cells, 2)
        self.assertEqual(skipped.actual_gap_cells, 1)

    def test_shared_plate_b_edge_is_checked(self) -> None:
        reachability = make_shared_plate_b_reachability()
        result = generate_joint_spacing(reachability)

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(result.accepted[0].boolean_id, "J01")
        skipped = result.skipped[0]
        self.assertEqual(skipped.boolean_id, "J02")
        self.assertEqual(skipped.plate_a, "P02")
        self.assertEqual(skipped.plate_b, "P03")
        self.assertEqual(skipped.reason, JointSpacingSkipReason.CONTINUOUS_SLOT)
        self.assertEqual(skipped.conflict_joint_id, "J01")

    def test_config_validation(self) -> None:
        for value in (0, 1, -1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(JointSpacingError) as context:
                    JointSpacingConfig(min_gap_cells=value)  # type: ignore[arg-type]
                self.assertEqual(
                    context.exception.code,
                    "JOINT_SPACING_INVALID_CONFIG",
                )
        for value in (0, 1, -1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(JointSpacingError) as context:
                    JointSpacingConfig(min_edge_margin_cells=value)  # type: ignore[arg-type]
                self.assertEqual(
                    context.exception.code,
                    "JOINT_SPACING_INVALID_CONFIG",
                )

    def test_spacing_record_validation(self) -> None:
        record = self.spacing.accepted[0]
        for kwargs in (
            {"reachability": object()},
            {"plate_id": ""},
            {"plate_id": "P02"},
            {"contact_edge": ""},
            {"previous_joint_id": "J01"},
            {"previous_joint_id": "J02", "gap_before_cells": 4},
            {
                "previous_joint_id": "J02",
                "gap_before_cells": 3,
                "slot_gap_before_cells": 1,
                "required_gap_before_cells": 4,
            },
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(JointSpacingError) as context:
                    replace(record, **kwargs)
                self.assertEqual(
                    context.exception.code,
                    "JOINT_SPACING_INVALID_RECORD",
                )

    def test_skipped_record_validation(self) -> None:
        result = generate_joint_spacing(
            make_same_edge_reachability(positions=(2, 5))
        )
        skipped = result.skipped[0]
        for kwargs in (
            {"boolean_id": ""},
            {"candidate_id": ""},
            {"contact_edge_id": ""},
            {"plate_a": "P02", "plate_b": "P01"},
            {"contact_edge": ""},
            {"width": 0},
            {"slot_width": 2},
            {"required_gap_cells": 0},
            {"actual_gap_cells": -1},
            {"slot_gap_cells": -1},
            {"reason": "continuous_slot"},
            {"conflict_joint_id": ""},
            {"conflict_joint_id": "J02"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(JointSpacingError) as context:
                    replace(skipped, **kwargs)
                self.assertEqual(
                    context.exception.code,
                    "JOINT_SPACING_INVALID_RECORD",
                )

    def test_extraction_rejects_duplicate_accepted_id(self) -> None:
        first, second = self.spacing.accepted[:2]
        duplicate = replace(
            second,
            reachability=first.reachability,
            boolean=first.boolean,
        )

        with self.assertRaises(JointSpacingError) as context:
            replace(self.spacing, accepted=(first, duplicate))
        self.assertEqual(context.exception.code, "JOINT_SPACING_DUPLICATE_ID")

    def test_extraction_rejects_unknown_reachability(self) -> None:
        unknown_reachability = replace(
            self.spacing.accepted[0].reachability,
            boolean_id="J99",
            candidate_id="J99",
        )
        unknown_boolean = replace(
            self.spacing.accepted[0].boolean,
            id="J99",
            candidate_id="J99",
        )
        record = replace(
            self.spacing.accepted[0],
            reachability=unknown_reachability,
            boolean=unknown_boolean,
        )

        with self.assertRaises(JointSpacingError) as context:
            replace(self.spacing, accepted=(record,))
        self.assertEqual(
            context.exception.code,
            "JOINT_SPACING_UNKNOWN_REACHABILITY",
        )

    def test_extraction_rejects_reachability_metadata_mismatch(self) -> None:
        mismatched_reachability = replace(
            self.spacing.accepted[0].reachability,
            contact_edge_id="E99",
        )
        mismatched_boolean = replace(
            self.spacing.accepted[0].boolean,
            contact_edge_id="E99",
        )
        record = replace(
            self.spacing.accepted[0],
            reachability=mismatched_reachability,
            boolean=mismatched_boolean,
        )

        with self.assertRaises(JointSpacingError) as context:
            replace(self.spacing, accepted=(record,))
        self.assertEqual(
            context.exception.code,
            "JOINT_SPACING_REACHABILITY_MISMATCH",
        )

    def test_extraction_rejects_skipped_metadata_mismatch(self) -> None:
        result = generate_joint_spacing(
            make_same_edge_reachability(positions=(2, 5))
        )
        skipped = replace(result.skipped[0], contact_edge_id="E99")

        with self.assertRaises(JointSpacingError) as context:
            replace(result, skipped=(skipped,))
        self.assertEqual(
            context.exception.code,
            "JOINT_SPACING_REACHABILITY_MISMATCH",
        )

    def test_extraction_rejects_duplicate_reachability(self) -> None:
        record = self.spacing.accepted[0]
        skipped = SkippedJointSpacing(
            boolean_id=record.boolean_id,
            candidate_id=record.candidate_id,
            contact_edge_id=record.contact_edge_id,
            plate_a=record.plate_a,
            plate_b=record.plate_b,
            contact_edge=record.contact_edge,
            position=record.position,
            width=record.width,
            slot_width=record.slot_width,
            contact_length=record.contact_length,
            edge_margin_cells=record.edge_margin_cells,
            required_gap_cells=4,
            actual_gap_cells=3,
            slot_gap_cells=0,
            reason=JointSpacingSkipReason.CONTINUOUS_SLOT,
            conflict_joint_id="J02",
        )

        with self.assertRaises(JointSpacingError) as context:
            replace(self.spacing, accepted=(record,), skipped=(skipped,))
        self.assertEqual(
            context.exception.code,
            "JOINT_SPACING_DUPLICATE_REACHABILITY",
        )

    def test_queries_and_unhandled_reachable(self) -> None:
        self.assertIs(self.spacing.spacing_by_id("J01"), self.spacing.accepted[0])
        self.assertEqual(
            [record.boolean_id for record in self.spacing.accepted_for_edge("E01")],
            ["J01"],
        )
        self.assertEqual(
            [record.boolean_id for record in self.spacing.accepted_for_plate("P01")],
            ["J01", "J02", "J03", "J04"],
        )
        partial = replace(self.spacing, accepted=(self.spacing.accepted[0],))
        self.assertEqual(
            [record.boolean_id for record in partial.unhandled_reachable],
            ["J02", "J03", "J04"],
        )
        with self.assertRaises(JointSpacingError) as context:
            self.spacing.accepted_for_plate("P99")
        self.assertEqual(context.exception.code, "JOINT_SPACING_UNKNOWN_PLATE")

    def test_source_skipped_are_preserved(self) -> None:
        reachability = generate_joint_reachability(
            self.reachability.booleans,
            JointReachabilityConfig(min_path_width_cells=4),
        )
        result = generate_joint_spacing(reachability)

        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(len(result.source_skipped), 4)
        self.assertEqual(result.unhandled_reachable, ())

    def test_empty_reachability_is_valid(self) -> None:
        empty_booleans = JointBooleanExtraction(candidates=self.reachability.booleans.candidates)
        empty_reachability = generate_joint_reachability(empty_booleans)
        result = generate_joint_spacing(empty_reachability)

        self.assertEqual(result.accepted, ())
        self.assertEqual(result.skipped, ())
        self.assertEqual(result.unhandled_reachable, ())


if __name__ == "__main__":
    unittest.main()
