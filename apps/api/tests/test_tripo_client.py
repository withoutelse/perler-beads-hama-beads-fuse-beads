import json
import tempfile
import unittest
from pathlib import Path

from app.pipeline.adapters.tripo import (
    HttpResponse,
    TripoHttpClient,
    TripoImage,
    TripoNotConfiguredError,
    TripoTaskFailedError,
)


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, str] | None, bytes | None]] = []
        self.task_polls = 0
        self.upload_count = 0

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout_s: float = 120.0,
    ) -> HttpResponse:
        self.requests.append((method, url, headers, body))
        if url.endswith("/upload"):
            self.upload_count += 1
            return HttpResponse(
                200,
                json.dumps(
                    {"code": 0, "data": {"file_token": f"token_{self.upload_count}"}}
                ).encode("utf-8"),
            )
        if method == "POST" and url.endswith("/task"):
            return HttpResponse(
                200,
                json.dumps({"code": 0, "data": {"task_id": "task_123"}}).encode("utf-8"),
            )
        if method == "GET" and "/task/" in url:
            self.task_polls += 1
            if self.task_polls < 2:
                return HttpResponse(
                    200,
                    json.dumps(
                        {
                            "code": 0,
                            "data": {"task_id": "task_123", "status": "running", "progress": 50},
                        }
                    ).encode("utf-8"),
                )
            return HttpResponse(
                200,
                json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "task_id": "task_123",
                            "status": "success",
                            "progress": 100,
                            "output": {"model": "https://cdn.example/model.glb"},
                        },
                    }
                ).encode("utf-8"),
            )
        if url == "https://cdn.example/model.glb":
            return HttpResponse(200, b"glb-bytes")
        raise AssertionError(f"unexpected request: {method} {url}")


class FailingTransport(FakeTransport):
    def request(self, method, url, *, headers=None, body=None, timeout_s=120.0):
        if method == "GET" and "/task/" in url:
            return HttpResponse(
                200,
                json.dumps(
                    {
                        "code": 0,
                        "data": {"task_id": "task_123", "status": "failed", "error": "bad input"},
                    }
                ).encode("utf-8"),
            )
        return super().request(method, url, headers=headers, body=body, timeout_s=timeout_s)


class TripoClientTests(unittest.TestCase):
    def test_reconstruct_uploads_polls_and_downloads_glb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = []
            for name, view in (("front.jpg", "front"), ("left.jpg", "left"), ("back.jpg", "back")):
                path = root / name
                path.write_bytes(b"image")
                images.append(TripoImage(path, view))

            transport = FakeTransport()
            client = TripoHttpClient(
                "https://api.example/v2/openapi",
                "test-key",
                transport=transport,
                poll_interval_s=0,
            )
            result = client.reconstruct(tuple(images), output_dir=root / "out")

            self.assertEqual(result.model_path.read_bytes(), b"glb-bytes")
            self.assertEqual(result.metadata["task_id"], "task_123")
            self.assertEqual(transport.upload_count, 3)

            task_request = next(
                request for request in transport.requests if request[0] == "POST" and request[1].endswith("/task")
            )
            payload = json.loads((task_request[3] or b"{}").decode("utf-8"))
            self.assertEqual(payload["type"], "multiview_to_model")
            self.assertEqual(payload["file"]["front"], "token_1")
            self.assertEqual(payload["file"]["left"], "token_2")
            self.assertEqual(payload["file"]["back"], "token_3")

    def test_missing_api_key_is_rejected(self) -> None:
        with self.assertRaises(TripoNotConfiguredError):
            TripoHttpClient("https://api.example/v2/openapi", "")

    def test_failed_task_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = []
            for name in ("front.jpg", "left.jpg", "back.jpg"):
                path = root / name
                path.write_bytes(b"image")
                images.append(TripoImage(path))
            client = TripoHttpClient(
                "https://api.example/v2/openapi",
                "test-key",
                transport=FailingTransport(),
                poll_interval_s=0,
            )
            with self.assertRaises(TripoTaskFailedError):
                client.reconstruct(tuple(images), output_dir=root / "out")


if __name__ == "__main__":
    unittest.main()
