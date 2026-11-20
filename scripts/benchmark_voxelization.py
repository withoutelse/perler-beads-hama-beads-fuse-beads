from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import trimesh  # type: ignore[import-untyped]
from app.domain.bead import BeadSpec
from app.pipeline.normalization import (
    load_glb_mesh,
    normalize_mesh,
    solid_voxel_grid,
    surface_voxel_grid,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基准测试 GLB 表面/实心体素化性能")
    parser.add_argument("--grid-size", type=int, default=256, help="立方体每轴格数")
    parser.add_argument("--max-seconds", type=float, default=30.0, help="总耗时预算")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.grid_size <= 0:
        raise SystemExit("--grid-size 必须为正数")
    if args.max_seconds <= 0:
        raise SystemExit("--max-seconds 必须为正数")

    with tempfile.TemporaryDirectory() as temp:
        model_path = Path(temp) / "benchmark-box.glb"
        trimesh.creation.box(extents=(6.0, 6.0, 6.0)).export(model_path)

        started = time.perf_counter()
        normalized = normalize_mesh(
            load_glb_mesh(model_path),
            bead_spec=BeadSpec.standard_5mm(),
            target_height_mm=args.grid_size * 5.0,
        )
        normalized_at = time.perf_counter()
        surface = surface_voxel_grid(normalized)
        surface_at = time.perf_counter()
        solid = solid_voxel_grid(normalized, surface=surface)
        finished = time.perf_counter()

    payload = {
        "grid_shape": normalized.grid_shape,
        "surface_voxel_count": len(surface.occupied),
        "solid_voxel_count": len(solid.occupied),
        "normalize_seconds": round(normalized_at - started, 3),
        "surface_seconds": round(surface_at - normalized_at, 3),
        "solid_seconds": round(finished - surface_at, 3),
        "total_seconds": round(finished - started, 3),
        "budget_seconds": args.max_seconds,
        "within_budget": finished - started <= args.max_seconds,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["within_budget"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
