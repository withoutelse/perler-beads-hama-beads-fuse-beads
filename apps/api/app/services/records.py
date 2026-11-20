from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.bead import BeadSpec
from app.domain.image import StoredImage


@dataclass(slots=True)
class ArtifactRecord:
    id: str
    project_id: str
    job_id: str | None
    kind: str
    filename: str
    content_type: str
    size_bytes: int
    relative_path: str
    created_at: datetime


@dataclass(slots=True)
class StageRecord:
    id: str
    label: str
    status: str = "queued"
    progress: int = 0
    message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(slots=True)
class JobRecord:
    id: str
    project_id: str
    status: str
    stages: list[StageRecord]
    created_at: datetime
    updated_at: datetime
    error_code: str | None = None
    error_message: str | None = None
    error_details: dict[str, Any] = field(default_factory=dict)
    tripo_task_id: str | None = None
    model_path: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectRecord:
    id: str
    name: str
    bead_spec: BeadSpec
    status: str
    created_at: datetime
    updated_at: datetime
    images: list[StoredImage] = field(default_factory=list)
    artifacts: list[ArtifactRecord] = field(default_factory=list)

    @property
    def image_count(self) -> int:
        return len(self.images)
