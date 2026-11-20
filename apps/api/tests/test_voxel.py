import unittest

from app.domain.voxel import VoxelGrid


class VoxelGridTests(unittest.TestCase):
    def test_layer_and_center_of_mass(self) -> None:
        grid = VoxelGrid(
            width=2,
            height=1,
            depth=1,
            occupied=frozenset({(0, 0, 0), (1, 0, 0)}),
            color_by_voxel={(0, 0, 0): "orange", (1, 0, 0): "orange"},
        )
        self.assertEqual(grid.layer(0), frozenset({(0, 0), (1, 0)}))
        self.assertEqual(grid.center_of_mass(), (1.0, 0.5, 0.5))
        self.assertEqual(grid.color_counts(), {"orange": 2})

    def test_out_of_bounds_voxel_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            VoxelGrid(
                width=1,
                height=1,
                depth=1,
                occupied=frozenset({(1, 0, 0)}),
            )


if __name__ == "__main__":
    unittest.main()
