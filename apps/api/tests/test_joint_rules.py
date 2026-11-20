import unittest

from app.domain.joint import Joint, JointDirection, JointType


def make_joint(
    tongue: set[tuple[int, int, int]],
    slot: set[tuple[int, int, int]],
) -> Joint:
    return Joint(
        id="J01",
        plate_a="P01",
        plate_b="P02",
        edge_a="top",
        edge_b="bottom",
        direction=JointDirection.Z_NEG,
        position=2,
        width=2,
        length=1,
        joint_type=JointType.LOAD_BEARING,
        tongue_cells=frozenset(tongue),
        slot_cells=frozenset(slot),
    )


class JointRuleTests(unittest.TestCase):
    def test_complementary_joint_has_clearance(self) -> None:
        joint = make_joint(
            tongue={(0, 0, 0), (1, 0, 0)},
            slot={(0, 0, 0), (1, 0, 0), (2, 0, 0)},
        )
        self.assertEqual(joint.clearance_cells, frozenset({(2, 0, 0)}))

    def test_tongue_must_fit_inside_slot(self) -> None:
        with self.assertRaises(ValueError):
            make_joint(tongue={(0, 0, 0)}, slot={(1, 0, 0), (2, 0, 0)})

    def test_slot_requires_clearance(self) -> None:
        with self.assertRaises(ValueError):
            make_joint(tongue={(0, 0, 0)}, slot={(0, 0, 0)})

if __name__ == "__main__":
    unittest.main()
