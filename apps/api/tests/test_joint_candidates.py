import json
import unittest
from dataclasses import replace
from pathlib import Path

from app.domain.bands import LayerBandConfig
from app.domain.cross_skeletons import CrossSkeletonConfig
from app.domain.decomposition import DecompositionConfig, decompose_voxel_grid
from app.domain.joint import JointDirection, JointType
from app.domain.joint_candidates import (
    JointCandidate,
    JointCandidateConfig,
    JointCandidateError,
    JointCandidateExtraction,
    JointCandidateSkipReason,
    SkippedJointCandidate,
    generate_joint_candidates,
)
from app.domain.plate_adjacency import (
    PlateContactEdge,
    PlateContactGraph,
    PlateContactKind,
)
from app.domain.vertical_plates import VerticalPlateConfig
from app.domain.voxel import VoxelGrid

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "fixtures" / "m3-decomposition.json"
)


def parse_cell2(value: list[int]) -> tuple[int, int]:
    return int(value[0]), int(value[1])


def parse_cell3(value: list[int]) -> tuple[int, int, int]:
    return int(value[0]), int(value[1]), int(value[2])


class JointCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.golden = decompose_voxel_grid(cls.build_golden_grid(), cls.build_config())
        cls.golden_candidates = generate_joint_candidates(cls.golden.adjacency)

    @classmethod
    def build_golden_grid(cls) -> VoxelGrid:
        voxel_payload = cls.payload["voxel_grid"]
        return VoxelGrid(
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

    @classmethod
    def build_config(cls) -> DecompositionConfig:
        config = cls.payload["config"]
        return DecompositionConfig(
            band=LayerBandConfig(**config["band"]),
            vertical=VerticalPlateConfig(**config["vertical"]),
            cross_skeleton=CrossSkeletonConfig(**config["cross_skeleton"]),
        )

    @staticmethod
    def ring_grid(
        *,
        size: int = 7,
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

    def test_golden_sample_generates_candidates_and_skips(self) -> None:
        result = self.golden_candidates

        self.assertEqual(result.candidate_count, 16)
        self.assertEqual(result.skipped_count, 4)
        self.assertEqual(
            [candidate.id for candidate in result.candidates],
            [f"J{index:02d}" for index in range(1, 17)],
        )
        self.assertEqual(
            [skipped.contact_edge_id for skipped in result.skipped],
            ["E15", "E16", "E17", "E18"],
        )
        self.assertTrue(
            all(
                skipped.reason is JointCandidateSkipReason.CONTACT_TOO_SHORT
                for skipped in result.skipped
            )
        )
        self.assertEqual(result.unhandled_edges, ())

    def test_candidate_descriptors_are_centered_and_sized(self) -> None:
        pin = self.golden_candidates.candidate_by_id("J01")
        self.assertEqual(pin.contact_edge_id, "E01")
        self.assertEqual((pin.plate_a, pin.plate_b), ("P01", "P02"))
        self.assertIs(pin.contact_kind, PlateContactKind.FACE)
        self.assertIs(pin.direction, JointDirection.Z_POS)
        self.assertIs(pin.joint_type, JointType.PIN)
        self.assertEqual((pin.position, pin.width, pin.length), (0, 1, 1))
        self.assertEqual((pin.slot_width, pin.slot_length), (2, 2))
        self.assertEqual(pin.contact_length, 16)
        self.assertEqual(pin.edge_margin_cells, 1)

        load_bearing = self.golden_candidates.candidate_by_id("J02")
        self.assertEqual(load_bearing.contact_edge_id, "E02")
        self.assertEqual((load_bearing.plate_a, load_bearing.plate_b), ("P01", "P04"))
        self.assertIs(load_bearing.direction, JointDirection.Y_NEG)
        self.assertIs(load_bearing.joint_type, JointType.LOAD_BEARING)
        self.assertEqual(
            (load_bearing.position, load_bearing.width, load_bearing.length),
            (1, 2, 3),
        )
        self.assertEqual((load_bearing.slot_width, load_bearing.slot_length), (3, 4))
        self.assertEqual(load_bearing.contact_length, 5)

    def test_thick_ring_generates_load_bearing_candidates(self) -> None:
        decomposition = decompose_voxel_grid(self.ring_grid(size=11, hole_size=3))
        result = generate_joint_candidates(decomposition.adjacency)

        self.assertEqual(result.candidate_count, 4)
        self.assertEqual(result.skipped_count, 4)
        self.assertTrue(
            all(
                candidate.joint_type is JointType.LOAD_BEARING
                for candidate in result.candidates
            )
        )
        self.assertTrue(
            all(
                (candidate.position, candidate.width, candidate.length) == (4, 2, 3)
                for candidate in result.candidates
            )
        )
        self.assertTrue(
            all(candidate.contact_length == 11 for candidate in result.candidates)
        )
        self.assertTrue(
            all(
                skipped.reason is JointCandidateSkipReason.CONTACT_TOO_SHORT
                for skipped in result.skipped
            )
        )

    def test_config_validation(self) -> None:
        for kwargs in (
            {"edge_margin_cells": -1},
            {"slot_clearance_cells": 0},
            {"load_bearing_width_cells": 1},
            {"load_bearing_length_cells": 1},
            {"pin_width_cells": 2},
            {"pin_length_cells": 3},
            {"min_width_cells": 2, "load_bearing_width_cells": 1},
            {"max_width_cells": 1, "load_bearing_width_cells": 2},
            {"min_length_cells": 2, "pin_length_cells": 1},
            {"max_length_cells": 1, "load_bearing_length_cells": 2},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(JointCandidateError) as context:
                    JointCandidateConfig(**kwargs)  # type: ignore[arg-type]
                self.assertEqual(
                    context.exception.code,
                    "JOINT_CANDIDATE_INVALID_CONFIG",
                )

    def test_candidate_record_validation(self) -> None:
        load_bearing = self.golden_candidates.candidate_by_id("J02")
        pin = self.golden_candidates.candidate_by_id("J01")

        for candidate, kwargs in (
            (load_bearing, {"id": ""}),
            (load_bearing, {"contact_edge_id": ""}),
            (load_bearing, {"plate_a": "P04", "plate_b": "P01"}),
            (load_bearing, {"position": -1}),
            (load_bearing, {"width": 0}),
            (load_bearing, {"length": 0}),
            (load_bearing, {"slot_clearance_cells": 0}),
            (load_bearing, {"contact_length": 0}),
            (load_bearing, {"edge_margin_cells": -1}),
            (load_bearing, {"width": 1}),
            (load_bearing, {"length": 1}),
            (load_bearing, {"position": 2}),
            (pin, {"width": 2}),
            (pin, {"length": 3}),
            (pin, {"position": 1}),
            (pin, {"joint_type": JointType.LOAD_BEARING}),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(JointCandidateError) as context:
                    replace(candidate, **kwargs)
                self.assertEqual(
                    context.exception.code,
                    "JOINT_CANDIDATE_INVALID_RECORD",
                )

    def test_skipped_record_validation(self) -> None:
        valid = self.golden_candidates.skipped[0]
        self.assertIs(valid.reason, JointCandidateSkipReason.CONTACT_TOO_SHORT)

        for kwargs in (
            {"contact_edge_id": ""},
            {"plate_a": "P05", "plate_b": "P04"},
            {"contact_length": 0},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(JointCandidateError) as context:
                    replace(valid, **kwargs)
                self.assertEqual(
                    context.exception.code,
                    "JOINT_CANDIDATE_INVALID_RECORD",
                )

    def test_extraction_rejects_unknown_edge(self) -> None:
        bad = replace(self.golden_candidates.candidates[0], contact_edge_id="E99")

        with self.assertRaises(JointCandidateError) as context:
            replace(self.golden_candidates, candidates=(bad,))
        self.assertEqual(context.exception.code, "JOINT_CANDIDATE_UNKNOWN_EDGE")

    def test_extraction_rejects_duplicate_edge(self) -> None:
        first, second = self.golden_candidates.candidates[:2]
        duplicate_edge = replace(second, contact_edge_id=first.contact_edge_id)

        with self.assertRaises(JointCandidateError) as context:
            replace(
                self.golden_candidates,
                candidates=(first, duplicate_edge),
            )
        self.assertEqual(context.exception.code, "JOINT_CANDIDATE_DUPLICATE_EDGE")

    def test_extraction_rejects_duplicate_id(self) -> None:
        first, second = self.golden_candidates.candidates[:2]
        duplicate_id = replace(second, id=first.id)

        with self.assertRaises(JointCandidateError) as context:
            replace(
                self.golden_candidates,
                candidates=(first, duplicate_id),
            )
        self.assertEqual(context.exception.code, "JOINT_CANDIDATE_DUPLICATE_ID")

    def test_extraction_rejects_candidate_edge_mismatch(self) -> None:
        bad = replace(self.golden_candidates.candidates[1], plate_a="P02")

        with self.assertRaises(JointCandidateError) as context:
            replace(self.golden_candidates, candidates=(bad,))
        self.assertEqual(context.exception.code, "JOINT_CANDIDATE_EDGE_MISMATCH")

    def test_extraction_rejects_skipped_edge_mismatch(self) -> None:
        bad = replace(self.golden_candidates.skipped[0], plate_a="P01")

        with self.assertRaises(JointCandidateError) as context:
            replace(self.golden_candidates, skipped=(bad,))
        self.assertEqual(context.exception.code, "JOINT_CANDIDATE_EDGE_MISMATCH")

    def test_empty_graph_produces_empty_extraction(self) -> None:
        empty = decompose_voxel_grid(
            VoxelGrid(
                width=3,
                height=3,
                depth=1,
                occupied=frozenset(),
            )
        )
        result = generate_joint_candidates(empty.adjacency)

        self.assertEqual(result.candidates, ())
        self.assertEqual(result.skipped, ())
        self.assertEqual(result.unhandled_edges, ())
        with self.assertRaises(JointCandidateError) as context:
            result.candidates_for_plate("P01")
        self.assertEqual(context.exception.code, "JOINT_CANDIDATE_UNKNOWN_PLATE")

    def test_short_pin_contact_is_skipped(self) -> None:
        adjacency = self.golden.adjacency
        edges = list(adjacency.contact_edges)
        index = next(index for index, edge in enumerate(edges) if edge.id == "E15")
        edges[index] = replace(edges[index], joint_type_hint=JointType.PIN)
        graph = replace(adjacency.graph, edges=tuple(edges))
        pin_adjacency = replace(adjacency, graph=graph)

        result = generate_joint_candidates(pin_adjacency)

        self.assertEqual(result.candidates_for_edge("E15"), ())
        self.assertEqual(len(result.skipped_for_edge("E15")), 1)
        self.assertIs(
            result.skipped_for_edge("E15")[0].reason,
            JointCandidateSkipReason.CONTACT_TOO_SHORT,
        )

    def test_unhandled_edges_are_reported(self) -> None:
        partial = replace(
            self.golden_candidates,
            candidates=(self.golden_candidates.candidates[0],),
            skipped=(),
        )

        self.assertEqual(len(partial.unhandled_edges), 19)
        self.assertEqual(partial.unhandled_edges[0].id, "E02")

    def test_candidates_for_plate(self) -> None:
        self.assertEqual(
            [candidate.id for candidate in self.golden_candidates.candidates_for_plate("P01")],
            ["J01", "J02", "J03", "J04", "J05"],
        )
        self.assertEqual(
            [candidate.id for candidate in self.golden_candidates.candidates_for_plate("P09")],
            ["J15", "J16"],
        )
        with self.assertRaises(JointCandidateError) as context:
            self.golden_candidates.candidates_for_plate("P99")
        self.assertEqual(context.exception.code, "JOINT_CANDIDATE_UNKNOWN_PLATE")

    def test_manual_extraction_validation(self) -> None:
        edge = PlateContactEdge(
            id="E01",
            plate_a="P01",
            plate_b="P02",
            kind=PlateContactKind.FACE,
            direction=JointDirection.X_POS,
            position=0,
            contact_length=5,
            contact_edge="test",
        )
        graph = PlateContactGraph(
            nodes=self.golden.adjacency.graph.nodes,
            edges=(edge,),
        )
        adjacency = replace(self.golden.adjacency, graph=graph)
        candidate = JointCandidate(
            id="J01",
            contact_edge_id="E01",
            plate_a="P01",
            plate_b="P02",
            contact_kind=PlateContactKind.FACE,
            direction=JointDirection.X_POS,
            position=1,
            width=2,
            length=3,
            joint_type=JointType.LOAD_BEARING,
            slot_clearance_cells=1,
            contact_length=5,
            edge_margin_cells=1,
        )
        extraction = JointCandidateExtraction(
            adjacency=adjacency,
            candidates=(candidate,),
        )
        self.assertEqual(extraction.candidate_by_id("J01"), candidate)
        self.assertEqual(extraction.candidates_for_edge("E01"), (candidate,))
        self.assertEqual(extraction.unhandled_edges, ())

        skipped = SkippedJointCandidate(
            contact_edge_id="E01",
            plate_a="P01",
            plate_b="P02",
            contact_kind=PlateContactKind.FACE,
            direction=JointDirection.X_POS,
            contact_length=5,
            joint_type=JointType.LOAD_BEARING,
            reason=JointCandidateSkipReason.CONTACT_TOO_SHORT,
        )
        with self.assertRaises(JointCandidateError) as context:
            JointCandidateExtraction(
                adjacency=adjacency,
                candidates=(candidate,),
                skipped=(skipped,),
            )
        self.assertEqual(context.exception.code, "JOINT_CANDIDATE_DUPLICATE_EDGE")


if __name__ == "__main__":
    unittest.main()
