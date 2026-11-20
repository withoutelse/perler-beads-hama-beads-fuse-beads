from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.domain.bead import BeadSpec
from app.domain.color import default_perler_standard_palette
from app.pipeline.normalization import (
    UpAxis,
    load_glb_mesh,
    normalize_mesh,
    solid_voxel_grid,
)
from app.pipeline.texture import colorize_voxel_grid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将 Tripo GLB 实心体素化并匹配 Perler 色卡")
    parser.add_argument("glb", type=Path, help="输入 GLB/GLTF 文件")
    parser.add_argument("--target-height-mm", type=float, default=80.0)
    parser.add_argument("--bead-size", choices=("5mm", "2.6mm"), default="5mm")
    parser.add_argument("--source-up-axis", choices=("y", "z"), default="y")
    parser.add_argument("--delta-e-tolerance", type=float, default=6.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bead_spec = BeadSpec.standard_5mm() if args.bead_size == "5mm" else BeadSpec.mini_2_6mm()
    normalized = normalize_mesh(
        load_glb_mesh(args.glb),
        bead_spec=bead_spec,
        target_height_mm=args.target_height_mm,
        source_up_axis=UpAxis(args.source_up_axis),
    )
    solid = solid_voxel_grid(normalized)
    palette = default_perler_standard_palette()
    colored = colorize_voxel_grid(
        normalized,
        solid,
        palette,
        delta_e_tolerance=args.delta_e_tolerance,
    )
    used_colors = set(colored.color_by_voxel.values())
    payload = {
        "grid_shape": normalized.grid_shape,
        "solid_voxel_count": len(colored.occupied),
        "color_counts": colored.color_counts(),
        "palette": {
            color.id: color.hex for color in palette if color.id in used_colors
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
