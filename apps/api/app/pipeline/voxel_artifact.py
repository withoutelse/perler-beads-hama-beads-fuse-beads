from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from app.domain.bead import BeadSpec
from app.domain.color import default_perler_standard_palette
from app.domain.voxel import Coord3
from app.pipeline.normalization import (
    UpAxis,
    load_glb_mesh,
    normalize_mesh,
    solid_voxel_grid,
    surface_voxel_grid,
)
from app.pipeline.texture import colorize_voxel_grid

VOXEL_ARTIFACT_SCHEMA_VERSION = 1
VOXEL_ARTIFACT_KIND = "voxel_npz"
VOXEL_ARTIFACT_CONTENT_TYPE = "application/octet-stream"
VOXEL_ARTIFACT_PALETTE_ID = "perler-standard-v1"

_SUPPORTED_PALETTE_IDS = frozenset({"perler-standard", VOXEL_ARTIFACT_PALETTE_ID})


class VoxelArtifactError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class VoxelizationOptions:
    target_height_mm: float = 80.0
    source_up_axis: UpAxis = UpAxis.Y
    delta_e_tolerance: float = 6.0
    palette_id: str = VOXEL_ARTIFACT_PALETTE_ID

    @classmethod
    def from_mapping(cls, options: Mapping[str, object] | None = None) -> VoxelizationOptions:
        values = options or {}
        target_height_mm = _positive_float(
            values.get("target_height_mm", 80.0),
            code="VOXEL_INVALID_TARGET_HEIGHT",
            message="target_height_mm 必须为正数",
        )
        delta_e_tolerance = _non_negative_float(
            values.get("delta_e_tolerance", 6.0),
            code="VOXEL_INVALID_TOLERANCE",
            message="delta_e_tolerance 不能为负数",
        )
        source_up_axis = _coerce_up_axis(values.get("source_up_axis", UpAxis.Y))
        palette_id = _coerce_palette_id(values.get("color_palette", VOXEL_ARTIFACT_PALETTE_ID))
        return cls(
            target_height_mm=target_height_mm,
            source_up_axis=source_up_axis,
            delta_e_tolerance=delta_e_tolerance,
            palette_id=palette_id,
        )

    def cache_payload(self) -> dict[str, object]:
        return {
            "schema_version": VOXEL_ARTIFACT_SCHEMA_VERSION,
            "target_height_mm": self.target_height_mm,
            "source_up_axis": self.source_up_axis.value,
            "delta_e_tolerance": self.delta_e_tolerance,
            "palette_id": self.palette_id,
        }


@dataclass(frozen=True, slots=True)
class VoxelArtifact:
    source_model_artifact_id: str
    source_model_relative_path: str
    options: VoxelizationOptions
    pitch_mm: float
    grid_shape: tuple[int, int, int]
    grid_extent_mm: tuple[float, float, float]
    occupied: frozenset[Coord3]
    color_by_voxel: Mapping[Coord3, str]
    palette: Mapping[str, str]
    surface_voxel_count: int
    interior_voxel_count: int
    schema_version: int = VOXEL_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != VOXEL_ARTIFACT_SCHEMA_VERSION:
            raise VoxelArtifactError(
                "VOXEL_ARTIFACT_SCHEMA_UNSUPPORTED",
                f"不支持的体素产物版本：{self.schema_version}",
            )
        if min(self.grid_shape) <= 0:
            raise VoxelArtifactError("VOXEL_ARTIFACT_INVALID_GRID", "体素网格尺寸必须为正数")
        if self.pitch_mm <= 0 or not math.isfinite(self.pitch_mm):
            raise VoxelArtifactError("VOXEL_ARTIFACT_INVALID_PITCH", "体素间距必须为正数")
        if len(self.grid_extent_mm) != 3 or any(
            not math.isfinite(value) or value <= 0 for value in self.grid_extent_mm
        ):
            raise VoxelArtifactError("VOXEL_ARTIFACT_INVALID_EXTENT", "体素物理边界必须为正数")
        for x, y, z in self.occupied:
            if not (
                0 <= x < self.grid_shape[0]
                and 0 <= y < self.grid_shape[1]
                and 0 <= z < self.grid_shape[2]
            ):
                raise VoxelArtifactError(
                    "VOXEL_ARTIFACT_INVALID_VOXEL",
                    f"体素 {(x, y, z)} 超出网格范围",
                )
        unknown_colors = set(self.color_by_voxel) - self.occupied
        if unknown_colors:
            raise VoxelArtifactError(
                "VOXEL_ARTIFACT_INVALID_COLOR_MAP",
                "color_by_voxel 的键必须是占用体素的子集",
            )
        palette_ids = set(self.palette)
        if any(color_id not in palette_ids for color_id in self.color_by_voxel.values()):
            raise VoxelArtifactError(
                "VOXEL_ARTIFACT_INVALID_COLOR_MAP",
                "color_by_voxel 包含色卡中不存在的色号",
            )
        object.__setattr__(self, "color_by_voxel", MappingProxyType(dict(self.color_by_voxel)))
        object.__setattr__(self, "palette", MappingProxyType(dict(self.palette)))

    def color_counts(self) -> dict[str, int]:
        return dict(Counter(self.color_by_voxel.values()))


def build_voxel_artifact(
    *,
    model_path: Path,
    model_artifact_id: str,
    model_relative_path: str,
    bead_spec: BeadSpec,
    options: VoxelizationOptions,
) -> VoxelArtifact:
    """Build a deterministic, colour-matched solid voxel artifact from a GLB."""
    normalized = normalize_mesh(
        load_glb_mesh(model_path),
        bead_spec=bead_spec,
        target_height_mm=options.target_height_mm,
        source_up_axis=options.source_up_axis,
    )
    surface = surface_voxel_grid(normalized)
    solid = solid_voxel_grid(normalized, surface=surface)
    palette = default_perler_standard_palette()
    colored = colorize_voxel_grid(
        normalized,
        solid,
        palette,
        delta_e_tolerance=options.delta_e_tolerance,
        surface=surface,
    )
    palette_by_id = {color.id: color.hex for color in palette}
    return VoxelArtifact(
        source_model_artifact_id=model_artifact_id,
        source_model_relative_path=model_relative_path,
        options=options,
        pitch_mm=normalized.pitch_mm,
        grid_shape=normalized.grid_shape,
        grid_extent_mm=normalized.grid_extent_mm,
        occupied=colored.occupied,
        color_by_voxel=colored.color_by_voxel,
        palette=palette_by_id,
        surface_voxel_count=len(surface.occupied),
        interior_voxel_count=len(colored.occupied - surface.occupied),
    )


def voxel_cache_key(
    *,
    model_artifact_id: str,
    model_relative_path: str,
    pitch_mm: float,
    options: VoxelizationOptions,
) -> str:
    payload = {
        "model_artifact_id": model_artifact_id,
        "model_relative_path": model_relative_path,
        "pitch_mm": float(pitch_mm),
        **options.cache_payload(),
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def voxel_artifact_id(cache_key: str) -> str:
    return f"art_voxel_npz_{cache_key[:24]}"


def save_voxel_artifact(path: Path, artifact: VoxelArtifact) -> None:
    """Persist a voxel artifact in a compressed, pickle-free NPZ container."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    try:
        occupied_xyz = np.asarray(sorted(artifact.occupied), dtype=np.int32)
        if occupied_xyz.size == 0:
            occupied_xyz = np.empty((0, 3), dtype=np.int32)
        palette_ids = np.asarray(sorted(artifact.palette), dtype=np.str_)
        palette_hex = np.asarray([artifact.palette[str(color_id)] for color_id in palette_ids], dtype=np.str_)
        palette_index = {str(color_id): index for index, color_id in enumerate(palette_ids)}
        color_index = np.asarray(
            [palette_index[artifact.color_by_voxel[voxel]] for voxel in sorted(artifact.occupied)],
            dtype=np.int32,
        )
        with temporary_path.open("wb") as handle:
            np.savez_compressed(
                handle,
                schema_version=np.asarray(artifact.schema_version, dtype=np.int32),
                source_model_artifact_id=np.asarray(artifact.source_model_artifact_id),
                source_model_relative_path=np.asarray(artifact.source_model_relative_path),
                target_height_mm=np.asarray(artifact.options.target_height_mm, dtype=np.float64),
                source_up_axis=np.asarray(artifact.options.source_up_axis.value),
                delta_e_tolerance=np.asarray(artifact.options.delta_e_tolerance, dtype=np.float64),
                palette_id=np.asarray(artifact.options.palette_id),
                pitch_mm=np.asarray(artifact.pitch_mm, dtype=np.float64),
                grid_shape=np.asarray(artifact.grid_shape, dtype=np.int32),
                grid_extent_mm=np.asarray(artifact.grid_extent_mm, dtype=np.float64),
                surface_voxel_count=np.asarray(artifact.surface_voxel_count, dtype=np.int64),
                interior_voxel_count=np.asarray(artifact.interior_voxel_count, dtype=np.int64),
                occupied_xyz=occupied_xyz,
                color_index=color_index,
                palette_ids=palette_ids,
                palette_hex=palette_hex,
            )
        temporary_path.replace(path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise VoxelArtifactError(
            "VOXEL_ARTIFACT_WRITE_FAILED",
            f"无法写入体素产物：{path}",
        ) from exc


def load_voxel_artifact(path: Path) -> VoxelArtifact:
    """Load a persisted voxel artifact and validate its internal consistency."""
    if not path.is_file():
        raise VoxelArtifactError("VOXEL_ARTIFACT_MISSING", f"体素产物不存在：{path}")
    try:
        with np.load(path, allow_pickle=False) as data:
            schema_version = int(np.asarray(data["schema_version"]).item())
            if schema_version != VOXEL_ARTIFACT_SCHEMA_VERSION:
                raise VoxelArtifactError(
                    "VOXEL_ARTIFACT_SCHEMA_UNSUPPORTED",
                    f"不支持的体素产物版本：{schema_version}",
                )
            grid_shape = _read_int_tuple(data["grid_shape"], length=3)
            grid_extent_mm = _read_float_tuple(data["grid_extent_mm"], length=3)
            occupied_xyz = np.asarray(data["occupied_xyz"], dtype=np.int64)
            color_index = np.asarray(data["color_index"], dtype=np.int64)
            palette_ids = [str(value) for value in np.asarray(data["palette_ids"]).tolist()]
            palette_hex = [str(value) for value in np.asarray(data["palette_hex"]).tolist()]
            if occupied_xyz.ndim != 2 or occupied_xyz.shape[1] != 3:
                raise VoxelArtifactError(
                    "VOXEL_ARTIFACT_INVALID_VOXEL",
                    "occupied_xyz 必须是 N×3 数组",
                )
            if color_index.shape != (occupied_xyz.shape[0],):
                raise VoxelArtifactError(
                    "VOXEL_ARTIFACT_INVALID_COLOR_MAP",
                    "color_index 数量必须与占用体素一致",
                )
            if len(palette_ids) != len(palette_hex):
                raise VoxelArtifactError(
                    "VOXEL_ARTIFACT_INVALID_COLOR_MAP",
                    "色卡 ID 与十六进制颜色数量不一致",
                )
            palette = dict(zip(palette_ids, palette_hex, strict=True))
            occupied: set[Coord3] = set()
            color_by_voxel: dict[Coord3, str] = {}
            for index, xyz in enumerate(occupied_xyz.tolist()):
                voxel = (int(xyz[0]), int(xyz[1]), int(xyz[2]))
                if voxel in occupied:
                    raise VoxelArtifactError(
                        "VOXEL_ARTIFACT_INVALID_VOXEL",
                        f"体素产物包含重复体素：{voxel}",
                    )
                color_position = int(color_index[index])
                if not 0 <= color_position < len(palette_ids):
                    raise VoxelArtifactError(
                        "VOXEL_ARTIFACT_INVALID_COLOR_MAP",
                        "color_index 超出色卡范围",
                    )
                occupied.add(voxel)
                color_by_voxel[voxel] = palette_ids[color_position]
            return VoxelArtifact(
                schema_version=schema_version,
                source_model_artifact_id=_read_text(data["source_model_artifact_id"]),
                source_model_relative_path=_read_text(data["source_model_relative_path"]),
                options=VoxelizationOptions(
                    target_height_mm=float(np.asarray(data["target_height_mm"]).item()),
                    source_up_axis=_coerce_up_axis(_read_text(data["source_up_axis"])),
                    delta_e_tolerance=float(np.asarray(data["delta_e_tolerance"]).item()),
                    palette_id=_coerce_palette_id(_read_text(data["palette_id"])),
                ),
                pitch_mm=float(np.asarray(data["pitch_mm"]).item()),
                grid_shape=grid_shape,
                grid_extent_mm=grid_extent_mm,
                occupied=frozenset(occupied),
                color_by_voxel=color_by_voxel,
                palette=palette,
                surface_voxel_count=int(np.asarray(data["surface_voxel_count"]).item()),
                interior_voxel_count=int(np.asarray(data["interior_voxel_count"]).item()),
            )
    except VoxelArtifactError:
        raise
    except Exception as exc:
        raise VoxelArtifactError(
            "VOXEL_ARTIFACT_READ_FAILED",
            f"无法读取体素产物：{path}",
        ) from exc


def _positive_float(value: object, *, code: str, message: str) -> float:
    number = _finite_float(value, code=code, message=message)
    if number <= 0:
        raise VoxelArtifactError(code, message)
    return number


def _non_negative_float(value: object, *, code: str, message: str) -> float:
    number = _finite_float(value, code=code, message=message)
    if number < 0:
        raise VoxelArtifactError(code, message)
    return number


def _finite_float(value: object, *, code: str, message: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VoxelArtifactError(code, message)
    number = float(value)
    if not math.isfinite(number):
        raise VoxelArtifactError(code, message)
    return number


def _coerce_up_axis(value: object) -> UpAxis:
    if isinstance(value, UpAxis):
        return value
    try:
        return UpAxis(str(value))
    except ValueError as exc:
        raise VoxelArtifactError(
            "VOXEL_INVALID_UP_AXIS",
            "source_up_axis 必须是 y 或 z",
        ) from exc


def _coerce_palette_id(value: object) -> str:
    if not isinstance(value, str) or value not in _SUPPORTED_PALETTE_IDS:
        raise VoxelArtifactError(
            "VOXEL_UNSUPPORTED_PALETTE",
            "当前只支持 perler-standard 色卡",
        )
    return VOXEL_ARTIFACT_PALETTE_ID


def _read_text(value: Any) -> str:
    return str(np.asarray(value).item())


def _read_int_tuple(value: Any, *, length: int) -> tuple[int, int, int]:
    array = np.asarray(value)
    if array.ndim != 1 or array.shape[0] != length:
        raise VoxelArtifactError("VOXEL_ARTIFACT_INVALID_GRID", "网格尺寸必须是三维整数元组")
    return int(array[0]), int(array[1]), int(array[2])


def _read_float_tuple(value: Any, *, length: int) -> tuple[float, float, float]:
    array = np.asarray(value)
    if array.ndim != 1 or array.shape[0] != length:
        raise VoxelArtifactError("VOXEL_ARTIFACT_INVALID_EXTENT", "物理边界必须是三维浮点元组")
    return float(array[0]), float(array[1]), float(array[2])
