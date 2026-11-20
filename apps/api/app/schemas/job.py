from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StageProgress(BaseModel):
    id: str
    label: str
    status: str
    progress: int = Field(default=0, ge=0, le=100)
    message: str | None = None


class JobResponse(BaseModel):
    id: str
    project_id: str
    status: str
    stages: list[StageProgress]
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    error_code: str | None = None
    error_details: dict[str, Any] = Field(default_factory=dict)
