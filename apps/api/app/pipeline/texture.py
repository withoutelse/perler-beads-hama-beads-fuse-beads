from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import trimesh  # type: ignore[import-untyped]
from numpy.typing import NDArray
from scipy.spatial import cKDTree  # type: ignore[import-untyped]

from app.domain.color import (
    PaletteColor,
    merge_palette_colors,
    nearest_palette_color,
    palette_from_mapping,
)
from app.domain.voxel import Coord3, VoxelGrid
from app.pipeline.normalization import NormalizedMesh, surface_voxel_grid

Rgb = tuple[int, int, int]
ColorArray = NDArray[np.float64]
PointArray = NDArray[np.float64]
ColorSampler = Callable[[int, tuple[float, float, float]], Rgb]

_AREA_EPSILON = 1e-12
_DISTANCE_EPSILON = 1e-12
_TRIANGLE_CANDIDATES = 32
_SURFACE_CHUNK = 4096
_COLOR_CHUNK = 65536


class TextureSamplingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def colorize_voxel_grid(
    normalized: NormalizedMesh,
    grid: VoxelGrid,
    palette: Mapping[str, str] | Sequence[PaletteColor],
    *,
    delta_e_tolerance: float = 6.0,
    surface: VoxelGrid | None = None,
) -> VoxelGrid:
    """Sample mesh visual colors at voxel centers and match them to a palette."""
    if (grid.width, grid.height, grid.depth) != normalized.grid_shape:
        raise TextureSamplingError(
            "TEXTURE_GRID_MISMATCH",
            "体素网格尺寸与归一化网格不一致",
        )
    if delta_e_tolerance < 0:
        raise TextureSamplingError("TEXTURE_INVALID_TOLERANCE", "delta_e_tolerance 不能为负数")

    palette_colors = _coerce_palette(palette)
    canonical_palette = merge_palette_colors(palette_colors, delta_e_tolerance)
    if not grid.occupied:
        return VoxelGrid(
            width=grid.width,
            height=grid.height,
            depth=grid.depth,
            occupied=grid.occupied,
            color_by_voxel={},
        )

    surface_grid = surface or surface_voxel_grid(normalized)
    if (surface_grid.width, surface_grid.height, surface_grid.depth) != normalized.grid_shape:
        raise TextureSamplingError(
            "TEXTURE_GRID_MISMATCH",
            "表面体素网格尺寸与归一化网格不一致",
        )
    surface_voxels = sorted(surface_grid.occupied)
    if not surface_voxels:
        raise TextureSamplingError("TEXTURE_NO_SURFACE", "模型没有可采样的表面体素")

    triangles = np.asarray(normalized.mesh.triangles, dtype=np.float64)
    faces = np.asarray(normalized.mesh.faces, dtype=np.int64)
    valid_faces = _non_degenerate_faces(triangles)
    if valid_faces.size == 0:
        raise TextureSamplingError("TEXTURE_DEGENERATE_MESH", "模型没有可采样的有效三角面")
    sampler = _surface_color_sampler(normalized.mesh, faces)

    triangle_tree = cKDTree(triangles[valid_faces].mean(axis=1))
    surface_rgb = _sample_surface_colors(
        normalized,
        surface_voxels,
        triangles,
        valid_faces,
        sampler,
        triangle_tree,
    )

    surface_centers = (
        np.asarray(surface_voxels, dtype=np.float64) + 0.5
    ) * normalized.pitch_mm
    surface_tree = cKDTree(surface_centers)
    match_cache: dict[Rgb, str] = {}
    color_by_voxel: dict[Coord3, str] = {}

    def match_color(rgb: Rgb) -> str:
        color_id = match_cache.get(rgb)
        if color_id is None:
            color_id = nearest_palette_color(rgb, canonical_palette).color.id
            match_cache[rgb] = color_id
        return color_id

    for voxel in surface_voxels:
        color_by_voxel[voxel] = match_color(surface_rgb[voxel])

    interior_voxels = sorted(grid.occupied - surface_grid.occupied)
    for start in range(0, len(interior_voxels), _COLOR_CHUNK):
        chunk = interior_voxels[start : start + _COLOR_CHUNK]
        centers = (np.asarray(chunk, dtype=np.float64) + 0.5) * normalized.pitch_mm
        _, nearest_indices = surface_tree.query(centers, k=1)
        for voxel, nearest_index in zip(
            chunk,
            np.asarray(nearest_indices, dtype=np.int64).tolist(),
            strict=True,
        ):
            color_by_voxel[voxel] = match_color(surface_rgb[surface_voxels[int(nearest_index)]])

    return VoxelGrid(
        width=grid.width,
        height=grid.height,
        depth=grid.depth,
        occupied=grid.occupied,
        color_by_voxel=color_by_voxel,
    )


def _coerce_palette(
    palette: Mapping[str, str] | Sequence[PaletteColor],
) -> tuple[PaletteColor, ...]:
    if isinstance(palette, Mapping):
        return palette_from_mapping(palette)
    colors = tuple(palette)
    if not colors:
        raise TextureSamplingError("TEXTURE_PALETTE_EMPTY", "色卡不能为空")
    if not all(isinstance(color, PaletteColor) for color in colors):
        raise TypeError("palette must contain PaletteColor values")
    return tuple(sorted(colors, key=lambda color: color.id))


def _surface_color_sampler(mesh: Any, faces: NDArray[np.int64]) -> ColorSampler:
    visual = getattr(mesh, "visual", None)
    if visual is None:
        return _default_color_sampler()

    if getattr(visual, "kind", None) == "texture":
        uv = getattr(visual, "uv", None)
        if uv is None:
            raise TextureSamplingError("TEXTURE_UV_MISSING", "纹理网格缺少 UV 坐标")
        material = getattr(visual, "material", None)
        image = getattr(material, "image", None)
        if image is None:
            raise TextureSamplingError("TEXTURE_IMAGE_MISSING", "纹理网格缺少贴图图像")
        uv_array = np.asarray(uv, dtype=np.float64)
        if uv_array.ndim != 2 or uv_array.shape[1] != 2 or uv_array.shape[0] != len(mesh.vertices):
            raise TextureSamplingError("TEXTURE_UV_INVALID", "UV 坐标数量或形状无效")
        if not np.isfinite(uv_array).all():
            raise TextureSamplingError("TEXTURE_UV_INVALID", "UV 坐标包含非有限数值")
        try:
            image_array = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        except Exception as exc:
            raise TextureSamplingError("TEXTURE_IMAGE_INVALID", "无法读取纹理图像") from exc
        if image_array.ndim != 3 or image_array.shape[2] != 4 or image_array.size == 0:
            raise TextureSamplingError("TEXTURE_IMAGE_INVALID", "纹理图像格式无效")

        def sample_texture(face_index: int, weights: tuple[float, float, float]) -> Rgb:
            face_vertices = faces[face_index]
            uv_sample = (
                weights[0] * uv_array[face_vertices[0]]
                + weights[1] * uv_array[face_vertices[1]]
                + weights[2] * uv_array[face_vertices[2]]
            )
            return _sample_texture_pixel(uv_sample, image_array)

        return sample_texture

    colors = getattr(visual, "vertex_colors", None)

    if colors is None:
        return _default_color_sampler()
    colors_array = _validate_vertex_colors(colors, len(mesh.vertices))

    def sample_vertex_color(face_index: int, weights: tuple[float, float, float]) -> Rgb:
        face_vertices = faces[face_index]
        sampled = (
            weights[0] * colors_array[face_vertices[0], :3]
            + weights[1] * colors_array[face_vertices[1], :3]
            + weights[2] * colors_array[face_vertices[2], :3]
        )
        return _clamp_rgb(sampled)

    return sample_vertex_color


def _validate_vertex_colors(colors: Any, vertex_count: int) -> ColorArray:
    colors_array = np.asarray(colors, dtype=np.float64)
    if colors_array.ndim != 2 or colors_array.shape[0] != vertex_count:
        raise TextureSamplingError("TEXTURE_VERTEX_COLOR_MISMATCH", "顶点颜色数量与顶点数量不一致")
    if colors_array.shape[1] == 3:
        alpha = np.full((colors_array.shape[0], 1), 255.0, dtype=np.float64)
        colors_array = np.concatenate((colors_array, alpha), axis=1)
    elif colors_array.shape[1] < 4:
        raise TextureSamplingError("TEXTURE_VERTEX_COLOR_INVALID", "顶点颜色必须包含 RGB 或 RGBA")
    if not np.isfinite(colors_array).all():
        raise TextureSamplingError("TEXTURE_VERTEX_COLOR_INVALID", "顶点颜色包含非有限数值")
    return colors_array[:, :4]


def _default_color_sampler() -> ColorSampler:
    def sample_default(face_index: int, weights: tuple[float, float, float]) -> Rgb:
        del face_index, weights
        return (102, 102, 102)

    return sample_default


def _sample_texture_pixel(uv: PointArray, image: NDArray[np.uint8]) -> Rgb:
    height, width = image.shape[:2]
    x = (float(uv[0]) * (width - 1)) % width
    y = ((1.0 - float(uv[1])) * (height - 1)) % height
    column = round(x) % width
    row = round(y) % height
    pixel = image[row, column]
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


def _clamp_rgb(sampled: Any) -> Rgb:
    return (
        round(min(255.0, max(0.0, float(sampled[0])))),
        round(min(255.0, max(0.0, float(sampled[1])))),
        round(min(255.0, max(0.0, float(sampled[2])))),
    )


def _non_degenerate_faces(triangles: NDArray[np.float64]) -> NDArray[np.int64]:
    if triangles.ndim != 3 or triangles.shape[1:] != (3, 3):
        raise TextureSamplingError("TEXTURE_INVALID_TRIANGLES", "三角面数组形状无效")
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    areas = np.linalg.norm(cross, axis=1) * 0.5
    return np.flatnonzero(areas > _AREA_EPSILON).astype(np.int64)


def _sample_surface_colors(
    normalized: NormalizedMesh,
    surface_voxels: Sequence[Coord3],
    triangles: NDArray[np.float64],
    valid_faces: NDArray[np.int64],
    sampler: ColorSampler,
    tree: cKDTree,
) -> dict[Coord3, Rgb]:
    """Sample all surface voxels with vectorized nearest-triangle queries."""
    surface_rgb: dict[Coord3, Rgb] = {}
    candidate_count = min(_TRIANGLE_CANDIDATES, int(valid_faces.size))
    for start in range(0, len(surface_voxels), _SURFACE_CHUNK):
        chunk = surface_voxels[start : start + _SURFACE_CHUNK]
        centers = (np.asarray(chunk, dtype=np.float64) + 0.5) * normalized.pitch_mm
        _, candidate_positions = tree.query(centers, k=candidate_count)
        positions = np.asarray(candidate_positions, dtype=np.int64)
        if positions.ndim == 1:
            positions = positions[:, None]
        candidate_faces = valid_faces[positions]
        candidate_triangles = triangles[candidate_faces]
        repeated_points = np.repeat(centers[:, None, :], candidate_count, axis=1).reshape(-1, 3)
        closest = trimesh.triangles.closest_point(
            candidate_triangles.reshape(-1, 3, 3),
            repeated_points,
        ).reshape(len(chunk), candidate_count, 3)
        weights = trimesh.triangles.points_to_barycentric(
            candidate_triangles.reshape(-1, 3, 3),
            closest.reshape(-1, 3),
        ).reshape(len(chunk), candidate_count, 3)
        distances = np.linalg.norm(centers[:, None, :] - closest, axis=2)
        best_distance = distances.min(axis=1, keepdims=True)
        tie_mask = distances <= best_distance + _DISTANCE_EPSILON
        tie_faces = np.where(tie_mask, candidate_faces, np.iinfo(np.int64).max)
        best_position = np.argmin(tie_faces, axis=1)
        rows = np.arange(len(chunk))
        best_faces = candidate_faces[rows, best_position]
        best_weights = weights[rows, best_position]
        for voxel, face_index, voxel_weights in zip(
            chunk,
            best_faces.tolist(),
            best_weights.tolist(),
            strict=True,
        ):
            surface_rgb[voxel] = sampler(
                int(face_index),
                (float(voxel_weights[0]), float(voxel_weights[1]), float(voxel_weights[2])),
            )
    return surface_rgb
