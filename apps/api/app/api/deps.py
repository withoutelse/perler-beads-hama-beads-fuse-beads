from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.pipeline.adapters.sqlite import SqliteStore
from app.pipeline.adapters.storage import LocalArtifactStorage
from app.services.project_service import ProjectService


@lru_cache(maxsize=1)
def get_project_service() -> ProjectService:
    database_url = settings.database_url
    if not database_url.startswith("sqlite:///"):
        raise ValueError("当前本地版本只支持 sqlite:/// 数据库地址")
    database_path = Path(database_url.removeprefix("sqlite:///"))
    return ProjectService(
        storage=LocalArtifactStorage(settings.storage_dir),
        store=SqliteStore(database_path),
    )
