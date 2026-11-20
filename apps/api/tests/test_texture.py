import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh  # type: ignore[import-untyped]
from PIL import Image
from trimesh.visual.texture import TextureVisuals  # type: ignore[import-untyped]

from app.domain.bead import BeadSpec
from app.domain.voxel import VoxelGrid
from app.pipeline.normalization import (
    NormalizedMesh,
    UpAxis,
    load_glb_mesh,
    normalize_mesh,
    solid_voxel_grid,
    surface_voxel_grid,
)
from app.pipeline.texture import TextureSamplingError, colorize_voxel_grid


def make_textured_plane() -> NormalizedMesh:
    vertices = np.array(
        [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [2.0, 2.0, 0.0], [0.0, 2.0, 0.0]],
        dtype=np.float64,
    )
    faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    uv = np.array(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        dtype=np.float64,
    )
    image = Image.new("RGB", (2, 2))
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((1, 0), (0, 255, 0))
    image.putpixel((0, 1), (0, 0, 255))
    image.putpixel((1, 1), (255, 255, 0))
    mesh = trimesh.Trimesh(
        vertices=vertices,
        faces=faces,
        visual=TextureVisuals(uv=uv, image=image),
        process=False,
    )
    return NormalizedMesh(
        mesh=mesh,
        transform=np.eye(4, dtype=np.float64),
        width=2,
        height=2,
        depth=1,
        pitch_mm=1.0,
        source_up_axis=UpAxis.Z,
        target_height_mm=None,
    )


class TextureTests(unittest.TestCase):
    def test_textured_plane_is_colored_deterministically(self) -> None:
        normalized = make_textured_plane()
        surface = surface_voxel_grid(normalized)
        grid = VoxelGrid(
            width=surface.width,
            height=surface.height,
            depth=surface.depth,
            occupied=surface.occupied,
        )
        palette = {
            "blue": "#0000ff",
            "green": "#00ff00",
            "red": "#ff0000",
            "yellow": "#ffff00",
        }

        first = colorize_voxel_grid(normalized, grid, palette, delta_e_tolerance=0)
        second = colorize_voxel_grid(normalized, grid, palette, delta_e_tolerance=0)
        self.assertEqual(first.color_by_voxel, second.color_by_voxel)
        self.assertEqual(first.occupied, grid.occupied)
        self.assertEqual(first.color_counts(), {"blue": 1, "green": 1, "red": 1, "yellow": 1})
        self.assertTrue(set(first.color_by_voxel.values()) <= set(palette))

    def test_solid_box_propagates_surface_color_to_interior(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "box.glb"
            trimesh.creation.box(extents=(2.0, 4.0, 6.0)).export(path)
            normalized = normalize_mesh(
                load_glb_mesh(path),
                bead_spec=BeadSpec.standard_5mm(),
                target_height_mm=30.0,
                source_up_axis=UpAxis.Y,
            )
            solid = solid_voxel_grid(normalized)
            colored = colorize_voxel_grid(normalized, solid, {"gray": "#666666"})

            self.assertEqual(len(colored.occupied), 162)
            self.assertEqual(colored.color_counts(), {"gray": 162})

    def test_missing_uv_has_stable_error_code(self) -> None:
        normalized = make_textured_plane()
        normalized.mesh.visual = TextureVisuals(uv=None, image=Image.new("RGB", (1, 1)))
        grid = surface_voxel_grid(normalized)

        with self.assertRaises(TextureSamplingError) as missing_uv:
            colorize_voxel_grid(normalized, grid, {"gray": "#666666"})
        self.assertEqual(missing_uv.exception.code, "TEXTURE_UV_MISSING")

    def test_invalid_uv_has_stable_error_code(self) -> None:
        normalized = make_textured_plane()
        normalized.mesh.visual = TextureVisuals(
            uv=np.array([[0.0, 0.0]], dtype=np.float64),
            image=Image.new("RGB", (1, 1), (128, 128, 128)),
        )
        grid = surface_voxel_grid(normalized)

        with self.assertRaises(TextureSamplingError) as invalid_uv:
            colorize_voxel_grid(normalized, grid, {"gray": "#666666"})
        self.assertEqual(invalid_uv.exception.code, "TEXTURE_UV_INVALID")

    def test_missing_image_has_stable_error_code(self) -> None:
        normalized = make_textured_plane()
        normalized.mesh.visual = TextureVisuals(
            uv=np.array(
                [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                dtype=np.float64,
            ),
            image=None,
        )
        normalized.mesh.visual.material.image = None
        grid = surface_voxel_grid(normalized)

        with self.assertRaises(TextureSamplingError) as missing_image:
            colorize_voxel_grid(normalized, grid, {"gray": "#666666"})
        self.assertEqual(missing_image.exception.code, "TEXTURE_IMAGE_MISSING")


if __name__ == "__main__":
    unittest.main()
