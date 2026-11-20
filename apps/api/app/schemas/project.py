from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class BeadSpecIn(BaseModel):
    size: Literal["5mm", "2.6mm"] = "5mm"
    outer_diameter_mm: float = Field(default=5.0, gt=0)
    pitch_mm: float = Field(default=5.0, gt=0)
    height_mm: float = Field(default=5.1, gt=0)
    hole_diameter_mm: float = Field(default=2.2, gt=0)
    board_max_cells_x: int = Field(default=29, gt=0)
    board_max_cells_y: int = Field(default=29, gt=0)

    @model_validator(mode="after")
    def validate_hole_diameter(self) -> BeadSpecIn:
        if self.hole_diameter_mm >= self.outer_diameter_mm:
            raise ValueError("hole_diameter_mm must be smaller than outer_diameter_mm")
        return self


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    bead_spec: BeadSpecIn = Field(default_factory=BeadSpecIn)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class ImageResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    view: str
    relative_path: str


class ProjectResponse(BaseModel):
    id: str
    name: str
    status: str
    image_count: int
    bead_spec: BeadSpecIn
    route_policy: str
    created_at: datetime
    updated_at: datetime
    images: list[ImageResponse] = Field(default_factory=list)


class CompileProjectRequest(BaseModel):
    route_policy: str = "shape_partitioned_double_sided_hole_glue_free"
    options: dict[str, object] = Field(default_factory=dict)


class ArtifactResponse(BaseModel):
    id: str
    kind: str
    filename: str
    content_type: str
    size_bytes: int
    download_url: str


class VoxelCellResponse(BaseModel):
    x: int
    y: int
    color: str
    hex: str


class VoxelPreviewResponse(BaseModel):
    project_id: str
    artifact_id: str
    grid_shape: tuple[int, int, int]
    grid_extent_mm: tuple[float, float, float]
    pitch_mm: float
    slice_index: int
    slice_count: int
    occupied_count: int
    color_counts: dict[str, int]
    palette: dict[str, str]
    cells: list[VoxelCellResponse] = Field(default_factory=list)


class ValidationIssueResponse(BaseModel):
    code: str
    severity: str
    message: str
    plate_id: str | None = None
    joint_id: str | None = None


class ValidationReportResponse(BaseModel):
    ok: bool
    issues: list[ValidationIssueResponse] = Field(default_factory=list)
