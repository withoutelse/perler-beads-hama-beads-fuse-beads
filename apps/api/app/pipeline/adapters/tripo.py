from __future__ import annotations

import json
import mimetypes
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


class TripoError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class TripoNotConfiguredError(TripoError):
    pass


class TripoTaskFailedError(TripoError):
    pass


class TripoTimeoutError(TripoError):
    pass


@dataclass(frozen=True, slots=True)
class TripoImage:
    path: Path
    view: str = "unknown"


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TripoError("TRIPO_INVALID_JSON", "Tripo 返回了非法 JSON") from exc


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout_s: float = 120.0,
    ) -> HttpResponse:
        ...


class UrllibTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout_s: float = 120.0,
    ) -> HttpResponse:
        request = Request(url, data=body, headers=headers or {}, method=method)
        try:
            with urlopen(request, timeout=timeout_s) as response:
                return HttpResponse(
                    status_code=response.status,
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except HTTPError as exc:
            return HttpResponse(
                status_code=exc.code,
                body=exc.read(),
                headers=dict(exc.headers.items()) if exc.headers else {},
            )
        except URLError as exc:
            raise TripoError("TRIPO_NETWORK_ERROR", str(exc)) from exc


@dataclass(frozen=True, slots=True)
class TripoTask:
    task_id: str
    status: str
    progress: int
    model_url: str | None
    error: str | None
    raw: dict[str, Any]

    @property
    def is_terminal(self) -> bool:
        return self.status in {"success", "succeeded", "failed", "cancelled", "canceled"}

    @property
    def is_success(self) -> bool:
        return self.status == "success"


@dataclass(frozen=True, slots=True)
class TripoReconstruction:
    model_path: Path
    metadata: dict[str, object]


class TripoClient(Protocol):
    def reconstruct(
        self,
        images: tuple[TripoImage, ...],
        *,
        output_dir: Path,
        prompt: str | None = None,
    ) -> TripoReconstruction:
        ...


class TripoHttpClient:
    """Minimal Tripo OpenAPI client: upload -> multiview task -> poll -> GLB."""

    CANONICAL_VIEWS = ("front", "left", "back", "right", "top", "bottom")

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        transport: HttpTransport | None = None,
        model_version: str = "v2.5-20250123",
        poll_interval_s: float = 2.0,
        task_timeout_s: float = 600.0,
        request_timeout_s: float = 120.0,
    ) -> None:
        if not api_key:
            raise TripoNotConfiguredError(
                "TRIPO_NOT_CONFIGURED",
                "未配置 TRIPO_API_KEY，无法调用 Tripo",
            )
        if poll_interval_s < 0:
            raise ValueError("poll_interval_s must be non-negative")
        if task_timeout_s <= 0 or request_timeout_s <= 0:
            raise ValueError("timeouts must be positive")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.transport = transport or UrllibTransport()
        self.model_version = model_version
        self.poll_interval_s = poll_interval_s
        self.task_timeout_s = task_timeout_s
        self.request_timeout_s = request_timeout_s

    def reconstruct(
        self,
        images: tuple[TripoImage, ...],
        *,
        output_dir: Path,
        prompt: str | None = None,
    ) -> TripoReconstruction:
        if len(images) < 3:
            raise TripoError("TRIPO_NEEDS_MULTIVIEW", "Tripo 多视角重建至少需要 3 张图片")
        task_id = self.create_multiview_task(images, prompt=prompt)
        task = self.wait_for_task(task_id)
        if not task.is_success:
            raise TripoTaskFailedError(
                "TRIPO_RECONSTRUCTION_FAILED",
                task.error or f"Tripo 任务失败：{task.status}",
                details={"task_id": task_id, "status": task.status},
            )
        if not task.model_url:
            raise TripoError(
                "TRIPO_MODEL_URL_MISSING",
                "Tripo 任务成功但没有返回 GLB 地址",
                details={"task_id": task_id},
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        model_path = output_dir / "model.glb"
        self.download_file(task.model_url, model_path)
        return TripoReconstruction(
            model_path=model_path,
            metadata={
                "task_id": task_id,
                "status": task.status,
                "progress": task.progress,
                "model_version": self.model_version,
                "image_count": len(images),
            },
        )

    def create_multiview_task(
        self,
        images: tuple[TripoImage, ...],
        *,
        prompt: str | None = None,
    ) -> str:
        tokens = [self.upload_image(image.path) for image in images]
        payload: dict[str, Any] = {
            "type": "multiview_to_model",
            "file": self._build_multiview_file(images, tokens),
            "model_version": self.model_version,
        }
        if prompt:
            payload["prompt"] = prompt
        response = self._request_json("POST", "/task", json_body=payload)
        data = self._data(response)
        task_id = data.get("task_id") or data.get("id")
        if not task_id:
            raise TripoError(
                "TRIPO_TASK_ID_MISSING",
                "Tripo 创建任务成功但没有返回 task_id",
                details=response,
            )
        return str(task_id)

    def upload_image(self, image_path: Path) -> str:
        if not image_path.is_file():
            raise TripoError("TRIPO_IMAGE_NOT_FOUND", f"图片不存在：{image_path}")
        data = image_path.read_bytes()
        boundary = f"----pindou{uuid4().hex}"
        content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        filename = image_path.name.replace('"', "_")
        body = b"".join(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                data,
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        response = self._request_json(
            "POST",
            "/upload",
            body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        payload = self._data(response)
        file_payload = payload.get("file")
        token = (
            payload.get("file_token")
            or payload.get("token")
            or (file_payload.get("file_token") if isinstance(file_payload, dict) else None)
        )
        if not token:
            raise TripoError(
                "TRIPO_UPLOAD_TOKEN_MISSING",
                "Tripo 上传成功但没有返回 file_token",
                details=response,
            )
        return str(token)

    def get_task(self, task_id: str) -> TripoTask:
        response = self._request_json("GET", f"/task/{task_id}")
        data = self._data(response)
        status = str(data.get("status", "unknown")).lower()
        progress_raw = data.get("progress", 0)
        try:
            progress = int(progress_raw or 0)
        except (TypeError, ValueError):
            progress = 0
        output = data.get("output")
        if not isinstance(output, dict):
            output = {}
        model_url = (
            output.get("model")
            or output.get("model_url")
            or data.get("model_url")
            or data.get("model")
        )
        error = data.get("error") or data.get("message")
        return TripoTask(
            task_id=str(data.get("task_id") or task_id),
            status=status,
            progress=max(0, min(100, progress)),
            model_url=str(model_url) if model_url else None,
            error=str(error) if error else None,
            raw=data,
        )

    def wait_for_task(self, task_id: str) -> TripoTask:
        deadline = time.monotonic() + self.task_timeout_s
        while True:
            task = self.get_task(task_id)
            if task.is_terminal:
                return task
            if time.monotonic() >= deadline:
                raise TripoTimeoutError(
                    "TRIPO_TIMEOUT",
                    f"Tripo 任务超时：{task_id}",
                    details={"task_id": task_id, "last_status": task.status},
                )
            time.sleep(self.poll_interval_s)

    def download_file(self, url: str, destination: Path) -> Path:
        response = self.transport.request(
            "GET",
            url,
            headers={"Accept": "application/octet-stream"},
            timeout_s=self.request_timeout_s,
        )
        if response.status_code >= 400:
            raise TripoError(
                "TRIPO_DOWNLOAD_FAILED",
                f"下载 GLB 失败：HTTP {response.status_code}",
                status_code=response.status_code,
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.body)
        return destination

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif content_type:
            headers["Content-Type"] = content_type

        response = self.transport.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            body=body,
            timeout_s=self.request_timeout_s,
        )
        payload = response.json() if response.body else {}
        code = payload.get("code")
        if response.status_code >= 400 or code not in (None, 0, "0"):
            raise TripoError(
                "TRIPO_HTTP_ERROR",
                self._error_message(payload, response.status_code),
                status_code=response.status_code,
                details=payload,
            )
        return payload

    def _build_multiview_file(
        self,
        images: tuple[TripoImage, ...],
        tokens: list[str],
    ) -> dict[str, str]:
        mapping: dict[str, str] = {}
        used_views: set[str] = set()

        for image, token in zip(images, tokens):
            view = image.view.lower()
            if view in self.CANONICAL_VIEWS and view not in used_views:
                mapping[view] = token
                used_views.add(view)

        for index, (image, token) in enumerate(zip(images, tokens), start=1):
            view = image.view.lower()
            if view in mapping and mapping[view] == token:
                continue
            next_view = next(
                (candidate for candidate in self.CANONICAL_VIEWS if candidate not in used_views),
                None,
            )
            if next_view is None:
                next_view = f"view_{index}"
            mapping[next_view] = token
            used_views.add(next_view)

        if len(mapping) < 3:
            raise TripoError("TRIPO_NEEDS_MULTIVIEW", "Tripo 多视角重建至少需要 3 个视角")
        return mapping

    @staticmethod
    def _data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data", payload)
        return data if isinstance(data, dict) else payload

    @staticmethod
    def _error_message(payload: dict[str, Any], status_code: int) -> str:
        message = (
            payload.get("message")
            or payload.get("msg")
            or payload.get("error")
            or payload.get("detail")
        )
        return f"Tripo API 错误（HTTP {status_code}）：{message or 'unknown error'}"
