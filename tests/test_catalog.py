import sqlite3
import uuid
from datetime import UTC, datetime

from audit_ai.catalog import Catalog


def test_project_and_document_lifecycle(settings, tmp_path):
    catalog = Catalog(settings)
    project = catalog.create_project("  Фінансовий   аудит  ")
    assert project.name == "Фінансовий аудит"
    assert catalog.get_project(project.id) is not None

    source = tmp_path / "stored.txt"
    source.write_text("дані", encoding="utf-8")
    document = catalog.add_document(
        document_id="doc-1",
        project_id=project.id,
        checksum="abc",
        original_name="report.txt",
        stored_path=source,
        file_type="txt",
        size_bytes=8,
        chunk_count=2,
    )
    assert document.chunk_count == 2
    assert catalog.find_document_by_checksum(project.id, "abc").id == "doc-1"

    catalog.delete_document("doc-1")
    assert catalog.get_document("doc-1") is None
    catalog.delete_project(project.id)
    assert catalog.get_project(project.id) is None


def test_empty_project_name_is_rejected(settings):
    catalog = Catalog(settings)
    try:
        catalog.create_project("   ")
    except ValueError as exc:
        assert "порожньою" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Очікувався ValueError")


def test_catalog_migrates_documents_from_previous_schema(settings, tmp_path):
    project_id = "b38bc2f8-c93d-41ea-a9fc-96de14ddd1dc"
    document_id = "c9274a7b-385c-44b5-86ef-929ea323fa7e"
    with sqlite3.connect(settings.catalog_path) as connection:
        connection.executescript(
            """
            CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                checksum TEXT NOT NULL,
                original_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                file_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, checksum)
            );
            """
        )
        now = datetime.now(UTC).isoformat()
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?)", (project_id, "Старий проєкт", now)
        )
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document_id,
                project_id,
                "checksum",
                "old.txt",
                str(tmp_path / "old.txt"),
                "txt",
                10,
                1,
                "indexed",
                now,
            ),
        )

    record = Catalog(settings).get_document(document_id)
    assert record is not None
    assert record.index_signature == ""
    assert record.collection_name == "audit_chunks_qwen3_06b_v1"


def test_report_history_is_project_isolated(settings, tmp_path):
    catalog = Catalog(settings)
    first = catalog.create_project("A")
    second = catalog.create_project("B")
    first_report = str(uuid.uuid4())
    second_report = str(uuid.uuid4())
    catalog.add_report(first_report, first.id, "technical", "Перевір код", tmp_path / "a.md")
    catalog.add_report(second_report, second.id, "legal", "Перевір договір", tmp_path / "b.md")

    assert [item.id for item in catalog.list_reports(first.id)] == [first_report]
    assert catalog.get_report(second_report).project_id == second.id
