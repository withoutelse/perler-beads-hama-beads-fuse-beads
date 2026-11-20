from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.core.errors import AppError, InvalidInputError, NotFoundError
from app.domain.bead import BeadSize, BeadSpec
from app.domain.image import (
    ImageUpload,
    ImageValidationError,
    ImageValidator,
    StoredImage,
)
from app.pipeline.adapters.sqlite import SqliteStore
from app.pipeline.adapters.storage import LocalArtifactStorage
from app.pipeline.adapters.tripo import (
    TripoClient,
    TripoError,
    TripoHttpClient,
    TripoImage,
)
from app.pipeline.normalization import (
    NormalizationError,
    UpAxis,
)
from app.pipeline.orchestrator import STAGE_SPECS as PIPELINE_STAGE_SPECS
from app.pipeline.texture import TextureSamplingError
from app.pipeline.voxel_artifact import (
    VOXEL_ARTIFACT_CONTENT_TYPE,
    VOXEL_ARTIFACT_KIND,
    VoxelArtifact,
    VoxelArtifactError,
    VoxelizationOptions,
    build_voxel_artifact,
    load_voxel_artifact,
    save_voxel_artifact,
    voxel_artifact_id,
    voxel_cache_key,
)
from app.schemas.job import JobResponse, StageProgress
from app.schemas.project import (
    ArtifactResponse,
    BeadSpecIn,
    CompileProjectRequest,
    CreateProjectRequest,
    ImageResponse,
    ProjectResponse,
    VoxelCellResponse,
    VoxelPreviewResponse,
)
from app.services.records import ArtifactRecord, JobRecord, ProjectRecord, StageRecord

logger = logging.getLogger(__name__)

ROUTE_POLICY = "shape_partitioned_double_sided_hole_glue_free"


def _now() -> datetime:
    return datetime.now(UTC)


class ProjectService:
    def __init__(
        self,
        *,
        storage: LocalArtifactStorage | None = None,
        image_validator: ImageValidator | None = None,
        store: SqliteStore | None = None,
        tripo_client_factory: Callable[[], TripoClient] | None = None,
    ) -> None:
        self._storage = storage or LocalArtifactStorage(Path("./storage"))
        self._image_validator = image_validator or ImageValidator()
        self._store = store or SqliteStore(self._storage.root / "pindou.db")
        self._tripo_client_factory = tripo_client_factory or self._default_tripo_client

    def create_project(self, payload: CreateProjectRequest) -> ProjectResponse:
        now = _now()
        record = ProjectRecord(
            id=f"prj_{uuid4().hex[:12]}",
            name=payload.name,
            bead_spec=self._to_bead_spec(payload.bead_spec),
            status="draft",
            created_at=now,
            updated_at=now,
        )
        self._store.create_project(record)
        return self._to_response(record)

    def get_project(self, project_id: str) -> ProjectResponse:
        return self._to_response(self._get_record(project_id))

    def add_images(self, project_id: str, uploads: Sequence[ImageUpload]) -> ProjectResponse:
        record = self._get_record(project_id)
        try:
            validated = self._image_validator.validate(uploads)
        except ImageValidationError as exc:
            details = {"filename": exc.filename} if exc.filename else None
            raise InvalidInputError(str(exc), code=exc.code, details=details) from exc

        if record.image_count + len(validated) > self._image_validator.max_images:
            raise InvalidInputError(
                f"单个项目最多上传 {self._image_validator.max_images} 张多视角图片",
                code="TOO_MANY_IMAGES",
            )

        existing_hashes = {image.sha256 for image in record.images}
        new_images: list[StoredImage] = []
        for image in validated:
            if image.sha256 in existing_hashes:
                raise InvalidInputError(
                    "检测到重复图片，请移除重复视角",
                    code="DUPLICATE_IMAGE",
                    details={"filename": image.filename},
                )
            existing_hashes.add(image.sha256)

        for image in validated:
            image_id = f"img_{uuid4().hex[:12]}"
            relative_path = f"projects/{record.id}/images/{image_id}_{image.filename}"
            self._storage.write_bytes(relative_path, image.data)
            new_images.append(
                StoredImage(
                    id=image_id,
                    filename=image.filename,
                    content_type=image.content_type,
                    size_bytes=image.size_bytes,
                    sha256=image.sha256,
                    view=image.view,
                    relative_path=relative_path,
                )
            )

        now = _now()
        self._store.add_images(record.id, new_images, updated_at=now)
        record.images.extend(new_images)
        record.updated_at = now
        return self._to_response(record)

    def compile_project(
        self,
        project_id: str,
        payload: CompileProjectRequest | None = None,
    ) -> JobResponse:
        if payload is not None and payload.route_policy != ROUTE_POLICY:
            raise InvalidInputError(
                "只允许 shape_partitioned_double_sided_hole_glue_free 路线",
                code="ROUTE_VIOLATION",
            )
        record = self._get_record(project_id)
        if record.image_count < 3:
            raise InvalidInputError("至少上传 3 张多视角图片后才能开始编译")

        options = dict(payload.options) if payload is not None else {}
        try:
            VoxelizationOptions.from_mapping(options)
        except VoxelArtifactError as exc:
            raise InvalidInputError(
                str(exc),
                code=exc.code,
                details={"options": options},
            ) from exc

        active_job = self._store.get_latest_job(record.id)
        if active_job is not None and active_job.status in {"queued", "running"}:
            return self._to_job_response(active_job)

        now = _now()
        job = JobRecord(
            id=f"job_{uuid4().hex[:12]}",
            project_id=record.id,
            status="queued",
            stages=[
                StageRecord(
                    id=spec.id.value,
                    label=spec.label,
                    status="queued",
                    progress=0,
                    message=spec.description,
                )
                for spec in PIPELINE_STAGE_SPECS
            ],
            created_at=now,
            updated_at=now,
            options=options,
        )
        self._store.create_job(job)
        record.status = "queued"
        record.updated_at = now
        self._store.update_project_status(record.id, record.status, updated_at=now)
        return self._to_job_response(job)

    def get_job(self, job_id: str) -> JobResponse:
        return self._to_job_response(self._get_job_record(job_id))

    def retry_job(self, job_id: str) -> JobResponse:
        previous = self._get_job_record(job_id)
        if previous.status not in {"failed", "cancelled"}:
            raise InvalidInputError(
                "只有失败或取消的作业可以重试",
                code="JOB_NOT_RETRYABLE",
            )
        record = self._get_record(previous.project_id)
        if record.image_count < 3:
            raise InvalidInputError("项目图片不足，无法重试")
        try:
            VoxelizationOptions.from_mapping(previous.options)
        except VoxelArtifactError as exc:
            raise InvalidInputError(
                str(exc),
                code=exc.code,
                details={"options": previous.options},
            ) from exc
        latest = self._store.get_latest_job(record.id)
        if (
            latest is not None
            and latest.id != previous.id
            and latest.status in {"queued", "running"}
        ):
            return self._to_job_response(latest)

        now = _now()
        job = JobRecord(
            id=f"job_{uuid4().hex[:12]}",
            project_id=record.id,
            status="queued",
            stages=[
                StageRecord(
                    id=spec.id.value,
                    label=spec.label,
                    status="queued",
                    progress=0,
                    message=spec.description,
                )
                for spec in PIPELINE_STAGE_SPECS
            ],
            created_at=now,
            updated_at=now,
            options=dict(previous.options),
        )
        self._store.create_job(job)
        record.status = "queued"
        record.updated_at = now
        self._store.update_project_status(record.id, record.status, updated_at=now)
        return self._to_job_response(job)

    def run_job(self, job_id: str, tripo_client: TripoClient | None = None) -> JobResponse:
        """Execute ingestion, reconstruction (or reuse), and voxelization."""
        job = self._get_job_record(job_id)
        if job.status != "queued":
            return self._to_job_response(job)

        project = self._get_record(job.project_id)
        now = _now()
        job.status = "running"
        job.updated_at = now
        self._store.update_job_status(job.id, status=job.status, updated_at=now)
        self._store.update_project_status(project.id, "running", updated_at=now)
        active_stage = "ingest"

        try:
            self._update_stage(
                job,
                "ingest",
                status="running",
                progress=0,
                message="正在校验输入图片",
                started_at=now,
            )
            if project.image_count < 3:
                raise TripoError("TRIPO_NEEDS_MULTIVIEW", "Tripo 多视角重建至少需要 3 张图片")
            self._update_stage(
                job,
                "ingest",
                status="succeeded",
                progress=100,
                message=f"已校验 {project.image_count} 张多视角图片",
                finished_at=now,
            )
            model_artifact = self._latest_model_artifact(project.id)
            model_path = self._existing_artifact_path(model_artifact)
            if model_artifact is not None and model_path is not None:
                self._update_stage(
                    job,
                    "reconstruct",
                    status="running",
                    progress=0,
                    message="检测到已有 GLB，复用模型",
                    started_at=_now(),
                )
                job.model_path = model_artifact.relative_path
                self._store.update_job_model_path(job.id, job.model_path)
                self._update_stage(
                    job,
                    "reconstruct",
                    status="succeeded",
                    progress=100,
                    message="复用已有 GLB 模型，未重复调用 Tripo",
                    finished_at=_now(),
                )
            else:
                active_stage = "reconstruct"
                self._update_stage(
                    job,
                    "reconstruct",
                    status="running",
                    progress=5,
                    message="正在上传图片并创建 Tripo 任务",
                    started_at=_now(),
                )

                client = tripo_client or self._tripo_client_factory()
                images = tuple(
                    TripoImage(
                        path=self._storage.path_for(image.relative_path),
                        view=image.view.value,
                    )
                    for image in project.images
                )
                reconstruction = client.reconstruct(
                    images,
                    output_dir=self._storage.model_dir(project.id),
                    prompt=project.name,
                )
                task_id = reconstruction.metadata.get("task_id")
                if task_id:
                    job.tripo_task_id = str(task_id)
                    self._store.update_job_tripo_task(job.id, job.tripo_task_id)

                relative_model_path = self._relative_to_storage(reconstruction.model_path)
                job.model_path = relative_model_path
                self._store.update_job_model_path(job.id, relative_model_path)
                model_artifact = ArtifactRecord(
                    id=f"art_model_glb_{uuid4().hex[:12]}",
                    project_id=project.id,
                    job_id=job.id,
                    kind="model_glb",
                    filename="model.glb",
                    content_type="model/gltf-binary",
                    size_bytes=reconstruction.model_path.stat().st_size,
                    relative_path=relative_model_path,
                    created_at=_now(),
                )
                self._store.add_artifact(model_artifact)
                self._remember_artifact(project, model_artifact)

                self._update_stage(
                    job,
                    "reconstruct",
                    status="succeeded",
                    progress=100,
                    message="Tripo 重建完成，GLB 已保存",
                    finished_at=_now(),
                )

            assert model_artifact is not None
            active_stage = "voxelize"
            self._update_stage(
                job,
                "voxelize",
                status="running",
                progress=0,
                message="正在执行实心体素化和色卡匹配",
                started_at=_now(),
            )
            options = VoxelizationOptions.from_mapping(job.options)
            voxel_artifact, voxel_record = self._ensure_voxel_artifact(
                project,
                model_artifact,
                options,
                job_id=job.id,
            )
            self._remember_artifact(project, voxel_record)
            finished = _now()
            self._update_stage(
                job,
                "voxelize",
                status="succeeded",
                progress=100,
                message=f"体素化完成：{len(voxel_artifact.occupied)} 个实心体素",
                finished_at=finished,
            )
            job.status = "succeeded"
            job.error_code = None
            job.error_message = None
            job.error_details = {}
            job.updated_at = finished
            self._store.update_job_status(job.id, status=job.status, updated_at=finished)
            project.status = "ready"
            project.updated_at = finished
            self._store.update_project_status(project.id, project.status, updated_at=finished)
            return self._to_job_response(job)
        except (TripoError, NormalizationError, TextureSamplingError, VoxelArtifactError, AppError) as exc:
            logger.warning("Job %s failed at %s: %s", job.id, active_stage, exc)
            details = getattr(exc, "details", None)
            if not isinstance(details, dict):
                details = {"project_id": project.id}
            return self._fail_job(
                job,
                project,
                stage_id=active_stage,
                code=exc.code,
                message=str(exc),
                details=details,
            )
        except Exception as exc:
            logger.exception("Unexpected job failure: %s", job.id)
            fallback_code = {
                "ingest": "INGEST_FAILED",
                "reconstruct": "RECONSTRUCTION_FAILED",
                "voxelize": "VOXELIZATION_FAILED",
            }.get(active_stage, "JOB_FAILED")
            return self._fail_job(
                job,
                project,
                stage_id=active_stage,
                code=fallback_code,
                message=str(exc) or "重建失败",
            )

    def list_artifacts(self, project_id: str) -> list[ArtifactResponse]:
        self._get_record(project_id)
        return [self._to_artifact_response(artifact) for artifact in self._store.list_artifacts(project_id)]

    def get_artifact_path(self, project_id: str, artifact_id: str) -> tuple[ArtifactRecord, Path]:
        self._get_record(project_id)
        artifact = self._store.get_artifact(project_id, artifact_id)
        if artifact is None:
            raise NotFoundError(f"产物不存在：{artifact_id}")
        path = self._storage.path_for(artifact.relative_path)
        if not path.is_file():
            raise NotFoundError(f"产物文件不存在：{artifact_id}")
        return artifact, path

    def get_voxel_preview(
        self,
        project_id: str,
        *,
        z: int | None = None,
        target_height_mm: float = 80.0,
        source_up_axis: UpAxis | str = UpAxis.Y,
        delta_e_tolerance: float = 6.0,
    ) -> VoxelPreviewResponse:
        """Return one deterministic coloured voxel slice from the cached artifact."""
        project = self._get_record(project_id)
        try:
            options = VoxelizationOptions.from_mapping(
                {
                    "target_height_mm": target_height_mm,
                    "source_up_axis": source_up_axis,
                    "delta_e_tolerance": delta_e_tolerance,
                }
            )
        except VoxelArtifactError as exc:
            raise InvalidInputError(
                str(exc),
                code=exc.code,
                details={
                    "target_height_mm": target_height_mm,
                    "source_up_axis": str(source_up_axis),
                    "delta_e_tolerance": delta_e_tolerance,
                },
            ) from exc

        model_artifact = self._latest_model_artifact(project.id)
        if model_artifact is None:
            raise NotFoundError(
                "项目还没有可预览的 GLB 模型，请先完成 Tripo 重建",
                code="MODEL_ARTIFACT_NOT_FOUND",
            )
        if self._existing_artifact_path(model_artifact) is None:
            raise NotFoundError(
                "GLB 模型文件不存在，请重新运行重建",
                code="MODEL_ARTIFACT_MISSING",
            )

        try:
            voxel_artifact, _ = self._ensure_voxel_artifact(
                project,
                model_artifact,
                options,
                job_id=None,
            )
        except (NormalizationError, TextureSamplingError, VoxelArtifactError) as exc:
            raise AppError(
                str(exc),
                code=getattr(exc, "code", "VOXEL_PREVIEW_FAILED"),
                details={"project_id": project.id, "artifact_id": model_artifact.id},
            ) from exc

        slice_count = voxel_artifact.grid_shape[2]
        if z is None:
            slice_index = slice_count // 2
        elif 0 <= z < slice_count:
            slice_index = z
        else:
            raise InvalidInputError(
                "切片索引超出范围",
                code="VOXEL_SLICE_OUT_OF_RANGE",
                details={"z": z, "slice_count": slice_count},
            )

        palette_by_id = dict(voxel_artifact.palette)
        color_counts: Counter[str] = Counter()
        cells: list[VoxelCellResponse] = []
        for x, y in sorted(
            (x, y)
            for x, y, voxel_z in voxel_artifact.occupied
            if voxel_z == slice_index
        ):
            color_id = voxel_artifact.color_by_voxel.get((x, y, slice_index), "uncolored")
            color_counts[color_id] += 1
            cells.append(
                VoxelCellResponse(
                    x=x,
                    y=y,
                    color=color_id,
                    hex=palette_by_id.get(color_id, "#999999"),
                )
            )

        return VoxelPreviewResponse(
            project_id=project.id,
            artifact_id=model_artifact.id,
            grid_shape=voxel_artifact.grid_shape,
            grid_extent_mm=voxel_artifact.grid_extent_mm,
            pitch_mm=voxel_artifact.pitch_mm,
            slice_index=slice_index,
            slice_count=slice_count,
            occupied_count=len(cells),
            color_counts=dict(sorted(color_counts.items())),
            palette={color_id: palette_by_id.get(color_id, "#999999") for color_id in sorted(color_counts)},
            cells=cells,
        )

    def _latest_model_artifact(self, project_id: str) -> ArtifactRecord | None:
        model_artifacts = [
            artifact
            for artifact in self._store.list_artifacts(project_id)
            if artifact.kind == "model_glb"
        ]
        return model_artifacts[-1] if model_artifacts else None

    def _existing_artifact_path(self, artifact: ArtifactRecord | None) -> Path | None:
        if artifact is None:
            return None
        path = self._storage.path_for(artifact.relative_path)
        return path if path.is_file() else None

    @staticmethod
    def _remember_artifact(project: ProjectRecord, artifact: ArtifactRecord) -> None:
        for index, existing in enumerate(project.artifacts):
            if existing.id == artifact.id:
                project.artifacts[index] = artifact
                return
        project.artifacts.append(artifact)

    def _ensure_voxel_artifact(
        self,
        project: ProjectRecord,
        model_artifact: ArtifactRecord,
        options: VoxelizationOptions,
        *,
        job_id: str | None,
    ) -> tuple[VoxelArtifact, ArtifactRecord]:
        model_path = self._existing_artifact_path(model_artifact)
        if model_path is None:
            raise NotFoundError(
                "GLB 模型文件不存在，请重新运行重建",
                code="MODEL_ARTIFACT_MISSING",
            )

        cache_key = voxel_cache_key(
            model_artifact_id=model_artifact.id,
            model_relative_path=model_artifact.relative_path,
            pitch_mm=project.bead_spec.pitch_mm,
            options=options,
        )
        artifact_id = voxel_artifact_id(cache_key)
        relative_path = f"projects/{project.id}/artifacts/voxel_{cache_key}.npz"
        artifact_path = self._storage.path_for(relative_path)
        cached_record = self._store.get_artifact(project.id, artifact_id)
        if cached_record is not None and artifact_path.is_file():
            try:
                cached_artifact = load_voxel_artifact(artifact_path)
            except VoxelArtifactError:
                logger.warning("Rebuilding unreadable voxel cache: %s", artifact_path, exc_info=True)
            else:
                if (
                    cached_artifact.source_model_artifact_id == model_artifact.id
                    and cached_artifact.options == options
                ):
                    return cached_artifact, cached_record
                logger.warning("Voxel cache key mismatch; rebuilding: %s", artifact_path)

        voxel_artifact = build_voxel_artifact(
            model_path=model_path,
            model_artifact_id=model_artifact.id,
            model_relative_path=model_artifact.relative_path,
            bead_spec=project.bead_spec,
            options=options,
        )
        save_voxel_artifact(artifact_path, voxel_artifact)
        record = ArtifactRecord(
            id=artifact_id,
            project_id=project.id,
            job_id=job_id,
            kind=VOXEL_ARTIFACT_KIND,
            filename=artifact_path.name,
            content_type=VOXEL_ARTIFACT_CONTENT_TYPE,
            size_bytes=artifact_path.stat().st_size,
            relative_path=relative_path,
            created_at=_now(),
        )
        self._store.upsert_artifact(record)
        return voxel_artifact, record

    def recover_interrupted_jobs(self) -> None:
        """Mark jobs left in-flight by a previous process as retryable failures."""
        self._store.mark_interrupted_jobs(updated_at=_now())

    def _fail_job(
        self,
        job: JobRecord,
        project: ProjectRecord,
        *,
        stage_id: str,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> JobResponse:
        now = _now()
        self._update_stage(
            job,
            stage_id,
            status="failed",
            progress=100,
            message=message,
            finished_at=now,
        )
        job.status = "failed"
        job.error_code = code
        job.error_message = message
        job.error_details = dict(details or {})
        job.updated_at = now
        self._store.update_job_status(
            job.id,
            status=job.status,
            updated_at=now,
            error_code=code,
            error_message=message,
            error_details=job.error_details,
        )
        project.status = "failed"
        project.updated_at = now
        self._store.update_project_status(project.id, project.status, updated_at=now)
        return self._to_job_response(job)

    def _update_stage(
        self,
        job: JobRecord,
        stage_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        for stage in job.stages:
            if stage.id != stage_id:
                continue
            if status is not None:
                stage.status = status
            if progress is not None:
                stage.progress = max(0, min(100, progress))
            if message is not None:
                stage.message = message
            if started_at is not None:
                stage.started_at = started_at
            if finished_at is not None:
                stage.finished_at = finished_at
            self._store.update_stage(
                job.id,
                stage_id,
                status=status,
                progress=progress,
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )
            return

    def _get_record(self, project_id: str) -> ProjectRecord:
        record = self._store.get_project(project_id)
        if record is None:
            raise NotFoundError(f"项目不存在：{project_id}")
        return record

    def _get_job_record(self, job_id: str) -> JobRecord:
        job = self._store.get_job(job_id)
        if job is None:
            raise NotFoundError(f"作业不存在：{job_id}")
        return job

    def _relative_to_storage(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self._storage.root).as_posix()
        except ValueError as exc:
            raise TripoError(
                "TRIPO_MODEL_PATH_INVALID",
                "Tripo 模型文件不在项目存储目录内",
            ) from exc

    @staticmethod
    def _default_tripo_client() -> TripoClient:
        return TripoHttpClient(
            settings.tripo_api_base_url,
            settings.tripo_api_key,
            model_version=settings.tripo_model_version,
            poll_interval_s=settings.tripo_poll_interval_s,
            task_timeout_s=settings.tripo_task_timeout_s,
            request_timeout_s=settings.tripo_request_timeout_s,
        )

    @staticmethod
    def _to_bead_spec(spec: BeadSpecIn) -> BeadSpec:
        return BeadSpec(
            size=BeadSize(spec.size),
            outer_diameter_mm=spec.outer_diameter_mm,
            pitch_mm=spec.pitch_mm,
            height_mm=spec.height_mm,
            hole_diameter_mm=spec.hole_diameter_mm,
            board_max_cells_x=spec.board_max_cells_x,
            board_max_cells_y=spec.board_max_cells_y,
        )

    @staticmethod
    def _to_response(record: ProjectRecord) -> ProjectResponse:
        return ProjectResponse(
            id=record.id,
            name=record.name,
            status=record.status,
            image_count=record.image_count,
            bead_spec=BeadSpecIn(
                size=record.bead_spec.size.value,
                outer_diameter_mm=record.bead_spec.outer_diameter_mm,
                pitch_mm=record.bead_spec.pitch_mm,
                height_mm=record.bead_spec.height_mm,
                hole_diameter_mm=record.bead_spec.hole_diameter_mm,
                board_max_cells_x=record.bead_spec.board_max_cells_x,
                board_max_cells_y=record.bead_spec.board_max_cells_y,
            ),
            route_policy=ROUTE_POLICY,
            created_at=record.created_at,
            updated_at=record.updated_at,
            images=[
                ImageResponse(
                    id=image.id,
                    filename=image.filename,
                    content_type=image.content_type,
                    size_bytes=image.size_bytes,
                    sha256=image.sha256,
                    view=image.view.value,
                    relative_path=image.relative_path,
                )
                for image in record.images
            ],
        )

    @staticmethod
    def _to_job_response(job: JobRecord) -> JobResponse:
        return JobResponse(
            id=job.id,
            project_id=job.project_id,
            status=job.status,
            stages=[
                StageProgress(
                    id=stage.id,
                    label=stage.label,
                    status=stage.status,
                    progress=stage.progress,
                    message=stage.message,
                )
                for stage in job.stages
            ],
            created_at=job.created_at,
            updated_at=job.updated_at,
            error=job.error_message,
            error_code=job.error_code,
            error_details=job.error_details,
        )

    @staticmethod
    def _to_artifact_response(artifact: ArtifactRecord) -> ArtifactResponse:
        return ArtifactResponse(
            id=artifact.id,
            kind=artifact.kind,
            filename=artifact.filename,
            content_type=artifact.content_type,
            size_bytes=artifact.size_bytes,
            download_url=f"/api/v1/projects/{artifact.project_id}/artifacts/{artifact.id}",
        )
