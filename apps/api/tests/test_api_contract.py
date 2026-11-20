import tempfile
import unittest
from pathlib import Path

import trimesh  # type: ignore[import-untyped]

from app.pipeline.adapters.storage import LocalArtifactStorage
from app.pipeline.adapters.tripo import TripoReconstruction

try:
    from fastapi.testclient import TestClient

    from app.api.deps import get_project_service
    from app.main import create_app
    from app.services.project_service import ProjectService
except ModuleNotFoundError:
    TestClient = None  # type: ignore[assignment]
    get_project_service = None  # type: ignore[assignment]
    create_app = None  # type: ignore[assignment]
    ProjectService = None  # type: ignore[assignment]


JPEG = b"\xff\xd8\xff\xe0" + b"api-contract" * 4


class FakeTripoClient:
    def reconstruct(self, images, *, output_dir: Path, prompt: str | None = None) -> TripoReconstruction:
        output_dir.mkdir(parents=True, exist_ok=True)
        model_path = output_dir / "model.glb"
        trimesh.creation.box(extents=(2.0, 4.0, 6.0)).export(model_path)
        return TripoReconstruction(model_path=model_path, metadata={"task_id": "task_contract"})


@unittest.skipUnless(TestClient is not None, "FastAPI/Pydantic 依赖未安装")
class ApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        assert ProjectService is not None
        assert create_app is not None
        assert get_project_service is not None
        self.service = ProjectService(
            storage=LocalArtifactStorage(Path(self.temp_dir.name)),
            tripo_client_factory=FakeTripoClient,
        )
        self.app = create_app(self.service)
        self.app.dependency_overrides[get_project_service] = lambda: self.service
        self.client = TestClient(self.app)

    def test_upload_compile_poll_and_download_contract(self) -> None:
        created = self.client.post(
            "/api/v1/projects",
            json={"name": "契约测试", "bead_spec": {"size": "5mm"}},
        )
        self.assertEqual(created.status_code, 201)
        project_id = created.json()["id"]

        files = [
            ("files", (f"view-{index}.jpg", JPEG + bytes([index]), "image/jpeg"))
            for index in range(3)
        ]
        uploaded = self.client.post(
            f"/api/v1/projects/{project_id}/images",
            files=files,
            data={"view": "unknown"},
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.json()["image_count"], 3)

        compiled = self.client.post(
            f"/api/v1/projects/{project_id}/compile",
            json={"route_policy": "shape_partitioned_double_sided_hole_glue_free"},
        )
        self.assertEqual(compiled.status_code, 202)
        job_id = compiled.json()["id"]

        job = self.client.get(f"/api/v1/jobs/{job_id}")
        self.assertEqual(job.status_code, 200)
        self.assertEqual(job.json()["status"], "succeeded")
        stages = {stage["id"]: stage for stage in job.json()["stages"]}
        self.assertEqual(stages["ingest"]["status"], "succeeded")
        self.assertEqual(stages["reconstruct"]["status"], "succeeded")
        self.assertEqual(stages["voxelize"]["status"], "succeeded")

        artifacts = self.client.get(f"/api/v1/projects/{project_id}/artifacts")
        self.assertEqual(artifacts.status_code, 200)
        self.assertEqual(
            [artifact["kind"] for artifact in artifacts.json()],
            ["model_glb", "voxel_npz"],
        )
        self.assertEqual(artifacts.json()[0]["kind"], "model_glb")
        download_url = artifacts.json()[0]["download_url"]
        downloaded = self.client.get(download_url)
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.headers["content-type"], "model/gltf-binary")
        self.assertTrue(downloaded.content.startswith(b"glTF"))
        voxel_download = self.client.get(artifacts.json()[1]["download_url"])
        self.assertEqual(voxel_download.status_code, 200)
        self.assertEqual(voxel_download.headers["content-type"], "application/octet-stream")
        self.assertTrue(voxel_download.content.startswith(b"PK"))

    def test_voxel_preview_contract(self) -> None:
        created = self.client.post(
            "/api/v1/projects",
            json={"name": "体素预览契约", "bead_spec": {"size": "5mm"}},
        )
        project_id = created.json()["id"]
        files = [
            ("files", (f"view-{index}.jpg", JPEG + bytes([index]), "image/jpeg"))
            for index in range(3)
        ]
        self.client.post(
            f"/api/v1/projects/{project_id}/images",
            files=files,
            data={"view": "unknown"},
        )
        self.client.post(
            f"/api/v1/projects/{project_id}/compile",
            json={"route_policy": "shape_partitioned_double_sided_hole_glue_free"},
        )

        response = self.client.get(
            f"/api/v1/projects/{project_id}/voxel-preview",
            params={"z": 3, "target_height_mm": 30.0},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["grid_shape"], [3, 9, 6])
        self.assertEqual(payload["slice_index"], 3)
        self.assertEqual(payload["occupied_count"], 27)
        self.assertEqual(payload["color_counts"], {"charcoal": 27})
        self.assertEqual(len(payload["cells"]), 27)

    def test_voxel_preview_out_of_range_returns_stable_error(self) -> None:
        created = self.client.post(
            "/api/v1/projects",
            json={"name": "切片越界", "bead_spec": {"size": "5mm"}},
        )
        project_id = created.json()["id"]
        files = [
            ("files", (f"view-{index}.jpg", JPEG + bytes([index]), "image/jpeg"))
            for index in range(3)
        ]
        self.client.post(
            f"/api/v1/projects/{project_id}/images",
            files=files,
            data={"view": "unknown"},
        )
        self.client.post(
            f"/api/v1/projects/{project_id}/compile",
            json={"route_policy": "shape_partitioned_double_sided_hole_glue_free"},
        )

        response = self.client.get(
            f"/api/v1/projects/{project_id}/voxel-preview",
            params={"z": 6, "target_height_mm": 30.0},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VOXEL_SLICE_OUT_OF_RANGE")

    def test_duplicate_image_is_rejected_with_stable_error_code(self) -> None:
        created = self.client.post("/api/v1/projects", json={"name": "重复测试"})
        project_id = created.json()["id"]
        files = [
            ("files", ("front.jpg", JPEG, "image/jpeg")),
            ("files", ("back.jpg", JPEG, "image/jpeg")),
            ("files", ("left.jpg", JPEG + b"x", "image/jpeg")),
        ]
        uploaded = self.client.post(
            f"/api/v1/projects/{project_id}/images",
            files=files,
            data={"view": "unknown"},
        )
        self.assertEqual(uploaded.status_code, 400)
        self.assertEqual(uploaded.json()["error"]["code"], "DUPLICATE_IMAGE")

    def test_invalid_bead_spec_returns_validation_error(self) -> None:
        response = self.client.post(
            "/api/v1/projects",
            json={
                "name": "非法规格",
                "bead_spec": {
                    "outer_diameter_mm": 0,
                    "hole_diameter_mm": 2.2,
                },
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
