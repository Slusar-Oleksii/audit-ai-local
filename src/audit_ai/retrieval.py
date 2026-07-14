from __future__ import annotations

import json
from dataclasses import dataclass

from audit_ai.config import Settings, get_settings
from audit_ai.embeddings import EmbeddingsClient
from audit_ai.schemas import RetrievalHit, SourceRef
from audit_ai.vector_store import VectorStore


@dataclass(frozen=True)
class RetrievalContext:
    hits: list[RetrievalHit]
    sources: list[SourceRef]
    context: str


class RetrievalService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        embeddings: EmbeddingsClient | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embeddings = embeddings or EmbeddingsClient(self.settings)
        self.vector_store = vector_store or VectorStore(self.settings)

    def search(
        self,
        project_id: str,
        queries: list[str],
        *,
        allowed_document_ids: set[str] | None = None,
    ) -> RetrievalContext:
        by_chunk: dict[str, RetrievalHit] = {}
        scores: dict[str, float] = {}
        for query in queries[:3]:
            vector = self.embeddings.embed_query(query)
            hits = self.vector_store.query(
                project_id,
                vector,
                n_results=(
                    min(50, self.settings.retrieval_per_query * 3)
                    if allowed_document_ids is not None
                    else self.settings.retrieval_per_query
                ),
            )
            for hit in hits:
                if (
                    allowed_document_ids is not None
                    and hit.chunk.document_id not in allowed_document_ids
                ):
                    continue
                scores[hit.chunk.id] = scores.get(hit.chunk.id, 0.0) + 1.0 / (60 + hit.rank)
                previous = by_chunk.get(hit.chunk.id)
                if previous is None or hit.distance < previous.distance:
                    by_chunk[hit.chunk.id] = hit

        ranked = sorted(by_chunk.values(), key=lambda hit: scores[hit.chunk.id], reverse=True)
        ranked = ranked[: self.settings.retrieval_final_k]
        sources: list[SourceRef] = []
        context_blocks: list[str] = []
        for index, hit in enumerate(ranked, start=1):
            hit.fused_score = scores[hit.chunk.id]
            source_id = f"S{index}"
            excerpt = " ".join(hit.chunk.text.split())[:360]
            source = SourceRef(
                source_id=source_id,
                chunk_id=hit.chunk.id,
                file_name=hit.chunk.file_name,
                location=hit.chunk.location(),
                score=hit.fused_score,
                excerpt=excerpt,
            )
            sources.append(source)
            context_blocks.append(
                json.dumps(
                    {
                        "source_id": source_id,
                        "file_name": hit.chunk.file_name,
                        "location": hit.chunk.location(),
                        "content": hit.chunk.text,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        return RetrievalContext(hits=ranked, sources=sources, context="\n".join(context_blocks))
