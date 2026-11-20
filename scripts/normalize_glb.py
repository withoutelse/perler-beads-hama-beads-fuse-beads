from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.domain.bead import BeadSpec
from app.pipeline.normalization import (
    UpAxis,
    load_glb_mesh,
    normalize_mesh,
    solid_voxel_grid,
    surface_voxel_grid,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将 Tripo GLB 归一化为确定性体素网格")
    parser.add_argument("glb", type=Path, help="输入 GLB/GLTF 文件")
    parser.add_argument("--target-height-mm", type=float, default=80.0)
    parser.add_argument("--bead-size", choices=("5mm", "2.6mm"), default="5mm")
    parser.add_argument("--source-up-axis", choices=("y", "z"), default="y")
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
    surface = surface_voxel_grid(normalized)
    solid = solid_voxel_grid(normalized)
    payload = {
        "grid_shape": normalized.grid_shape,
        "grid_extent_mm": normalized.grid_extent_mm,
        "bounds_mm": normalized.mesh.bounds.tolist(),
        "transform": normalized.transform.tolist(),
        "surface_voxel_count": len(surface.occupied),
        "interior_voxel_count": len(solid.occupied - surface.occupied),
        "solid_voxel_count": len(solid.occupied),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
