import unittest

from app.domain.color import (
    DEFAULT_PERLER_STANDARD,
    ciede2000,
    default_perler_standard_palette,
    merge_palette_colors,
    nearest_palette_color,
    palette_from_mapping,
    parse_hex_color,
    srgb_to_lab,
)


class ColorTests(unittest.TestCase):
    def test_ciede2000_reference_pair(self) -> None:
        self.assertAlmostEqual(
            ciede2000((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485)),
            2.0425,
            places=4,
        )

    def test_srgb_to_lab_endpoints(self) -> None:
        white = srgb_to_lab((255, 255, 255))
        black = srgb_to_lab((0, 0, 0))
        self.assertAlmostEqual(white[0], 100.0, places=3)
        self.assertAlmostEqual(white[1], 0.0, places=3)
        self.assertAlmostEqual(white[2], 0.0, places=3)
        self.assertEqual(black, (0.0, 0.0, 0.0))

    def test_hex_parsing(self) -> None:
        self.assertEqual(parse_hex_color("#e86f2d"), (232, 111, 45))
        self.assertEqual(parse_hex_color("#fff"), (255, 255, 255))
        with self.assertRaises(ValueError):
            parse_hex_color("#xyzxyz")
        with self.assertRaises(TypeError):
            parse_hex_color(123)  # type: ignore[arg-type]

    def test_palette_matching_and_merging(self) -> None:
        palette = palette_from_mapping(
            {
                "blue": "#0000ff",
                "red": "#ff0000",
                "red_near": "#fe0000",
            }
        )
        match = nearest_palette_color((255, 0, 0), palette)
        self.assertEqual(match.color.id, "red")
        self.assertLess(match.delta_e, 6.0)

        merged = merge_palette_colors(palette, tolerance=6.0)
        self.assertEqual(tuple(color.id for color in merged), ("blue", "red"))

    def test_default_palette_is_stable(self) -> None:
        palette = default_perler_standard_palette()
        self.assertEqual(len(palette), len(DEFAULT_PERLER_STANDARD))
        self.assertIn("orange", {color.id for color in palette})


if __name__ == "__main__":
    unittest.main()
