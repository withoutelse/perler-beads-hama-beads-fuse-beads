from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.bead import BeadSize, BeadSpec
from app.domain.image import ImageView, StoredImage
from app.services.records import ArtifactRecord, JobRecord, ProjectRecord, StageRecord


class SqliteStore:
    """Small local-first persistence adapter for the single-user M1 workflow."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.db_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    bead_size TEXT NOT NULL,
                    outer_diameter_mm REAL NOT NULL,
                    pitch_mm REAL NOT NULL,
                    height_mm REAL NOT NULL,
                    hole_diameter_mm REAL NOT NULL,
                    board_max_cells_x INTEGER NOT NULL,
                    board_max_cells_y INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    view TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_images_project_id
                    ON images(project_id);

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    error_details_json TEXT NOT NULL DEFAULT '{}',
                    tripo_task_id TEXT,
                    model_path TEXT,
                    options_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_project_id
                    ON jobs(project_id, created_at);

                CREATE TABLE IF NOT EXISTS job_stages (
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    stage_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    PRIMARY KEY (job_id, stage_id)
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
                    kind TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    relative_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_artifacts_project_id
                    ON artifacts(project_id, created_at);
                """
            )

    def create_project(self, record: ProjectRecord) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    id, name, status, bead_size, outer_diameter_mm, pitch_mm,
                    height_mm, hole_diameter_mm, board_max_cells_x,
                    board_max_cells_y, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.name,
                    record.status,
                    record.bead_spec.size.value,
                    record.bead_spec.outer_diameter_mm,
                    record.bead_spec.pitch_mm,
                    record.bead_spec.height_mm,
                    record.bead_spec.hole_diameter_mm,
                    record.bead_spec.board_max_cells_x,
                    record.bead_spec.board_max_cells_y,
                    self._iso(record.created_at),
                    self._iso(record.updated_at),
                ),
            )

    def get_project(self, project_id: str) -> ProjectRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                return None
            image_rows = connection.execute(
                "SELECT * FROM images WHERE project_id = ? ORDER BY created_at, rowid",
                (project_id,),
            ).fetchall()
            artifact_rows = connection.execute(
                "SELECT * FROM artifacts WHERE project_id = ? ORDER BY created_at, rowid",
                (project_id,),
            ).fetchall()
        return self._project_from_rows(row, image_rows, artifact_rows)

    def add_images(
        self,
        project_id: str,
        images: Sequence[StoredImage],
        *,
        updated_at: datetime,
    ) -> None:
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT INTO images (
                    id, project_id, filename, content_type, size_bytes, sha256,
                    view, relative_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        image.id,
                        project_id,
                        image.filename,
                        image.content_type,
                        image.size_bytes,
                        image.sha256,
                        image.view.value,
                        image.relative_path,
                        self._iso(updated_at),
                    )
                    for image in images
                ],
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (self._iso(updated_at), project_id),
            )

    def update_project_status(
        self,
        project_id: str,
        status: str,
        *,
        updated_at: datetime,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                (status, self._iso(updated_at), project_id),
            )

    def create_job(self, record: JobRecord) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, project_id, status, error_code, error_message,
                    error_details_json, tripo_task_id, model_path, options_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.project_id,
                    record.status,
                    record.error_code,
                    record.error_message,
                    json.dumps(record.error_details, ensure_ascii=False),
                    record.tripo_task_id,
                    record.model_path,
                    json.dumps(record.options, ensure_ascii=False),
                    self._iso(record.created_at),
                    self._iso(record.updated_at),
                ),
            )
            connection.executemany(
                """
                INSERT INTO job_stages (
                    job_id, stage_id, position, label, status, progress,
                    message, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.id,
                        stage.id,
                        position,
                        stage.label,
                        stage.status,
                        stage.progress,
                        stage.message,
                        self._optional_iso(stage.started_at),
                        self._optional_iso(stage.finished_at),
                    )
                    for position, stage in enumerate(record.stages)
                ],
            )

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            stage_rows = connection.execute(
                "SELECT * FROM job_stages WHERE job_id = ? ORDER BY position",
                (job_id,),
            ).fetchall()
        return self._job_from_rows(row, stage_rows)

    def get_latest_job(self, project_id: str) -> JobRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE project_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            if row is None:
                return None
            stage_rows = connection.execute(
                "SELECT * FROM job_stages WHERE job_id = ? ORDER BY position",
                (row["id"],),
            ).fetchall()
        return self._job_from_rows(row, stage_rows)

    def update_job_status(
        self,
        job_id: str,
        *,
        status: str,
        updated_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, error_code = ?,
                    error_message = ?, error_details_json = ?
                WHERE id = ?
                """,
                (
                    status,
                    self._iso(updated_at),
                    error_code,
                    error_message,
                    json.dumps(error_details or {}, ensure_ascii=False),
                    job_id,
                ),
            )

    def update_job_tripo_task(self, job_id: str, task_id: str | None) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE jobs SET tripo_task_id = ? WHERE id = ?",
                (task_id, job_id),
            )

    def update_job_model_path(self, job_id: str, model_path: str | None) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE jobs SET model_path = ? WHERE id = ?",
                (model_path, job_id),
            )

    def update_stage(
        self,
        job_id: str,
        stage_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        assignments: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("status", status),
            ("progress", None if progress is None else max(0, min(100, progress))),
            ("message", message),
            ("started_at", self._optional_iso(started_at)),
            ("finished_at", self._optional_iso(finished_at)),
        ):
            if value is not None:
                assignments.append(f"{column} = ?")
                values.append(value)
        if not assignments:
            return
        values.extend([job_id, stage_id])
        with self._connection() as connection:
            connection.execute(
                f"UPDATE job_stages SET {', '.join(assignments)} WHERE job_id = ? AND stage_id = ?",
                values,
            )

    def add_artifact(self, record: ArtifactRecord) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO artifacts (
                    id, project_id, job_id, kind, filename, content_type,
                    size_bytes, relative_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.project_id,
                    record.job_id,
                    record.kind,
                    record.filename,
                    record.content_type,
                    record.size_bytes,
                    record.relative_path,
                    self._iso(record.created_at),
                ),
            )

    def upsert_artifact(self, record: ArtifactRecord) -> None:
        """Insert an artifact or refresh a deterministic cache record in place."""
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO artifacts (
                    id, project_id, job_id, kind, filename, content_type,
                    size_bytes, relative_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_id = excluded.project_id,
                    job_id = excluded.job_id,
                    kind = excluded.kind,
                    filename = excluded.filename,
                    content_type = excluded.content_type,
                    size_bytes = excluded.size_bytes,
                    relative_path = excluded.relative_path,
                    created_at = excluded.created_at
                """,
                (
                    record.id,
                    record.project_id,
                    record.job_id,
                    record.kind,
                    record.filename,
                    record.content_type,
                    record.size_bytes,
                    record.relative_path,
                    self._iso(record.created_at),
                ),
            )

    def get_artifact(self, project_id: str, artifact_id: str) -> ArtifactRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
                (artifact_id, project_id),
            ).fetchone()
        return self._artifact_from_row(row) if row is not None else None

    def list_artifacts(self, project_id: str) -> list[ArtifactRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE project_id = ? ORDER BY created_at, rowid",
                (project_id,),
            ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def mark_interrupted_jobs(self, *, updated_at: datetime) -> None:
        """Fail queued/running jobs left behind by a previous process."""
        with self._connection() as connection:
            project_rows = connection.execute(
                "SELECT DISTINCT project_id FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchall()
            job_rows = connection.execute(
                "SELECT id FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchall()
            job_ids = [str(row["id"]) for row in job_rows]
            if not job_ids:
                return
            placeholders = ",".join("?" for _ in job_ids)
            connection.execute(
                f"UPDATE job_stages SET status = 'failed', message = ? "
                f"WHERE job_id IN ({placeholders}) AND status = 'running'",
                ("服务重启，作业中断，可重试", *job_ids),
            )
            connection.execute(
                f"UPDATE job_stages SET status = 'pending' "
                f"WHERE job_id IN ({placeholders}) AND status = 'queued'",
                job_ids,
            )
            connection.execute(
                f"UPDATE jobs SET status = 'failed', error_code = 'JOB_INTERRUPTED', "
                f"error_message = ?, updated_at = ? WHERE id IN ({placeholders})",
                ("服务重启导致作业中断，请重试", self._iso(updated_at), *job_ids),
            )
            project_ids = [str(row["project_id"]) for row in project_rows]
            if project_ids:
                project_placeholders = ",".join("?" for _ in project_ids)
                connection.execute(
                    f"UPDATE projects SET status = 'failed', updated_at = ? "
                    f"WHERE id IN ({project_placeholders})",
                    (self._iso(updated_at), *project_ids),
                )

    def _project_from_rows(
        self,
        row: sqlite3.Row,
        image_rows: Sequence[sqlite3.Row],
        artifact_rows: Sequence[sqlite3.Row],
    ) -> ProjectRecord:
        return ProjectRecord(
            id=str(row["id"]),
            name=str(row["name"]),
            status=str(row["status"]),
            bead_spec=BeadSpec(
                size=BeadSize(str(row["bead_size"])),
                outer_diameter_mm=float(row["outer_diameter_mm"]),
                pitch_mm=float(row["pitch_mm"]),
                height_mm=float(row["height_mm"]),
                hole_diameter_mm=float(row["hole_diameter_mm"]),
                board_max_cells_x=int(row["board_max_cells_x"]),
                board_max_cells_y=int(row["board_max_cells_y"]),
            ),
            created_at=self._parse_datetime(str(row["created_at"])),
            updated_at=self._parse_datetime(str(row["updated_at"])),
            images=[
                StoredImage(
                    id=str(image["id"]),
                    filename=str(image["filename"]),
                    content_type=str(image["content_type"]),
                    size_bytes=int(image["size_bytes"]),
                    sha256=str(image["sha256"]),
                    view=ImageView(str(image["view"])),
                    relative_path=str(image["relative_path"]),
                )
                for image in image_rows
            ],
            artifacts=[self._artifact_from_row(artifact) for artifact in artifact_rows],
        )

    def _job_from_rows(
        self,
        row: sqlite3.Row,
        stage_rows: Sequence[sqlite3.Row],
    ) -> JobRecord:
        return JobRecord(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            status=str(row["status"]),
            error_code=str(row["error_code"]) if row["error_code"] else None,
            error_message=str(row["error_message"]) if row["error_message"] else None,
            error_details=self._json_dict(row["error_details_json"]),
            tripo_task_id=str(row["tripo_task_id"]) if row["tripo_task_id"] else None,
            model_path=str(row["model_path"]) if row["model_path"] else None,
            options=self._json_dict(row["options_json"]),
            created_at=self._parse_datetime(str(row["created_at"])),
            updated_at=self._parse_datetime(str(row["updated_at"])),
            stages=[
                StageRecord(
                    id=str(stage["stage_id"]),
                    label=str(stage["label"]),
                    status=str(stage["status"]),
                    progress=int(stage["progress"]),
                    message=str(stage["message"]) if stage["message"] else None,
                    started_at=(
                        self._parse_datetime(str(stage["started_at"]))
                        if stage["started_at"]
                        else None
                    ),
                    finished_at=(
                        self._parse_datetime(str(stage["finished_at"]))
                        if stage["finished_at"]
                        else None
                    ),
                )
                for stage in stage_rows
            ],
        )

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> ArtifactRecord:
        return ArtifactRecord(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            job_id=str(row["job_id"]) if row["job_id"] else None,
            kind=str(row["kind"]),
            filename=str(row["filename"]),
            content_type=str(row["content_type"]),
            size_bytes=int(row["size_bytes"]),
            relative_path=str(row["relative_path"]),
            created_at=SqliteStore._parse_datetime(str(row["created_at"])),
        )

    @staticmethod
    def _json_dict(value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.isoformat()

    @staticmethod
    def _optional_iso(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None
