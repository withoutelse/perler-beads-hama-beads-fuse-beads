import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from app.domain.bead import BeadSpec
from app.domain.image import ImageView, StoredImage
from app.pipeline.adapters.sqlite import SqliteStore
from app.services.records import ArtifactRecord, JobRecord, ProjectRecord, StageRecord


class SqliteStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = SqliteStore(Path(self.temp_dir.name) / "pindou.db")
        self.now = datetime.now(UTC)

    def make_project(self) -> ProjectRecord:
        project = ProjectRecord(
            id="prj_test",
            name="测试项目",
            bead_spec=BeadSpec.standard_5mm(),
            status="draft",
            created_at=self.now,
            updated_at=self.now,
        )
        self.store.create_project(project)
        return project

    def test_project_images_and_artifacts_round_trip(self) -> None:
        project = self.make_project()
        image = StoredImage(
            id="img_001",
            filename="front.jpg",
            content_type="image/jpeg",
            size_bytes=4,
            sha256="abc",
            view=ImageView.FRONT,
            relative_path="projects/prj_test/images/img_001_front.jpg",
        )
        self.store.add_images(project.id, [image], updated_at=self.now)
        artifact = ArtifactRecord(
            id="art_001",
            project_id=project.id,
            job_id=None,
            kind="model_glb",
            filename="model.glb",
            content_type="model/gltf-binary",
            size_bytes=9,
            relative_path="projects/prj_test/model/model.glb",
            created_at=self.now,
        )
        self.store.add_artifact(artifact)

        loaded = self.store.get_project(project.id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.image_count, 1)
        self.assertEqual(loaded.images[0].view, ImageView.FRONT)
        self.assertEqual(loaded.artifacts[0].kind, "model_glb")
        self.assertEqual(self.store.get_artifact(project.id, "art_001").filename, "model.glb")

    def test_job_stage_state_round_trip(self) -> None:
        project = self.make_project()
        job = JobRecord(
            id="job_001",
            project_id=project.id,
            status="queued",
            stages=[StageRecord("ingest", "输入校验"), StageRecord("reconstruct", "3D 重建")],
            created_at=self.now,
            updated_at=self.now,
            options={"target_height_mm": 80},
        )
        self.store.create_job(job)
        self.store.update_stage(
            job.id,
            "ingest",
            status="succeeded",
            progress=100,
            message="ok",
            finished_at=self.now,
        )
        self.store.update_job_status(job.id, status="running", updated_at=self.now)

        loaded = self.store.get_job(job.id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.status, "running")
        self.assertEqual(loaded.stages[0].status, "succeeded")
        self.assertEqual(loaded.stages[0].progress, 100)
        self.assertEqual(loaded.options["target_height_mm"], 80)

    def test_artifact_upsert_refreshes_deterministic_cache_record(self) -> None:
        project = self.make_project()
        job = JobRecord(
            id="job_001",
            project_id=project.id,
            status="running",
            stages=[StageRecord("voxelize", "实心体素化")],
            created_at=self.now,
            updated_at=self.now,
        )
        self.store.create_job(job)
        artifact = ArtifactRecord(
            id="art_voxel_npz_cache",
            project_id=project.id,
            job_id=None,
            kind="voxel_npz",
            filename="voxel.npz",
            content_type="application/octet-stream",
            size_bytes=10,
            relative_path="projects/prj_test/artifacts/voxel.npz",
            created_at=self.now,
        )
        self.store.upsert_artifact(artifact)
        refreshed = ArtifactRecord(
            id=artifact.id,
            project_id=project.id,
            job_id="job_001",
            kind="voxel_npz",
            filename="voxel.npz",
            content_type="application/octet-stream",
            size_bytes=20,
            relative_path="projects/prj_test/artifacts/voxel.npz",
            created_at=self.now,
        )
        self.store.upsert_artifact(refreshed)

        loaded = self.store.get_artifact(project.id, artifact.id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.job_id, "job_001")
        self.assertEqual(loaded.size_bytes, 20)
        self.assertEqual(len(self.store.list_artifacts(project.id)), 1)

    def test_interrupted_jobs_are_marked_retryable(self) -> None:
        project = self.make_project()
        job = JobRecord(
            id="job_interrupted",
            project_id=project.id,
            status="running",
            stages=[StageRecord("reconstruct", "3D 重建", status="running")],
            created_at=self.now,
            updated_at=self.now,
        )
        self.store.create_job(job)

        self.store.mark_interrupted_jobs(updated_at=self.now)

        loaded = self.store.get_job(job.id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.status, "failed")
        self.assertEqual(loaded.error_code, "JOB_INTERRUPTED")
        self.assertEqual(loaded.stages[0].status, "failed")
        self.assertEqual(self.store.get_project(project.id).status, "failed")


if __name__ == "__main__":
    unittest.main()
