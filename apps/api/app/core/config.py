from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PinDou Studio"
    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = "sqlite:///./storage/pindou.db"
    storage_dir: Path = Path("./storage")
    tripo_api_base_url: str = "https://api.tripo3d.ai/v2/openapi"
    tripo_api_key: str | None = None
    tripo_model_version: str = "v2.5-20250123"
    tripo_poll_interval_s: float = 2.0
    tripo_task_timeout_s: float = 600.0
    tripo_request_timeout_s: float = 120.0
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def ensure_directories(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
