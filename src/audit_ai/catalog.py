from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from audit_ai.config import Settings, get_settings
from audit_ai.schemas import DocumentRecord, ProjectRecord


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Catalog:
    """Незалежний SQLite-каталог; внутрішню SQLite Chroma не чіпаємо."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()
        self.path = self.settings.catalog_path
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    index_signature TEXT NOT NULL DEFAULT '',
                    collection_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, checksum),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    query TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);
                CREATE INDEX IF NOT EXISTS idx_reports_project ON reports(project_id);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(documents)").fetchall()
            }
            if "index_signature" not in columns:
                connection.execute(
                    "ALTER TABLE documents ADD COLUMN index_signature TEXT NOT NULL DEFAULT ''"
                )
            if "collection_name" not in columns:
                connection.execute(
                    "ALTER TABLE documents ADD COLUMN collection_name TEXT NOT NULL "
                    "DEFAULT 'audit_chunks_qwen3_06b_v1'"
                )

    def create_project(self, name: str) -> ProjectRecord:
        cleaned = " ".join(name.split())
        if not cleaned:
            raise ValueError("Назва проєкту не може бути порожньою")
        record = ProjectRecord(id=str(uuid.uuid4()), name=cleaned[:120], created_at=datetime.now(UTC))
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO projects(id, name, created_at) VALUES (?, ?, ?)",
                (record.id, record.name, record.created_at.isoformat()),
            )
        return record

    def list_projects(self) -> list[ProjectRecord]:
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return [ProjectRecord(**dict(row)) for row in rows]

    def get_project(self, project_id: str) -> ProjectRecord | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return ProjectRecord(**dict(row)) if row else None

    def delete_project(self, project_id: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def find_document_by_checksum(self, project_id: str, checksum: str) -> DocumentRecord | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE project_id = ? AND checksum = ?",
                (project_id, checksum),
            ).fetchone()
        return self._document(row)

    def add_document(
        self,
        *,
        document_id: str,
        project_id: str,
        checksum: str,
        original_name: str,
        stored_path: Path,
        file_type: str,
        size_bytes: int,
        chunk_count: int,
        status: str = "indexed",
        index_signature: str = "",
        collection_name: str = "",
    ) -> DocumentRecord:
        created_at = _utc_now()
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO documents(
                    id, project_id, checksum, original_name, stored_path, file_type,
                    size_bytes, chunk_count, status, index_signature, collection_name, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    project_id,
                    checksum,
                    original_name,
                    str(stored_path),
                    file_type,
                    size_bytes,
                    chunk_count,
                    status,
                    index_signature,
                    collection_name,
                    created_at,
                ),
            )
        return self.get_document(document_id)  # type: ignore[return-value]

    def update_document_index(
        self,
        document_id: str,
        *,
        chunk_count: int,
        status: str,
        index_signature: str,
        collection_name: str,
    ) -> None:
        with self.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE documents
                SET chunk_count = ?, status = ?, index_signature = ?, collection_name = ?
                WHERE id = ?
                """,
                (chunk_count, status, index_signature, collection_name, document_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Документ не знайдено для оновлення індексу")

    def update_document_status(self, document_id: str, status: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE documents SET status = ? WHERE id = ?",
                (status, document_id),
            )

    def list_documents(self, project_id: str) -> list[DocumentRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM documents WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [self._document(row) for row in rows if row is not None]  # type: ignore[misc]

    def get_document(self, document_id: str) -> DocumentRecord | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return self._document(row)

    def delete_document(self, document_id: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    def add_report(self, report_id: str, project_id: str, profile: str, query: str, path: Path) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO reports(id, project_id, profile, query, stored_path, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, project_id, profile, query, str(path), _utc_now()),
            )

    @staticmethod
    def _document(row: sqlite3.Row | None) -> DocumentRecord | None:
        if row is None:
            return None
        data = dict(row)
        data["stored_path"] = Path(data["stored_path"])
        return DocumentRecord(**data)
