from fastapi import APIRouter, BackgroundTasks, Depends, status

from app.api.deps import get_project_service
from app.schemas.job import JobResponse
from app.services.project_service import ProjectService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    service: ProjectService = Depends(get_project_service),
) -> JobResponse:
    return service.get_job(job_id)


@router.post(
    "/{job_id}/retry",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    service: ProjectService = Depends(get_project_service),
) -> JobResponse:
    job = service.retry_job(job_id)
    background_tasks.add_task(service.run_job, job.id)
    return job
