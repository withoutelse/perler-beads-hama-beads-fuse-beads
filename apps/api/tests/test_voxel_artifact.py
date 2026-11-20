import hashlib
import json
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path

import trimesh  # type: ignore[import-untyped]

from app.domain.bead import BeadSpec
from app.pipeline.normalization import (
    load_glb_mesh,
    normalize_mesh,
    solid_voxel_grid,
    surface_voxel_grid,
)
from app.pipeline.voxel_artifact import (
    VoxelArtifactError,
    VoxelizationOptions,
    build_voxel_artifact,
    load_voxel_artifact,
    save_voxel_artifact,
    voxel_artifact_id,
    voxel_cache_key,
)

ROOT = Path(__file__).resolve().parents[3]


def load_golden_payload() -> dict:
    return json.loads((ROOT / "fixtures" / "m2-voxel-artifact.json").read_text(encoding="utf-8"))


def artifact_digests(artifact) -> tuple[str, str]:
    occupied = sorted(artifact.occupied)
    occupied_text = "\n".join(f"{x},{y},{z}" for x, y, z in occupied)
    color_text = "\n".join(
        f"{x},{y},{z}:{artifact.color_by_voxel[(x, y, z)]}" for x, y, z in occupied
    )
    return (
        hashlib.sha256(occupied_text.encode()).hexdigest(),
        hashlib.sha256(color_text.encode()).hexdigest(),
    )


class VoxelArtifactTests(unittest.TestCase):
    def make_box_glb(self, directory: str, extents: tuple[float, float, float]) -> Path:
        path = Path(directory) / "box.glb"
        trimesh.creation.box(extents=extents).export(path)
        return path

    def test_golden_box_artifact_and_npz_round_trip(self) -> None:
        payload = load_golden_payload()
        expected = payload["expected"]
        with tempfile.TemporaryDirectory() as temp:
            model_path = self.make_box_glb(temp, tuple(payload["source_model"]["extents"]))
            options = VoxelizationOptions.from_mapping(payload["options"])
            cache_key = voxel_cache_key(
                model_artifact_id=payload["source_model"]["artifact_id"],
                model_relative_path=payload["source_model"]["relative_path"],
                pitch_mm=BeadSpec.standard_5mm().pitch_mm,
                options=options,
            )
            self.assertEqual(cache_key, expected["cache_key"])
            self.assertEqual(voxel_artifact_id(cache_key), expected["artifact_id"])

            artifact = build_voxel_artifact(
                model_path=model_path,
                model_artifact_id=payload["source_model"]["artifact_id"],
                model_relative_path=payload["source_model"]["relative_path"],
                bead_spec=BeadSpec.standard_5mm(),
                options=options,
            )
            self.assertEqual(artifact.grid_shape, tuple(expected["grid_shape"]))
            self.assertEqual(artifact.grid_extent_mm, tuple(expected["grid_extent_mm"]))
            self.assertEqual(artifact.pitch_mm, expected["pitch_mm"])
            self.assertEqual(artifact.surface_voxel_count, expected["surface_voxel_count"])
            self.assertEqual(artifact.interior_voxel_count, expected["interior_voxel_count"])
            self.assertEqual(len(artifact.occupied), expected["occupied_count"])
            self.assertEqual(dict(Counter(artifact.color_by_voxel.values())), expected["color_counts"])
            used_palette = {
                color_id: artifact.palette[color_id] for color_id in artifact.color_by_voxel.values()
            }
            self.assertEqual(used_palette, expected["used_palette"])
            self.assertEqual(
                sum(1 for _, _, z in artifact.occupied if z == 3),
                expected["slice_z3_occupied_count"],
            )
            self.assertEqual(
                dict(
                    Counter(
                        artifact.color_by_voxel[(x, y, z)]
                        for x, y, z in artifact.occupied
                        if z == 3
                    )
                ),
                expected["slice_z3_color_counts"],
            )
            occupied_digest, color_digest = artifact_digests(artifact)
            self.assertEqual(occupied_digest, expected["occupied_sha256"])
            self.assertEqual(color_digest, expected["color_sha256"])

            artifact_path = Path(temp) / "voxel.npz"
            save_voxel_artifact(artifact_path, artifact)
            loaded = load_voxel_artifact(artifact_path)
            self.assertEqual(loaded, artifact)
            self.assertTrue(artifact_path.read_bytes().startswith(b"PK"))

    def test_cache_key_is_sensitive_to_voxelization_options(self) -> None:
        base = VoxelizationOptions(target_height_mm=30.0)
        changed_height = VoxelizationOptions(target_height_mm=31.0)
        kwargs = {
            "model_artifact_id": "art_model_glb_golden",
            "model_relative_path": "projects/prj_golden/model/model.glb",
            "pitch_mm": 5.0,
        }
        self.assertNotEqual(
            voxel_cache_key(**kwargs, options=base),
            voxel_cache_key(**kwargs, options=changed_height),
        )

    def test_invalid_options_have_stable_error_codes(self) -> None:
        with self.assertRaises(VoxelArtifactError) as invalid_height:
            VoxelizationOptions.from_mapping({"target_height_mm": 0})
        self.assertEqual(invalid_height.exception.code, "VOXEL_INVALID_TARGET_HEIGHT")

        with self.assertRaises(VoxelArtifactError) as invalid_tolerance:
            VoxelizationOptions.from_mapping({"delta_e_tolerance": -1})
        self.assertEqual(invalid_tolerance.exception.code, "VOXEL_INVALID_TOLERANCE")

        with self.assertRaises(VoxelArtifactError) as invalid_axis:
            VoxelizationOptions.from_mapping({"source_up_axis": "x"})
        self.assertEqual(invalid_axis.exception.code, "VOXEL_INVALID_UP_AXIS")

        with self.assertRaises(VoxelArtifactError) as invalid_palette:
            VoxelizationOptions.from_mapping({"color_palette": "unknown"})
        self.assertEqual(invalid_palette.exception.code, "VOXEL_UNSUPPORTED_PALETTE")

    def test_missing_artifact_has_stable_error_code(self) -> None:
        with self.assertRaises(VoxelArtifactError) as missing:
            load_voxel_artifact(Path("does-not-exist.npz"))
        self.assertEqual(missing.exception.code, "VOXEL_ARTIFACT_MISSING")

    def test_128_cube_geometry_voxelization_stays_within_initial_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            model_path = self.make_box_glb(temp, (6.0, 6.0, 6.0))
            started = time.perf_counter()
            normalized = normalize_mesh(
                load_glb_mesh(model_path),
                bead_spec=BeadSpec.standard_5mm(),
                target_height_mm=640.0,
            )
            surface = surface_voxel_grid(normalized)
            solid = solid_voxel_grid(normalized, surface=surface)
            elapsed = time.perf_counter() - started

            self.assertEqual(normalized.grid_shape, (128, 128, 128))
            self.assertEqual(len(solid.occupied), 128**3)
            self.assertLess(elapsed, 30.0)


if __name__ == "__main__":
    unittest.main()
