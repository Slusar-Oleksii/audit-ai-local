from __future__ import annotations

from collections.abc import Sequence

from audit_ai.config import Settings, get_settings


class EmbeddingsClient:
    def __init__(self, settings: Settings | None = None, client: object | None = None) -> None:
        self.settings = settings or get_settings()
        if client is None:
            try:
                from ollama import Client
            except ImportError as exc:  # pragma: no cover - залежить від середовища
                raise RuntimeError("Пакет ollama не встановлений") from exc
            client = Client(host=self.settings.ollama_host, timeout=self.settings.llm_timeout_seconds)
        self.client = client

    @staticmethod
    def _vectors(response: object) -> list[list[float]]:
        if hasattr(response, "embeddings"):
            return [list(vector) for vector in response.embeddings]  # type: ignore[attr-defined]
        if isinstance(response, dict) and "embeddings" in response:
            return [list(vector) for vector in response["embeddings"]]
        raise RuntimeError("Ollama повернула неочікувану відповідь embeddings")

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = self.client.embed(  # type: ignore[attr-defined]
            model=self.settings.embedding_model,
            input=list(texts),
            truncate=True,
        )
        return self._vectors(response)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.settings.embedding_batch_size):
            batch = texts[start : start + self.settings.embedding_batch_size]
            prepared = [f"Представ документ для пошуку аудиторських доказів:\n{text}" for text in batch]
            vectors.extend(self._embed(prepared))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        prepared = f"Представ запит для пошуку релевантних аудиторських доказів:\n{text}"
        vectors = self._embed([prepared])
        if not vectors:
            raise RuntimeError("Ollama не повернула embedding запиту")
        return vectors[0]
