from __future__ import annotations

import json
from dataclasses import dataclass

from audit_ai.config import Settings, get_settings
from audit_ai.embeddings import EmbeddingsClient
from audit_ai.lexical_store import LexicalStore
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
        lexical_store: LexicalStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embeddings = embeddings or EmbeddingsClient(self.settings)
        self.vector_store = vector_store or VectorStore(self.settings)
        self.lexical_store = lexical_store or LexicalStore(self.settings)

    def search(
        self,
        project_id: str,
        queries: list[str],
        *,
        allowed_document_ids: set[str] | None = None,
    ) -> RetrievalContext:
        by_chunk: dict[str, RetrievalHit] = {}
        scores: dict[str, float] = {}
        methods: dict[str, set[str]] = {}
        candidate_count = (
            min(50, self.settings.retrieval_per_query * 3)
            if allowed_document_ids is not None
            else self.settings.retrieval_per_query
        )

        def add_hits(hits: list[RetrievalHit], method: str) -> None:
            for hit in hits:
                if (
                    allowed_document_ids is not None
                    and hit.chunk.document_id not in allowed_document_ids
                ):
                    continue
                chunk_id = hit.chunk.id
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (60 + hit.rank)
                methods.setdefault(chunk_id, set()).add(method)
                previous = by_chunk.get(chunk_id)
                if previous is None or method == "vector":
                    by_chunk[chunk_id] = hit

        for query in queries[:3]:
            vector = self.embeddings.embed_query(query)
            vector_hits = self.vector_store.query(
                project_id,
                vector,
                n_results=candidate_count,
            )
            lexical_hits = self.lexical_store.query(project_id, query, candidate_count)
            add_hits(vector_hits, "vector")
            add_hits(lexical_hits, "bm25")

        ranked = sorted(
            by_chunk.values(),
            key=lambda hit: (-scores[hit.chunk.id], hit.chunk.id),
        )
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
                document_id=hit.chunk.document_id,
                file_name=hit.chunk.file_name,
                location=hit.chunk.location(),
                score=hit.fused_score,
                excerpt=excerpt,
                content=hit.chunk.text,
                retrieval_methods=sorted(methods.get(hit.chunk.id, set())),
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
