from __future__ import annotations

import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version

from audit_ai.config import Settings, get_settings
from audit_ai.schemas import DocumentChunk, RetrievalHit


def _metadata(chunk: DocumentChunk) -> dict[str, str | int]:
    values: dict[str, str | int | None] = {
        "project_id": chunk.project_id,
        "document_id": chunk.document_id,
        "checksum": chunk.checksum,
        "file_name": chunk.file_name,
        "file_type": chunk.file_type,
        "index_signature": chunk.index_signature,
        "chunk_index": chunk.chunk_index,
        "page": chunk.page,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "row_start": chunk.row_start,
        "row_end": chunk.row_end,
    }
    return {key: value for key, value in values.items() if value is not None}


class VectorStore:
    def __init__(self, settings: Settings | None = None, client: object | None = None) -> None:
        self.settings = settings or get_settings()
        if client is None:
            if sys.version_info[:2] != (3, 11):
                raise RuntimeError(
                    f"Chroma для цього MVP потребує Python 3.11; запущено {sys.version.split()[0]}"
                )
            try:
                chroma_version = version("chromadb")
            except PackageNotFoundError as exc:
                raise RuntimeError("Пакет chromadb не встановлений") from exc
            if chroma_version != "0.6.3":
                raise RuntimeError(
                    f"Несумісна версія chromadb {chroma_version}; потрібна 0.6.3"
                )
            try:
                import chromadb
                from chromadb.config import Settings as ChromaSettings
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("Пакет chromadb не встановлений") from exc
            client = chromadb.PersistentClient(
                path=str(self.settings.chroma_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        self.client = client
        self.collection = self.client.get_or_create_collection(  # type: ignore[attr-defined]
            name=self.settings.collection_name,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": self.settings.embedding_model,
                "index_schema": "audit-index-v2",
            },
            embedding_function=None,
        )
        metadata = getattr(self.collection, "metadata", None) or {}
        existing_model = metadata.get("embedding_model")
        if existing_model and existing_model != self.settings.embedding_model:
            raise RuntimeError(
                f"Колекція створена для {existing_model}; потрібна переіндексація для {self.settings.embedding_model}"
            )
        existing_schema = metadata.get("index_schema")
        if existing_schema and existing_schema != "audit-index-v2":
            raise RuntimeError(
                f"Колекція має несумісну схему {existing_schema}; використайте нову колекцію"
            )

    def upsert(self, chunks: Sequence[DocumentChunk], embeddings: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Кількість chunks і embeddings не збігається")
        if not chunks:
            return
        for start in range(0, len(chunks), self.settings.vector_batch_size):
            chunk_batch = chunks[start : start + self.settings.vector_batch_size]
            vector_batch = embeddings[start : start + self.settings.vector_batch_size]
            self.collection.upsert(
                ids=[chunk.id for chunk in chunk_batch],
                documents=[chunk.text for chunk in chunk_batch],
                metadatas=[_metadata(chunk) for chunk in chunk_batch],
                embeddings=[list(vector) for vector in vector_batch],
            )

    def query(self, project_id: str, embedding: Sequence[float], n_results: int) -> list[RetrievalHit]:
        result = self.collection.query(
            query_embeddings=[list(embedding)],
            n_results=n_results,
            where={
                "$and": [
                    {"project_id": project_id},
                    {"index_signature": self.settings.index_signature},
                ]
            },
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits: list[RetrievalHit] = []
        for rank, (chunk_id, text, metadata, distance) in enumerate(
            zip(ids, documents, metadatas, distances), start=1
        ):
            data = dict(metadata or {})
            chunk = DocumentChunk(id=chunk_id, text=text or "", **data)
            hits.append(RetrievalHit(chunk=chunk, rank=rank, distance=float(distance)))
        return hits

    def delete_document(self, project_id: str, document_id: str) -> None:
        self.collection.delete(
            where={"$and": [{"project_id": project_id}, {"document_id": document_id}]}
        )

    def delete_project(self, project_id: str) -> None:
        self.collection.delete(where={"project_id": project_id})

    def _named_collection(self, collection_name: str) -> object | None:
        if not collection_name or collection_name == self.settings.collection_name:
            return self.collection
        collections = self.client.list_collections()  # type: ignore[attr-defined]
        names = {
            item if isinstance(item, str) else str(getattr(item, "name", ""))
            for item in collections
        }
        if collection_name not in names:
            return None
        return self.client.get_collection(  # type: ignore[attr-defined]
            name=collection_name,
            embedding_function=None,
        )

    def delete_document_from_collection(
        self,
        collection_name: str,
        project_id: str,
        document_id: str,
    ) -> None:
        collection = self._named_collection(collection_name)
        if collection is not None:
            collection.delete(  # type: ignore[attr-defined]
                where={"$and": [{"project_id": project_id}, {"document_id": document_id}]}
            )

    def delete_project_from_collection(self, collection_name: str, project_id: str) -> None:
        collection = self._named_collection(collection_name)
        if collection is not None:
            collection.delete(where={"project_id": project_id})  # type: ignore[attr-defined]
