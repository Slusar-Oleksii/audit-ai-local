from pathlib import Path

from audit_ai.catalog import Catalog
from audit_ai.ingestion import IngestionService
from audit_ai.repository import Repository


class FakeEmbeddings:
    def embed_documents(self, texts):
        return [[float(len(text)), 1.0] for text in texts]


class FakeVectorStore:
    def __init__(self):
        self.chunks = {}

    def upsert(self, chunks, embeddings):
        for chunk, embedding in zip(chunks, embeddings):
            self.chunks[chunk.id] = (chunk, embedding)

    def delete_document(self, project_id, document_id):
        self.chunks = {
            key: value
            for key, value in self.chunks.items()
            if not (value[0].project_id == project_id and value[0].document_id == document_id)
        }

    def delete_project(self, project_id):
        self.chunks = {
            key: value for key, value in self.chunks.items() if value[0].project_id != project_id
        }


def make_service(settings):
    catalog = Catalog(settings)
    vector = FakeVectorStore()
    service = IngestionService(
        settings,
        catalog=catalog,
        repository=Repository(settings),
        embeddings=FakeEmbeddings(),
        vector_store=vector,
    )
    return service, catalog, vector


def test_ingestion_deduplicates_and_deletes(settings, tmp_path: Path):
    service, catalog, vector = make_service(settings)
    project = catalog.create_project("Тест")
    source = tmp_path / "notes.txt"
    source.write_text("Перший факт.\nДругий факт із розбіжністю.", encoding="utf-8")

    first = service.ingest_files(project.id, [source])
    assert first.items[0].status == "indexed"
    assert vector.chunks
    second = service.ingest_files(project.id, [source])
    assert second.items[0].status == "duplicate"

    document = catalog.list_documents(project.id)[0]
    service.delete_document(project.id, document.id)
    assert not catalog.list_documents(project.id)
    assert not vector.chunks


def test_unsupported_file_becomes_item_error(settings, tmp_path: Path):
    service, catalog, _ = make_service(settings)
    project = catalog.create_project("Тест")
    source = tmp_path / "archive.zip"
    source.write_bytes(b"not a zip")
    result = service.ingest_files(project.id, [source])
    assert result.items[0].status == "error"
    assert "не підтримується" in result.items[0].message


def test_binary_file_with_text_extension_is_rejected(settings, tmp_path: Path):
    service, catalog, vector = make_service(settings)
    project = catalog.create_project("Тест")
    source = tmp_path / "payload.txt"
    source.write_bytes(b"\x00\x01\x02binary")
    result = service.ingest_files(project.id, [source])
    assert result.items[0].status == "error"
    assert "двійковий" in result.items[0].message
    assert not catalog.list_documents(project.id)
    assert not vector.chunks


def test_stale_duplicate_requires_reindex_and_recovers(settings, tmp_path: Path):
    service, catalog, vector = make_service(settings)
    project = service.create_project("Переіндексація")
    source = tmp_path / "notes.txt"
    source.write_text("Факт для повторної індексації.", encoding="utf-8")

    assert service.ingest_files(project.id, [source]).items[0].status == "indexed"
    document = catalog.list_documents(project.id)[0]
    catalog.update_document_index(
        document.id,
        chunk_count=document.chunk_count,
        status="reindex_error",
        index_signature="old-index-signature",
        collection_name=settings.collection_name,
    )

    duplicate = service.ingest_files(project.id, [source]).items[0]
    assert duplicate.status == "needs_reindex"

    result = service.reindex_project(project.id)
    assert result.items[0].status == "indexed"
    recovered = catalog.get_document(document.id)
    assert recovered is not None
    assert recovered.status == "indexed"
    assert recovered.index_signature == settings.index_signature
    assert recovered.collection_name == settings.collection_name
    assert vector.chunks
    assert all(item[0].index_signature == settings.index_signature for item in vector.chunks.values())


def test_create_project_rolls_back_catalog_and_partial_directory(settings):
    class FailingRepository(Repository):
        def ensure_project(self, project_id: str):
            directory = self.project_dir(project_id)
            directory.mkdir(parents=True)
            raise OSError("simulated disk failure")

    catalog = Catalog(settings)
    service = IngestionService(
        settings,
        catalog=catalog,
        repository=FailingRepository(settings),
    )

    try:
        service.create_project("Не має залишитися")
    except OSError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Очікувалася помилка файлової системи")

    assert catalog.list_projects() == []
    assert list(settings.projects_dir.iterdir()) == []
