from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from math import ceil
from pathlib import Path
from typing import Any

import numpy as np
import trimesh  # type: ignore[import-untyped]
from numpy.typing import NDArray
from scipy import ndimage  # type: ignore[import-untyped]

from app.domain.bead import BeadSpec
from app.domain.voxel import Coord3, VoxelGrid

Matrix4 = NDArray[np.float64]
Vector3 = NDArray[np.float64]

_GRID_EPSILON = 1e-9
class NormalizationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class UpAxis(str, Enum):
    Y = "y"
    Z = "z"


@dataclass(frozen=True, slots=True)
class NormalizedMesh:
    mesh: Any
    transform: Matrix4
    width: int
    height: int
    depth: int
    pitch_mm: float
    source_up_axis: UpAxis
    target_height_mm: float | None

    @property
    def grid_shape(self) -> tuple[int, int, int]:
        return self.width, self.height, self.depth

    @property
    def grid_extent_mm(self) -> tuple[float, float, float]:
        return (
            self.width * self.pitch_mm,
            self.height * self.pitch_mm,
            self.depth * self.pitch_mm,
        )

    def voxel_center(self, x: int, y: int, z: int) -> tuple[float, float, float]:
        if not (0 <= x < self.width and 0 <= y < self.height and 0 <= z < self.depth):
            raise ValueError(f"voxel {(x, y, z)} is outside the grid")
        return (
            (x + 0.5) * self.pitch_mm,
            (y + 0.5) * self.pitch_mm,
            (z + 0.5) * self.pitch_mm,
        )

    def transform_point(self, point: Sequence[float]) -> tuple[float, float, float]:
        if len(point) != 3:
            raise ValueError("point must contain exactly three coordinates")
        homogeneous = np.array([point[0], point[1], point[2], 1.0], dtype=np.float64)
        transformed = self.transform @ homogeneous
        return float(transformed[0]), float(transformed[1]), float(transformed[2])


def load_glb_mesh(path: Path) -> Any:
    """Load a GLB/GLTF asset and concatenate scene geometry into one mesh."""
    if not path.is_file():
        raise NormalizationError(
            "NORMALIZATION_GLB_NOT_FOUND",
            f"GLB 文件不存在：{path}",
        )
    try:
        loaded = trimesh.load(path, force="mesh")
    except Exception as exc:
        raise NormalizationError(
            "NORMALIZATION_GLB_LOAD_FAILED",
            f"无法读取 GLB：{path}",
        ) from exc

    if isinstance(loaded, trimesh.Scene):
        geometries = [geometry for geometry in loaded.geometry.values() if isinstance(geometry, trimesh.Trimesh)]
        if not geometries:
            raise NormalizationError("NORMALIZATION_EMPTY_MESH", "GLB 场景中没有三角网格")
        loaded = trimesh.util.concatenate(geometries)

    if not isinstance(loaded, trimesh.Trimesh) or loaded.is_empty or len(loaded.faces) == 0:
        raise NormalizationError("NORMALIZATION_EMPTY_MESH", "GLB 中没有可用的三角网格")
    if not np.isfinite(np.asarray(loaded.vertices, dtype=np.float64)).all():
        raise NormalizationError("NORMALIZATION_INVALID_VERTEX", "GLB 顶点包含非有限数值")
    return loaded


def normalize_mesh(
    mesh: Any,
    *,
    bead_spec: BeadSpec,
    target_height_mm: float | None = None,
    source_up_axis: UpAxis | str = UpAxis.Y,
) -> NormalizedMesh:
    """Map a source mesh into a deterministic z-up millimetre voxel grid."""
    try:
        up_axis = UpAxis(source_up_axis)
    except ValueError as exc:
        raise NormalizationError(
            "NORMALIZATION_UP_AXIS_UNSUPPORTED",
            f"不支持的源上轴：{source_up_axis}",
        ) from exc
    if target_height_mm is not None and target_height_mm <= 0:
        raise NormalizationError(
            "NORMALIZATION_INVALID_TARGET_HEIGHT",
            "target_height_mm 必须为正数",
        )
    if not isinstance(mesh, trimesh.Trimesh) or mesh.is_empty or len(mesh.faces) == 0:
        raise NormalizationError("NORMALIZATION_EMPTY_MESH", "没有可归一化的三角网格")

    rotation = _up_axis_rotation(up_axis)
    rotated = mesh.copy()
    rotated.apply_transform(rotation)
    rotated_extents = np.asarray(rotated.extents, dtype=np.float64)
    if rotated_extents[2] <= _GRID_EPSILON:
        raise NormalizationError("NORMALIZATION_DEGENERATE_HEIGHT", "模型高度必须大于 0")

    scale = 1.0 if target_height_mm is None else target_height_mm / float(rotated_extents[2])
    if not np.isfinite(scale) or scale <= 0:
        raise NormalizationError("NORMALIZATION_INVALID_SCALE", "模型缩放必须为正数")

    scale_matrix = np.eye(4, dtype=np.float64)
    scale_matrix[0, 0] = scale
    scale_matrix[1, 1] = scale
    scale_matrix[2, 2] = scale
    scaled = rotated.copy()
    scaled.apply_transform(scale_matrix)

    extents = np.asarray(scaled.extents, dtype=np.float64)
    width = _grid_cells(extents[0], bead_spec.pitch_mm)
    height = _grid_cells(extents[1], bead_spec.pitch_mm)
    depth = _grid_cells(extents[2], bead_spec.pitch_mm)
    grid_extent = np.array([width, height, depth], dtype=np.float64) * bead_spec.pitch_mm
    bounds = np.asarray(scaled.bounds, dtype=np.float64)

    translation = np.array(
        [
            grid_extent[0] / 2 - (bounds[0, 0] + bounds[1, 0]) / 2,
            grid_extent[1] / 2 - (bounds[0, 1] + bounds[1, 1]) / 2,
            -bounds[0, 2],
        ],
        dtype=np.float64,
    )
    translation_matrix = np.eye(4, dtype=np.float64)
    translation_matrix[:3, 3] = translation
    transform = translation_matrix @ scale_matrix @ rotation

    normalized = mesh.copy()
    normalized.apply_transform(transform)
    normalized_bounds = np.asarray(normalized.bounds, dtype=np.float64)
    if np.any(normalized_bounds[0] < -1e-6) or np.any(normalized_bounds[1] > grid_extent + 1e-6):
        raise NormalizationError("NORMALIZATION_GRID_ESCAPE", "归一化后模型超出体素网格")

    return NormalizedMesh(
        mesh=normalized,
        transform=transform,
        width=width,
        height=height,
        depth=depth,
        pitch_mm=bead_spec.pitch_mm,
        source_up_axis=up_axis,
        target_height_mm=target_height_mm,
    )


def surface_voxel_grid(normalized: NormalizedMesh) -> VoxelGrid:
    """Conservative deterministic surface voxelization for M2-T1 golden samples."""
    pitch = normalized.pitch_mm
    shape = np.array(normalized.grid_shape, dtype=np.int64)
    occupied: set[Coord3] = set()
    triangles = np.asarray(normalized.mesh.triangles, dtype=np.float64)

    for triangle in triangles:
        if not np.isfinite(triangle).all():
            continue
        candidates = _triangle_candidate_indices(triangle, pitch, shape)
        if candidates.size == 0:
            continue
        intersected = _triangle_intersects_aabb_batch(triangle, candidates, pitch)
        occupied.update(
            (int(x), int(y), int(z))
            for x, y, z in candidates[intersected]
        )

    if not occupied:
        raise NormalizationError("NORMALIZATION_EMPTY_VOXEL_GRID", "表面体素化没有产生任何体素")
    return VoxelGrid(
        width=normalized.width,
        height=normalized.height,
        depth=normalized.depth,
        occupied=frozenset(occupied),
    )


def solid_voxel_grid(normalized: NormalizedMesh, *, surface: VoxelGrid | None = None) -> VoxelGrid:
    """Fill the interior of a watertight normalized mesh deterministically.

    The surface pass is conservative: every voxel touched by a triangle is
    occupied.  A 6-connected hole fill then treats every empty region that is
    not connected to the grid boundary as interior.  This is equivalent to an
    exterior flood-fill, but uses a compact boolean volume so large grids do
    not allocate one Python object per exterior voxel.
    """
    topology = normalized.mesh.copy()
    topology.merge_vertices()
    if not (topology.is_watertight and topology.is_winding_consistent):
        raise NormalizationError(
            "NORMALIZATION_NOT_WATERTIGHT",
            "模型不是闭合且法线一致的网格，无法可靠地实心体素化",
        )

    surface_grid = surface or surface_voxel_grid(normalized)
    if (surface_grid.width, surface_grid.height, surface_grid.depth) != normalized.grid_shape:
        raise NormalizationError(
            "NORMALIZATION_SURFACE_GRID_MISMATCH",
            "表面体素网格尺寸与归一化网格不一致",
        )
    shape = normalized.grid_shape
    occupied = np.zeros(shape, dtype=bool)
    for x, y, z in surface_grid.occupied:
        occupied[x, y, z] = True

    # scipy's binary_fill_holes is C-backed and keeps memory bounded for the
    # 256^3 performance target.  The 6-connected structuring element matches
    # the voxel adjacency used by the rest of the pipeline.
    solid = ndimage.binary_fill_holes(
        occupied,
        structure=ndimage.generate_binary_structure(3, 1),
    )
    solid_points = np.argwhere(solid)
    solid_occupied: set[Coord3] = set(
        zip(
            solid_points[:, 0].tolist(),
            solid_points[:, 1].tolist(),
            solid_points[:, 2].tolist(),
            strict=True,
        )
    )
    if not solid_occupied:
        raise NormalizationError("NORMALIZATION_EMPTY_VOXEL_GRID", "实心体素化没有产生任何体素")

    return VoxelGrid(
        width=normalized.width,
        height=normalized.height,
        depth=normalized.depth,
        occupied=frozenset(solid_occupied),
    )


def _grid_cells(extent_mm: float, pitch_mm: float) -> int:
    return max(1, ceil(extent_mm / pitch_mm - _GRID_EPSILON))


def _up_axis_rotation(up_axis: UpAxis) -> Matrix4:
    if up_axis is UpAxis.Z:
        return np.eye(4, dtype=np.float64)
    # glTF/Tripo 常见 Y-up：绕 X 轴 +90°，把源 Y 映射到世界 Z。
    rotation = np.eye(4, dtype=np.float64)
    rotation[1, 1] = 0.0
    rotation[1, 2] = -1.0
    rotation[2, 1] = 1.0
    rotation[2, 2] = 0.0
    return rotation


def _triangle_candidate_indices(
    triangle: Vector3,
    pitch: float,
    shape: NDArray[np.int64],
) -> NDArray[np.int64]:
    low = triangle.min(axis=0) - pitch / 2
    high = triangle.max(axis=0) + pitch / 2
    index_min = np.maximum(np.floor(low / pitch + _GRID_EPSILON).astype(np.int64), 0)
    index_max = np.minimum(
        np.floor(high / pitch - _GRID_EPSILON).astype(np.int64),
        shape - 1,
    )
    if np.any(index_max < index_min):
        return np.empty((0, 3), dtype=np.int64)
    axes = [
        np.arange(int(index_min[axis]), int(index_max[axis]) + 1, dtype=np.int64)
        for axis in range(3)
    ]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


def _triangle_intersects_aabb_batch(
    triangle: Vector3,
    indices: NDArray[np.int64],
    pitch: float,
) -> NDArray[np.bool_]:
    """Vectorized triangle/AABB SAT for all candidate voxels of one triangle."""
    half = pitch * 0.5
    centers = (indices.astype(np.float64) + 0.5) * pitch
    a = triangle[0] - centers
    b = triangle[1] - centers
    c = triangle[2] - centers

    triangle_min = np.minimum(np.minimum(a, b), c)
    triangle_max = np.maximum(np.maximum(a, b), c)
    overlap = ~(
        np.any(triangle_min > half, axis=1)
        | np.any(triangle_max < -half, axis=1)
    )
    normal = np.cross(b - a, c - a)
    normal_norm = np.linalg.norm(normal, axis=1)
    distance = np.einsum("ij,ij->i", normal, a)
    radius = np.sum(np.abs(normal), axis=1) * half
    mask = (
        overlap
        & (normal_norm > _GRID_EPSILON)
        & (np.abs(distance) <= radius + _GRID_EPSILON)
    )
    if not np.any(mask):
        return mask

    axes = np.eye(3, dtype=np.float64)
    for edge in (b - a, c - b, a - c):
        for axis in axes:
            separating_axis = np.cross(edge, axis)
            separating_norm = np.linalg.norm(separating_axis, axis=1)
            valid = separating_norm > _GRID_EPSILON
            projections_a = np.einsum("ij,ij->i", separating_axis, a)
            projections_b = np.einsum("ij,ij->i", separating_axis, b)
            projections_c = np.einsum("ij,ij->i", separating_axis, c)
            box_radius = np.sum(np.abs(separating_axis), axis=1) * half
            separated = (
                np.minimum(np.minimum(projections_a, projections_b), projections_c)
                > box_radius + _GRID_EPSILON
            ) | (
                np.maximum(np.maximum(projections_a, projections_b), projections_c)
                < -box_radius - _GRID_EPSILON
            )
            mask &= ~(valid & separated)
            if not np.any(mask):
                return mask
    return mask
