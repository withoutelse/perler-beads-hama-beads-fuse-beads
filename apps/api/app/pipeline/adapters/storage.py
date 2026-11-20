from __future__ import annotations

import re
from pathlib import Path


class LocalArtifactStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError("artifact path escapes storage root")
        return path

    def write_bytes(self, relative_path: str, data: bytes) -> Path:
        path = self.path_for(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def project_root(self, project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
            raise ValueError("invalid project id")
        path = self.path_for(f"projects/{project_id}")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_original_image(
        self,
        project_id: str,
        *,
        image_id: str,
        filename: str,
        data: bytes,
    ) -> Path:
        relative_path = f"projects/{project_id}/images/{image_id}_{filename}"
        return self.write_bytes(relative_path, data)

    def model_dir(self, project_id: str) -> Path:
        path = self.project_root(project_id) / "model"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def artifact_dir(self, project_id: str) -> Path:
        path = self.project_root(project_id) / "artifacts"
        path.mkdir(parents=True, exist_ok=True)
        return path
