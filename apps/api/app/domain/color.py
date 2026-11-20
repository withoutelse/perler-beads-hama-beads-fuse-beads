from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import atan2, cos, degrees, exp, radians, sin, sqrt
from types import MappingProxyType

Rgb = tuple[int, int, int]
Lab = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class PaletteColor:
    id: str
    hex: str
    rgb: Rgb
    lab: Lab


@dataclass(frozen=True, slots=True)
class PaletteMatch:
    color: PaletteColor
    delta_e: float


DEFAULT_PERLER_STANDARD: Mapping[str, str] = MappingProxyType(
    {
        "black": "#1a1a1a",
        "blue": "#2f80ed",
        "brown": "#7a4a2a",
        "charcoal": "#3b3b3b",
        "clear": "#f2f2f2",
        "coral": "#f47c5c",
        "cream": "#f5e6c8",
        "dark_brown": "#4b2e1f",
        "dark_green": "#1f6b45",
        "gold": "#d4a017",
        "gray": "#8c8c8c",
        "green": "#3a9d5d",
        "lavender": "#b9a7e6",
        "light_blue": "#9bc7f0",
        "light_gray": "#c7c7c7",
        "lime": "#a4d65e",
        "magenta": "#c0398f",
        "mint": "#8fd6b4",
        "navy": "#1f3a5f",
        "olive": "#7a8f3a",
        "orange": "#e86f2d",
        "peach": "#f4b183",
        "pink": "#f28cb1",
        "plum": "#6b2d5c",
        "purple": "#7b4bb7",
        "red": "#d62828",
        "silver": "#b8b8b8",
        "sky": "#7cc7e8",
        "tan": "#c9a27e",
        "turquoise": "#2aa7a0",
        "white": "#f5f5f5",
        "yellow": "#f2c94c",
    }
)


def parse_hex_color(value: str) -> Rgb:
    if not isinstance(value, str):
        raise TypeError("hex color must be a string")
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    if len(text) != 6:
        raise ValueError(f"invalid hex color: {value!r}")
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError as exc:
        raise ValueError(f"invalid hex color: {value!r}") from exc


def srgb_to_lab(rgb: Sequence[int]) -> Lab:
    if len(rgb) != 3:
        raise ValueError("rgb must contain exactly three channels")
    channels = [min(255.0, max(0.0, float(channel))) / 255.0 for channel in rgb]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    red, green, blue = linear
    x = 0.4124564 * red + 0.3575761 * green + 0.1804375 * blue
    y = 0.2126729 * red + 0.7151522 * green + 0.0721750 * blue
    z = 0.0193339 * red + 0.1191920 * green + 0.9503041 * blue
    fx = _lab_f(x / 0.95047)
    fy = _lab_f(y / 1.0)
    fz = _lab_f(z / 1.08883)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def ciede2000(lab1: Sequence[float], lab2: Sequence[float]) -> float:
    if len(lab1) != 3 or len(lab2) != 3:
        raise ValueError("lab colors must contain exactly three channels")
    l1, a1, b1 = (float(value) for value in lab1)
    l2, a2, b2 = (float(value) for value in lab2)

    c1 = sqrt(a1 * a1 + b1 * b1)
    c2 = sqrt(a2 * a2 + b2 * b2)
    c_bar = (c1 + c2) / 2.0
    c_bar_7 = c_bar**7
    g = 0.5 * (1.0 - sqrt(c_bar_7 / (c_bar_7 + 25.0**7)))
    a1_prime = (1.0 + g) * a1
    a2_prime = (1.0 + g) * a2
    c1_prime = sqrt(a1_prime * a1_prime + b1 * b1)
    c2_prime = sqrt(a2_prime * a2_prime + b2 * b2)
    h1_prime = _hue_degrees(b1, a1_prime, c1_prime)
    h2_prime = _hue_degrees(b2, a2_prime, c2_prime)

    delta_l_prime = l2 - l1
    delta_c_prime = c2_prime - c1_prime
    delta_h_prime = h2_prime - h1_prime
    if c1_prime * c2_prime == 0:
        delta_h_prime = 0.0
    elif delta_h_prime > 180.0:
        delta_h_prime -= 360.0
    elif delta_h_prime < -180.0:
        delta_h_prime += 360.0

    delta_h_capital = 2.0 * sqrt(c1_prime * c2_prime) * sin(radians(delta_h_prime / 2.0))
    l_bar_prime = (l1 + l2) / 2.0
    c_bar_prime = (c1_prime + c2_prime) / 2.0
    h_bar_prime = _mean_hue(h1_prime, h2_prime, c1_prime, c2_prime)

    t = (
        1.0
        - 0.17 * cos(radians(h_bar_prime - 30.0))
        + 0.24 * cos(radians(2.0 * h_bar_prime))
        + 0.32 * cos(radians(3.0 * h_bar_prime + 6.0))
        - 0.20 * cos(radians(4.0 * h_bar_prime - 63.0))
    )
    delta_theta = 30.0 * exp(-(((h_bar_prime - 275.0) / 25.0) ** 2))
    c_bar_prime_7 = c_bar_prime**7
    r_c = 2.0 * sqrt(c_bar_prime_7 / (c_bar_prime_7 + 25.0**7))
    s_l = 1.0 + (0.015 * (l_bar_prime - 50.0) ** 2) / sqrt(
        20.0 + (l_bar_prime - 50.0) ** 2
    )
    s_c = 1.0 + 0.045 * c_bar_prime
    s_h = 1.0 + 0.015 * c_bar_prime * t
    r_t = -sin(radians(2.0 * delta_theta)) * r_c

    lightness = delta_l_prime / s_l
    chroma = delta_c_prime / s_c
    hue = delta_h_capital / s_h
    return sqrt(lightness * lightness + chroma * chroma + hue * hue + r_t * chroma * hue)


def palette_from_mapping(palette: Mapping[str, str]) -> tuple[PaletteColor, ...]:
    if not palette:
        raise ValueError("palette must not be empty")
    colors: list[PaletteColor] = []
    for color_id, hex_value in sorted(palette.items()):
        if not color_id.strip():
            raise ValueError("palette color id must not be blank")
        rgb = parse_hex_color(hex_value)
        colors.append(
            PaletteColor(
                id=color_id,
                hex=hex_value,
                rgb=rgb,
                lab=srgb_to_lab(rgb),
            )
        )
    return tuple(colors)


def merge_palette_colors(
    palette: Sequence[PaletteColor],
    tolerance: float,
) -> tuple[PaletteColor, ...]:
    if tolerance < 0:
        raise ValueError("delta_e tolerance must not be negative")
    if not palette:
        raise ValueError("palette must not be empty")

    representatives: list[PaletteColor] = []
    for color in sorted(palette, key=lambda item: item.id):
        if any(ciede2000(color.lab, representative.lab) <= tolerance for representative in representatives):
            continue
        representatives.append(color)
    return tuple(representatives)


def nearest_palette_color(rgb: Sequence[int], palette: Sequence[PaletteColor]) -> PaletteMatch:
    if not palette:
        raise ValueError("palette must not be empty")
    lab = srgb_to_lab(rgb)
    best_color = min(palette, key=lambda color: (ciede2000(lab, color.lab), color.id))
    return PaletteMatch(color=best_color, delta_e=ciede2000(lab, best_color.lab))


def default_perler_standard_palette() -> tuple[PaletteColor, ...]:
    return palette_from_mapping(DEFAULT_PERLER_STANDARD)


def _lab_f(value: float) -> float:
    if value > 0.008856:
        return value ** (1.0 / 3.0)
    return 7.787 * value + 16.0 / 116.0


def _hue_degrees(b: float, a: float, chroma: float) -> float:
    if chroma == 0:
        return 0.0
    return degrees(atan2(b, a)) % 360.0


def _mean_hue(h1: float, h2: float, c1: float, c2: float) -> float:
    if c1 * c2 == 0:
        return h1 + h2
    if abs(h1 - h2) <= 180.0:
        return (h1 + h2) / 2.0
    if h1 + h2 < 360.0:
        return (h1 + h2 + 360.0) / 2.0
    return (h1 + h2 - 360.0) / 2.0
