from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import get_project_service
from app.core.errors import InvalidInputError
from app.domain.image import ImageUpload, ImageView
from app.schemas.job import JobResponse
from app.schemas.project import (
    ArtifactResponse,
    CompileProjectRequest,
    CreateProjectRequest,
    ProjectResponse,
    VoxelPreviewResponse,
)
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: CreateProjectRequest,
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    return service.create_project(payload)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    return service.get_project(project_id)


@router.post("/{project_id}/images", response_model=ProjectResponse)
async def upload_images(
    project_id: str,
    files: list[UploadFile] = File(...),
    view: str = Form("unknown"),
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    try:
        image_view = ImageView(view)
    except ValueError as exc:
        raise InvalidInputError(
            "无效的视角标签",
            code="INVALID_IMAGE_VIEW",
            details={"view": view},
        ) from exc

    uploads: list[ImageUpload] = []
    for file in files:
        uploads.append(
            ImageUpload(
                filename=file.filename or "image",
                content_type=file.content_type,
                data=await file.read(),
                view=image_view,
            )
        )
    return service.add_images(project_id, uploads)


@router.post(
    "/{project_id}/compile",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def compile_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    payload: CompileProjectRequest | None = None,
    service: ProjectService = Depends(get_project_service),
) -> JobResponse:
    job = service.compile_project(project_id, payload)
    background_tasks.add_task(service.run_job, job.id)
    return job


@router.get("/{project_id}/artifacts", response_model=list[ArtifactResponse])
def list_artifacts(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
) -> list[ArtifactResponse]:
    return service.list_artifacts(project_id)


@router.get("/{project_id}/voxel-preview", response_model=VoxelPreviewResponse)
def get_voxel_preview(
    project_id: str,
    z: int | None = Query(default=None, ge=0),
    target_height_mm: float = Query(default=80.0, gt=0),
    source_up_axis: Literal["y", "z"] = Query(default="y"),
    delta_e_tolerance: float = Query(default=6.0, ge=0),
    service: ProjectService = Depends(get_project_service),
) -> VoxelPreviewResponse:
    return service.get_voxel_preview(
        project_id,
        z=z,
        target_height_mm=target_height_mm,
        source_up_axis=source_up_axis,
        delta_e_tolerance=delta_e_tolerance,
    )


@router.get("/{project_id}/artifacts/{artifact_id}")
def download_artifact(
    project_id: str,
    artifact_id: str,
    service: ProjectService = Depends(get_project_service),
) -> FileResponse:
    artifact, path = service.get_artifact_path(project_id, artifact_id)
    return FileResponse(
        path,
        media_type=artifact.content_type,
        filename=artifact.filename,
    )
