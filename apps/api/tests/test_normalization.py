import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh  # type: ignore[import-untyped]

from app.domain.bead import BeadSpec
from app.pipeline.normalization import (
    NormalizationError,
    UpAxis,
    load_glb_mesh,
    normalize_mesh,
    solid_voxel_grid,
    surface_voxel_grid,
)

ROOT = Path(__file__).resolve().parents[3]


def load_golden_payload() -> dict:
    return json.loads((ROOT / "fixtures" / "m2-normalization.json").read_text(encoding="utf-8"))


class NormalizationTests(unittest.TestCase):
    def make_box_glb(self, directory: str, extents: tuple[float, float, float]) -> Path:
        path = Path(directory) / "box.glb"
        trimesh.creation.box(extents=extents).export(path)
        return path

    def test_golden_y_up_glb_normalization(self) -> None:
        payload = load_golden_payload()
        expected = payload["expected"]
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_box_glb(temp, tuple(payload["source_mesh"]["extents"]))
            mesh = load_glb_mesh(path)
            normalized = normalize_mesh(
                mesh,
                bead_spec=BeadSpec.standard_5mm(),
                target_height_mm=payload["target_height_mm"],
                source_up_axis=payload["source_mesh"]["source_up_axis"],
            )

            self.assertEqual(normalized.grid_shape, tuple(expected["grid_shape"]))
            np.testing.assert_allclose(normalized.grid_extent_mm, expected["grid_extent_mm"])
            np.testing.assert_allclose(normalized.mesh.bounds, expected["bounds_mm"], atol=1e-9)
            np.testing.assert_allclose(normalized.transform, expected["transform"], atol=1e-9)

            grid = surface_voxel_grid(normalized)
            self.assertEqual(len(grid.occupied), expected["surface_voxel_count"])
            self.assertEqual(grid.bounds(), ((0, 0, 0), (2, 8, 5)))
            np.testing.assert_allclose(grid.center_of_mass(), (1.5, 4.5, 3.0), atol=1e-9)
            self.assertEqual(grid.color_counts(), {})

            solid = solid_voxel_grid(normalized)
            self.assertEqual(len(solid.occupied), expected["solid_voxel_count"])
            self.assertEqual(
                len(solid.occupied - grid.occupied),
                expected["interior_voxel_count"],
            )
            self.assertEqual(solid.bounds(), ((0, 0, 0), (2, 8, 5)))
            np.testing.assert_allclose(solid.center_of_mass(), (1.5, 4.5, 3.0), atol=1e-9)
            self.assertTrue(solid.is_solid(1, 4, 3))
            self.assertFalse(grid.is_solid(1, 4, 3))
            self.assertEqual(solid.color_counts(), {})

    def test_transform_is_invertible_and_round_trips_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_box_glb(temp, (2.0, 4.0, 6.0))
            source = load_glb_mesh(path)
            normalized = normalize_mesh(
                source,
                bead_spec=BeadSpec.standard_5mm(),
                target_height_mm=30.0,
                source_up_axis=UpAxis.Y,
            )

            inverse = np.linalg.inv(normalized.transform)
            normalized_bounds = np.asarray(normalized.mesh.bounds, dtype=np.float64)
            corners = np.array(
                [
                    [x, y, z, 1.0]
                    for x in (normalized_bounds[0, 0], normalized_bounds[1, 0])
                    for y in (normalized_bounds[0, 1], normalized_bounds[1, 1])
                    for z in (normalized_bounds[0, 2], normalized_bounds[1, 2])
                ],
                dtype=np.float64,
            )
            restored = (inverse @ corners.T).T[:, :3]
            np.testing.assert_allclose(restored.min(axis=0), source.bounds[0], atol=1e-9)
            np.testing.assert_allclose(restored.max(axis=0), source.bounds[1], atol=1e-9)
            self.assertEqual(normalized.voxel_center(0, 0, 0), (2.5, 2.5, 2.5))

    def test_z_up_source_keeps_axis_orientation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_box_glb(temp, (2.0, 4.0, 6.0))
            source = load_glb_mesh(path)
            normalized = normalize_mesh(
                source,
                bead_spec=BeadSpec.standard_5mm(),
                target_height_mm=30.0,
                source_up_axis=UpAxis.Z,
            )

            self.assertEqual(normalized.grid_shape, (2, 4, 6))
            np.testing.assert_allclose(normalized.transform[:3, :3], np.diag([5.0, 5.0, 5.0]))
            self.assertEqual(len(surface_voxel_grid(normalized).occupied), 48)

    def test_scene_glb_is_concatenated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            left = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
            left.apply_translation((-2.0, 0.0, 0.0))
            right = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
            right.apply_translation((2.0, 0.0, 0.0))
            path = Path(temp) / "scene.glb"
            trimesh.Scene([left, right]).export(path)

            mesh = load_glb_mesh(path)
            self.assertEqual(len(mesh.faces), 24)
            normalized = normalize_mesh(
                mesh,
                bead_spec=BeadSpec.standard_5mm(),
                target_height_mm=10.0,
                source_up_axis=UpAxis.Z,
            )
            self.assertTrue(surface_voxel_grid(normalized).occupied)

    def test_surface_voxelization_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_box_glb(temp, (2.0, 4.0, 6.0))
            normalized = normalize_mesh(
                load_glb_mesh(path),
                bead_spec=BeadSpec.standard_5mm(),
                target_height_mm=30.0,
                source_up_axis=UpAxis.Y,
            )
            first = surface_voxel_grid(normalized)
            second = surface_voxel_grid(normalized)
            self.assertEqual(first.occupied, second.occupied)

    def test_solid_voxelization_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_box_glb(temp, (2.0, 4.0, 6.0))
            normalized = normalize_mesh(
                load_glb_mesh(path),
                bead_spec=BeadSpec.standard_5mm(),
                target_height_mm=30.0,
                source_up_axis=UpAxis.Y,
            )
            first = solid_voxel_grid(normalized)
            second = solid_voxel_grid(normalized)
            self.assertEqual(first.occupied, second.occupied)

    def test_split_vertex_closed_mesh_is_solidified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_box_glb(temp, (2.0, 4.0, 6.0))
            mesh = load_glb_mesh(path)
            mesh.unmerge_vertices()
            self.assertFalse(mesh.is_watertight)
            normalized = normalize_mesh(
                mesh,
                bead_spec=BeadSpec.standard_5mm(),
                target_height_mm=30.0,
                source_up_axis=UpAxis.Y,
            )

            solid = solid_voxel_grid(normalized)
            self.assertEqual(len(solid.occupied), 162)

    def test_open_mesh_cannot_be_solidified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_box_glb(temp, (2.0, 4.0, 6.0))
            mesh = load_glb_mesh(path)
            mesh.faces = mesh.faces[:-1]
            normalized = normalize_mesh(
                mesh,
                bead_spec=BeadSpec.standard_5mm(),
                target_height_mm=30.0,
                source_up_axis=UpAxis.Y,
            )

            with self.assertRaises(NormalizationError) as not_watertight:
                solid_voxel_grid(normalized)
            self.assertEqual(not_watertight.exception.code, "NORMALIZATION_NOT_WATERTIGHT")

    def test_invalid_inputs_have_stable_error_codes(self) -> None:
        mesh = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
        with self.assertRaises(NormalizationError) as invalid_height:
            normalize_mesh(mesh, bead_spec=BeadSpec.standard_5mm(), target_height_mm=0)
        self.assertEqual(invalid_height.exception.code, "NORMALIZATION_INVALID_TARGET_HEIGHT")

        with self.assertRaises(NormalizationError) as invalid_axis:
            normalize_mesh(
                mesh,
                bead_spec=BeadSpec.standard_5mm(),
                target_height_mm=10.0,
                source_up_axis="x",
            )
        self.assertEqual(invalid_axis.exception.code, "NORMALIZATION_UP_AXIS_UNSUPPORTED")

        with self.assertRaises(NormalizationError) as missing:
            load_glb_mesh(Path("does-not-exist.glb"))
        self.assertEqual(missing.exception.code, "NORMALIZATION_GLB_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
