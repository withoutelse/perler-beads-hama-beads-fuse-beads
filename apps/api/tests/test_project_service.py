import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import trimesh  # type: ignore[import-untyped]

from app.core.errors import InvalidInputError, NotFoundError
from app.domain.image import ImageUpload, ImageView
from app.pipeline.adapters.storage import LocalArtifactStorage
from app.pipeline.adapters.tripo import TripoError, TripoReconstruction
from app.pipeline.normalization import NormalizationError
from app.pipeline.voxel_artifact import build_voxel_artifact, load_voxel_artifact

try:
    from app.schemas.project import CompileProjectRequest, CreateProjectRequest
    from app.services.project_service import ProjectService
except ModuleNotFoundError:
    CompileProjectRequest = None  # type: ignore[assignment]
    CreateProjectRequest = None  # type: ignore[assignment]
    ProjectService = None  # type: ignore[assignment]


JPEG = b"\xff\xd8\xff\xe0" + b"pindou" * 8


class FakeTripoClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def reconstruct(self, images, *, output_dir: Path, prompt: str | None = None) -> TripoReconstruction:
        if self.fail:
            raise TripoError("TRIPO_RECONSTRUCTION_FAILED", "模拟 Tripo 失败")
        output_dir.mkdir(parents=True, exist_ok=True)
        model_path = output_dir / "model.glb"
        trimesh.creation.box(extents=(2.0, 4.0, 6.0)).export(model_path)
        return TripoReconstruction(
            model_path=model_path,
            metadata={"task_id": "task_test", "image_count": len(images), "prompt": prompt},
        )


class RealGlbTripoClient:
    def reconstruct(self, images, *, output_dir: Path, prompt: str | None = None) -> TripoReconstruction:
        output_dir.mkdir(parents=True, exist_ok=True)
        model_path = output_dir / "model.glb"
        trimesh.creation.box(extents=(2.0, 4.0, 6.0)).export(model_path)
        return TripoReconstruction(
            model_path=model_path,
            metadata={"task_id": "task_preview", "image_count": len(images), "prompt": prompt},
        )


@unittest.skipUnless(ProjectService is not None, "FastAPI/Pydantic 依赖未安装")
class ProjectServiceTests(unittest.TestCase):
    def make_service(self, temp: str, *, fail: bool = False) -> ProjectService:
        return ProjectService(
            storage=LocalArtifactStorage(Path(temp)),
            tripo_client_factory=lambda: FakeTripoClient(fail=fail),
        )

    def add_images(self, service: ProjectService, project_id: str) -> None:
        uploads = tuple(
            ImageUpload(
                filename=f"view-{index}.jpg",
                content_type="image/jpeg",
                data=JPEG + bytes([index]),
                view=ImageView.UNKNOWN,
            )
            for index in range(3)
        )
        service.add_images(project_id, uploads)

    def test_compile_and_run_reconstruction_persists_glb_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(temp)
            project = service.create_project(CreateProjectRequest(name="测试圆罐"))
            self.add_images(service, project.id)
            job = service.compile_project(
                project.id,
                CompileProjectRequest(options={"target_height_mm": 30.0}),
            )

            result = service.run_job(job.id)

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(service.get_project(project.id).status, "ready")
            artifacts = service.list_artifacts(project.id)
            self.assertEqual([artifact.kind for artifact in artifacts], ["model_glb", "voxel_npz"])
            self.assertEqual(artifacts[0].kind, "model_glb")
            _, path = service.get_artifact_path(project.id, artifacts[0].id)
            self.assertTrue(path.read_bytes().startswith(b"glTF"))
            _, voxel_path = service.get_artifact_path(project.id, artifacts[1].id)
            voxel_artifact = load_voxel_artifact(voxel_path)
            self.assertEqual(voxel_artifact.grid_shape, (3, 9, 6))
            self.assertEqual(len(voxel_artifact.occupied), 162)
            self.assertEqual(voxel_artifact.color_counts(), {"charcoal": 162})
            voxel_stage = next(stage for stage in result.stages if stage.id == "voxelize")
            self.assertEqual(voxel_stage.status, "succeeded")

    def test_failed_job_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(temp)
            project = service.create_project(CreateProjectRequest(name="重试项目"))
            self.add_images(service, project.id)
            job = service.compile_project(project.id)

            failed = service.run_job(job.id, tripo_client=FakeTripoClient(fail=True))
            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.error_code, "TRIPO_RECONSTRUCTION_FAILED")

            retried = service.retry_job(job.id)
            self.assertEqual(retried.status, "queued")
            succeeded = service.run_job(retried.id, tripo_client=FakeTripoClient())
            self.assertEqual(succeeded.status, "succeeded")
            artifacts = service.list_artifacts(project.id)
            self.assertEqual([artifact.kind for artifact in artifacts], ["model_glb", "voxel_npz"])

    def test_voxel_preview_returns_real_colored_slice(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(temp)
            project = service.create_project(CreateProjectRequest(name="体素预览"))
            self.add_images(service, project.id)
            job = service.compile_project(project.id)
            self.assertEqual(
                service.run_job(job.id, tripo_client=RealGlbTripoClient()).status,
                "succeeded",
            )

            preview = service.get_voxel_preview(
                project.id,
                z=3,
                target_height_mm=30.0,
            )

            self.assertEqual(preview.grid_shape, (3, 9, 6))
            self.assertEqual(preview.grid_extent_mm, (15.0, 45.0, 30.0))
            self.assertEqual(preview.slice_index, 3)
            self.assertEqual(preview.slice_count, 6)
            self.assertEqual(preview.occupied_count, 27)
            self.assertEqual(preview.color_counts, {"charcoal": 27})
            self.assertEqual(preview.palette, {"charcoal": "#3b3b3b"})
            self.assertEqual(len(preview.cells), 27)

    def test_voxel_preview_defaults_to_middle_slice_and_validates_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(temp)
            project = service.create_project(CreateProjectRequest(name="切片范围"))
            self.add_images(service, project.id)
            job = service.compile_project(project.id)
            service.run_job(job.id, tripo_client=RealGlbTripoClient())

            preview = service.get_voxel_preview(project.id, target_height_mm=30.0)
            self.assertEqual(preview.slice_index, 3)

            with self.assertRaises(InvalidInputError) as out_of_range:
                service.get_voxel_preview(project.id, z=6, target_height_mm=30.0)
            self.assertEqual(out_of_range.exception.code, "VOXEL_SLICE_OUT_OF_RANGE")

    def test_voxel_preview_requires_model_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(temp)
            project = service.create_project(CreateProjectRequest(name="缺少模型"))

            with self.assertRaises(NotFoundError) as missing:
                service.get_voxel_preview(project.id)
            self.assertEqual(missing.exception.code, "MODEL_ARTIFACT_NOT_FOUND")

    def test_voxel_preview_uses_persisted_cache_without_recomputing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(temp)
            project = service.create_project(CreateProjectRequest(name="体素缓存"))
            self.add_images(service, project.id)
            job = service.compile_project(
                project.id,
                CompileProjectRequest(options={"target_height_mm": 30.0}),
            )
            self.assertEqual(service.run_job(job.id).status, "succeeded")

            with patch(
                "app.services.project_service.build_voxel_artifact",
                side_effect=AssertionError("预览不应重新计算体素"),
            ):
                preview = service.get_voxel_preview(
                    project.id,
                    z=3,
                    target_height_mm=30.0,
                )

            self.assertEqual(preview.occupied_count, 27)
            self.assertEqual(preview.color_counts, {"charcoal": 27})

    def test_voxelize_failure_is_retryable_without_recalling_tripo(self) -> None:
        class ExplodingTripoClient:
            def reconstruct(self, images, *, output_dir: Path, prompt: str | None = None) -> TripoReconstruction:
                del images, output_dir, prompt
                raise AssertionError("重试体素化不应再次调用 Tripo")

        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(temp)
            project = service.create_project(CreateProjectRequest(name="体素重试"))
            self.add_images(service, project.id)
            job = service.compile_project(project.id)

            original_build = build_voxel_artifact
            calls = {"count": 0}

            def flaky_build(**kwargs):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise NormalizationError("NORMALIZATION_NOT_WATERTIGHT", "模拟体素化失败")
                return original_build(**kwargs)

            with patch(
                "app.services.project_service.build_voxel_artifact",
                side_effect=flaky_build,
            ):
                failed = service.run_job(job.id)
                self.assertEqual(failed.status, "failed")
                self.assertEqual(failed.error_code, "NORMALIZATION_NOT_WATERTIGHT")
                failed_stage = next(stage for stage in failed.stages if stage.id == "voxelize")
                self.assertEqual(failed_stage.status, "failed")
                self.assertEqual(
                    [artifact.kind for artifact in service.list_artifacts(project.id)],
                    ["model_glb"],
                )

                retried = service.retry_job(job.id)
                succeeded = service.run_job(retried.id, tripo_client=ExplodingTripoClient())

            self.assertEqual(succeeded.status, "succeeded")
            self.assertEqual(
                [artifact.kind for artifact in service.list_artifacts(project.id)],
                ["model_glb", "voxel_npz"],
            )

    def test_invalid_voxel_options_return_stable_error_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(temp)
            project = service.create_project(CreateProjectRequest(name="非法体素参数"))
            self.add_images(service, project.id)

            with self.assertRaises(InvalidInputError) as invalid_height:
                service.compile_project(
                    project.id,
                    payload=CompileProjectRequest(options={"target_height_mm": 0}),
                )
            self.assertEqual(invalid_height.exception.code, "VOXEL_INVALID_TARGET_HEIGHT")

            with self.assertRaises(InvalidInputError) as invalid_tolerance:
                service.get_voxel_preview(project.id, delta_e_tolerance=-1.0)
            self.assertEqual(invalid_tolerance.exception.code, "VOXEL_INVALID_TOLERANCE")


if __name__ == "__main__":
    unittest.main()
