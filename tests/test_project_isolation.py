from pathlib import Path

from audit_ai.catalog import Catalog


def test_checksums_are_isolated_by_project(settings, tmp_path: Path):
    catalog = Catalog(settings)
    first = catalog.create_project("A")
    second = catalog.create_project("B")
    stored = tmp_path / "same.txt"
    stored.write_text("same", encoding="utf-8")
    for index, project in enumerate((first, second), start=1):
        catalog.add_document(
            document_id=f"doc-{index}",
            project_id=project.id,
            checksum="same-checksum",
            original_name="same.txt",
            stored_path=stored,
            file_type="txt",
            size_bytes=4,
            chunk_count=1,
        )
    assert catalog.find_document_by_checksum(first.id, "same-checksum").id == "doc-1"
    assert catalog.find_document_by_checksum(second.id, "same-checksum").id == "doc-2"
