import unittest

from app.domain.plate import Plate, PlateKind


class PlateTests(unittest.TestCase):
    def test_connected_plate(self) -> None:
        cells = frozenset({(0, 0), (1, 0), (0, 1), (1, 1)})
        plate = Plate(
            id="P01",
            kind=PlateKind.RING,
            cells=cells,
            color_by_cell={cell: "orange" for cell in cells},
        )
        self.assertTrue(plate.is_4_connected())
        self.assertEqual(plate.width(), 2)
        self.assertEqual(plate.height(), 2)
        self.assertEqual(plate.color_counts(), {"orange": 4})

    def test_disconnected_plate_is_detected(self) -> None:
        cells = frozenset({(0, 0), (2, 0)})
        plate = Plate(
            id="P01",
            kind=PlateKind.RING,
            cells=cells,
            color_by_cell={cell: "orange" for cell in cells},
        )
        self.assertFalse(plate.is_4_connected())

    def test_holes_must_not_overlap_cells(self) -> None:
        with self.assertRaises(ValueError):
            Plate(
                id="P01",
                kind=PlateKind.RING,
                cells=frozenset({(0, 0)}),
                color_by_cell={(0, 0): "orange"},
                holes=frozenset({(0, 0)}),
            )

    def test_color_keys_must_be_cells(self) -> None:
        with self.assertRaises(ValueError):
            Plate(
                id="P01",
                kind=PlateKind.RING,
                cells=frozenset({(0, 0)}),
                color_by_cell={(1, 0): "orange"},
            )


if __name__ == "__main__":
    unittest.main()
