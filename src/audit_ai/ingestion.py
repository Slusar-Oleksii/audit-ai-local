from __future__ import annotations

import tempfile
import uuid
import zipfile
from collections.abc import Sequence
from pathlib import Path

from audit_ai.catalog import Catalog
from audit_ai.chunking import build_chunks
from audit_ai.concurrency import project_lock
from audit_ai.config import Settings, get_settings
from audit_ai.embeddings import EmbeddingsClient
from audit_ai.loaders import SUPPORTED_EXTENSIONS, load_document
from audit_ai.repository import Repository, file_checksum, safe_filename
from audit_ai.schemas import DocumentChunk, IngestionItem, IngestionResult, ProjectRecord
from audit_ai.vector_store import VectorStore


def _validate_file_content(path: Path, extension: str) -> None:
    with path.open("rb") as handle:
        head = handle.read(65_536)
    if extension == ".pdf":
        if b"%PDF-" not in head[:1024]:
            raise ValueError("Файл має розширення PDF, але не містить PDF-сигнатури")
        return
    if extension == ".docx":
        if not zipfile.is_zipfile(path):
            raise ValueError("Файл має розширення DOCX, але не є ZIP/DOCX-контейнером")
        return
    allowed_controls = {9, 10, 12, 13}
    controls = sum(byte < 32 and byte not in allowed_controls for byte in head)
    if b"\x00" in head or (head and controls / len(head) > 0.02):
        raise ValueError("Текстовий файл схожий на двійковий і не буде індексований")


class IngestionService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        catalog: Catalog | None = None,
        repository: Repository | None = None,
        embeddings: EmbeddingsClient | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.catalog = catalog or Catalog(self.settings)
        self.repository = repository or Repository(self.settings)
        self.embeddings = embeddings
        self.vector_store = vector_store

    def _dependencies(self) -> tuple[EmbeddingsClient, VectorStore]:
        if self.embeddings is None:
            self.embeddings = EmbeddingsClient(self.settings)
        if self.vector_store is None:
            self.vector_store = VectorStore(self.settings)
        return self.embeddings, self.vector_store

    def _vector_store(self) -> VectorStore:
        if self.vector_store is None:
            self.vector_store = VectorStore(self.settings)
        return self.vector_store

    def create_project(self, name: str) -> ProjectRecord:
        project = self.catalog.create_project(name)
        try:
            self.repository.ensure_project(project.id)
        except Exception:
            try:
                self.repository.delete_project_files(project.id)
            except Exception:
                pass
            self.catalog.delete_project(project.id)
            raise
        return project

    def ingest_files(self, project_id: str, paths: Sequence[Path]) -> IngestionResult:
        result = IngestionResult(project_id=project_id)
        for path in paths:
            try:
                with project_lock(project_id):
                    if self.catalog.get_project(project_id) is None:
                        raise ValueError("Проєкт не існує або його вже видалено")
                    item = self._ingest_one(project_id, Path(path))
            except Exception as exc:
                item = IngestionItem(
                    file_name=Path(path).name,
                    status="error",
                    message=str(exc),
                )
            result.items.append(item)
        return result

    def ingest_uploads(self, project_id: str, uploads: Sequence[tuple[str, bytes]]) -> IngestionResult:
        total_bytes = sum(len(content) for _, content in uploads)
        if total_bytes > self.settings.max_total_upload_mb * 1024 * 1024:
            raise ValueError(
                f"Сумарний розмір файлів перевищує {self.settings.max_total_upload_mb} МБ"
            )
        with tempfile.TemporaryDirectory(prefix="audit-ai-upload-") as temp_dir:
            paths: list[Path] = []
            for index, (name, content) in enumerate(uploads):
                directory = Path(temp_dir) / f"{index:04d}"
                directory.mkdir()
                target = directory / safe_filename(name)
                target.write_bytes(content)
                paths.append(target)
            return self.ingest_files(project_id, paths)

    def _prepare_document(
        self,
        *,
        project_id: str,
        document_id: str,
        checksum: str,
        stored_path: Path,
        original_name: str,
        extension: str,
        embeddings: EmbeddingsClient,
        reset_ocr: bool = False,
    ) -> tuple[list[DocumentChunk], list[list[float]], bool]:
        ocr_path = self.repository.ocr_output_path(project_id, document_id)
        if reset_ocr:
            ocr_path.unlink(missing_ok=True)
        units, used_ocr = load_document(stored_path, self.settings, ocr_output=ocr_path)
        chunks = build_chunks(
            units,
            project_id=project_id,
            document_id=document_id,
            checksum=checksum,
            file_name=original_name,
            file_type=extension.lstrip("."),
            settings=self.settings,
        )
        if not chunks:
            raise ValueError("Документ не містить придатного для індексації тексту")
        if len(chunks) > self.settings.max_chunks_per_document:
            raise ValueError(
                f"Документ створює {len(chunks)} chunks; ліміт — "
                f"{self.settings.max_chunks_per_document}"
            )
        vectors = embeddings.embed_documents([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks):
            raise RuntimeError("Ollama повернула неповний набір embeddings")
        return chunks, vectors, used_ocr

    def _ingest_one(self, project_id: str, path: Path) -> IngestionItem:
        if not path.is_file():
            raise ValueError("Файл не знайдено")
        extension = path.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Тип {extension or '(без розширення)'} не підтримується")
        size = path.stat().st_size
        if size == 0:
            raise ValueError("Файл порожній")
        if size > self.settings.max_upload_mb * 1024 * 1024:
            raise ValueError(f"Файл перевищує ліміт {self.settings.max_upload_mb} МБ")
        _validate_file_content(path, extension)

        original_name = safe_filename(path.name)
        checksum = file_checksum(path)
        duplicate = self.catalog.find_document_by_checksum(project_id, checksum)
        if duplicate:
            is_current = (
                duplicate.index_signature == self.settings.index_signature
                and duplicate.collection_name == self.settings.collection_name
                and duplicate.status in {"indexed", "ocr_indexed"}
            )
            return IngestionItem(
                file_name=original_name,
                status="duplicate" if is_current else "needs_reindex",
                message=(
                    "Файл із таким вмістом уже проіндексований"
                    if is_current
                    else "Файл є в каталозі, але його індекс застарів; виконайте переіндексацію"
                ),
                document_id=duplicate.id,
                chunk_count=duplicate.chunk_count,
            )

        document_id = str(uuid.uuid4())
        stored_path: Path | None = None
        vector_store: VectorStore | None = None
        try:
            stored_path = self.repository.store_document(project_id, document_id, path, original_name)
            embeddings, vector_store = self._dependencies()
            chunks, vectors, used_ocr = self._prepare_document(
                project_id=project_id,
                document_id=document_id,
                checksum=checksum,
                stored_path=stored_path,
                original_name=original_name,
                extension=extension,
                embeddings=embeddings,
            )
            vector_store.upsert(chunks, vectors)
            self.catalog.add_document(
                document_id=document_id,
                project_id=project_id,
                checksum=checksum,
                original_name=original_name,
                stored_path=stored_path,
                file_type=extension.lstrip("."),
                size_bytes=size,
                chunk_count=len(chunks),
                status="ocr_indexed" if used_ocr else "indexed",
                index_signature=self.settings.index_signature,
                collection_name=self.settings.collection_name,
            )
            return IngestionItem(
                file_name=original_name,
                status="indexed",
                message="OCR виконано та проіндексовано" if used_ocr else "Проіндексовано",
                document_id=document_id,
                chunk_count=len(chunks),
            )
        except Exception as original_error:
            rollback_errors: list[str] = []
            if vector_store is not None:
                try:
                    vector_store.delete_document(project_id, document_id)
                except Exception as exc:
                    rollback_errors.append(f"вектори: {exc}")
            if stored_path is not None:
                try:
                    self.repository.delete_document_files(project_id, document_id)
                except Exception as exc:
                    rollback_errors.append(f"файли: {exc}")
            if rollback_errors:
                raise RuntimeError(
                    f"{original_error}. Неповний rollback ({'; '.join(rollback_errors)})"
                ) from original_error
            raise

    def reindex_project(self, project_id: str) -> IngestionResult:
        result = IngestionResult(project_id=project_id)
        with project_lock(project_id):
            if self.catalog.get_project(project_id) is None:
                raise ValueError("Проєкт не існує або його вже видалено")
            documents = self.catalog.list_documents(project_id)
            if not documents:
                return result
            embeddings, vector_store = self._dependencies()
            for record in documents:
                extension = f".{record.file_type.lower().lstrip('.')}"
                try:
                    self.catalog.update_document_status(record.id, "reindexing")
                    stored_path = self.repository.validate_document_path(
                        project_id, record.id, record.stored_path
                    )
                    if not stored_path.is_file():
                        raise FileNotFoundError("Оригінал документа відсутній у локальному сховищі")
                    if file_checksum(stored_path) != record.checksum:
                        raise ValueError("Контрольна сума оригіналу змінилася після індексації")
                    _validate_file_content(stored_path, extension)
                    chunks, vectors, used_ocr = self._prepare_document(
                        project_id=project_id,
                        document_id=record.id,
                        checksum=record.checksum,
                        stored_path=stored_path,
                        original_name=record.original_name,
                        extension=extension,
                        embeddings=embeddings,
                        reset_ocr=True,
                    )
                    old_collection = record.collection_name or self.settings.collection_name
                    if old_collection == self.settings.collection_name:
                        vector_store.delete_document(project_id, record.id)
                        vector_store.upsert(chunks, vectors)
                    else:
                        vector_store.upsert(chunks, vectors)
                        if hasattr(vector_store, "delete_document_from_collection"):
                            vector_store.delete_document_from_collection(
                                old_collection, project_id, record.id
                            )
                    self.catalog.update_document_index(
                        record.id,
                        chunk_count=len(chunks),
                        status="ocr_indexed" if used_ocr else "indexed",
                        index_signature=self.settings.index_signature,
                        collection_name=self.settings.collection_name,
                    )
                    result.items.append(
                        IngestionItem(
                            file_name=record.original_name,
                            status="indexed",
                            message="Переіндексовано",
                            document_id=record.id,
                            chunk_count=len(chunks),
                        )
                    )
                except Exception as exc:
                    try:
                        self.catalog.update_document_status(record.id, "reindex_error")
                    except Exception:
                        pass
                    result.items.append(
                        IngestionItem(
                            file_name=record.original_name,
                            status="error",
                            message=str(exc),
                            document_id=record.id,
                        )
                    )
        return result

    def delete_document(self, project_id: str, document_id: str) -> None:
        with project_lock(project_id):
            record = self.catalog.get_document(document_id)
            if record is None or record.project_id != project_id:
                raise ValueError("Документ не знайдено в цьому проєкті")
            vector_store = self._vector_store()
            collection_name = record.collection_name or self.settings.collection_name
            if hasattr(vector_store, "delete_document_from_collection"):
                vector_store.delete_document_from_collection(
                    collection_name, project_id, document_id
                )
                if collection_name != self.settings.collection_name:
                    vector_store.delete_document(project_id, document_id)
            else:
                vector_store.delete_document(project_id, document_id)
            self.repository.delete_document_files(project_id, document_id)
            self.catalog.delete_document(document_id)

    def delete_project(self, project_id: str) -> None:
        with project_lock(project_id):
            if self.catalog.get_project(project_id) is None:
                return
            documents = self.catalog.list_documents(project_id)
            vector_store = self._vector_store()
            collection_names = {
                record.collection_name or self.settings.collection_name
                for record in documents
            }
            collection_names.add(self.settings.collection_name)
            if hasattr(vector_store, "delete_project_from_collection"):
                for collection_name in collection_names:
                    vector_store.delete_project_from_collection(collection_name, project_id)
            else:
                vector_store.delete_project(project_id)
            self.repository.delete_project_files(project_id)
            self.catalog.delete_project(project_id)


def ingest_files(project_id: str, paths: Sequence[Path]) -> IngestionResult:
    return IngestionService().ingest_files(project_id, paths)


def delete_document(project_id: str, document_id: str) -> None:
    IngestionService().delete_document(project_id, document_id)
