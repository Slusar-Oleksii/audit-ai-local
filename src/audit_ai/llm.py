from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from audit_ai.config import Settings, get_settings


ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMClient:
    def __init__(self, settings: Settings | None = None, client: object | None = None) -> None:
        self.settings = settings or get_settings()
        if client is None:
            try:
                from ollama import Client
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("Пакет ollama не встановлений") from exc
            client = Client(host=self.settings.ollama_host, timeout=self.settings.llm_timeout_seconds)
        self.client = client

    def list_models(self) -> set[str]:
        response = self.client.list()  # type: ignore[attr-defined]
        models = getattr(response, "models", None)
        if models is None and isinstance(response, dict):
            models = response.get("models", [])
        names: set[str] = set()
        for item in models or []:
            name = getattr(item, "model", None) or getattr(item, "name", None)
            if name is None and isinstance(item, dict):
                name = item.get("model") or item.get("name")
            if name:
                names.add(str(name))
        return names

    def readiness(self) -> dict[str, bool | str]:
        try:
            models = self.list_models()
        except Exception as exc:
            return {
                "ollama": False,
                "llm": False,
                "embedding": False,
                "detail": str(exc),
            }

        def available(expected: str) -> bool:
            return expected in models or f"{expected}:latest" in models

        return {
            "ollama": True,
            "llm": available(self.settings.llm_model),
            "embedding": available(self.settings.embedding_model),
            "detail": ", ".join(sorted(models)) or "Моделі не завантажені",
        }

    @staticmethod
    def _content(response: object) -> str:
        message = getattr(response, "message", None)
        if message is not None:
            content = getattr(message, "content", None)
            if content is not None:
                return str(content)
        if isinstance(response, dict):
            return str((response.get("message") or {}).get("content") or "")
        raise RuntimeError("Ollama повернула неочікувану відповідь chat")

    def structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[ModelT],
        *,
        temperature: float = 0.0,
    ) -> ModelT:
        schema: dict[str, Any] = response_model.model_json_schema()
        kwargs: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "format": schema,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": self.settings.llm_context_size,
                "num_predict": self.settings.llm_max_output_tokens,
            },
        }
        try:
            response = self.client.chat(**kwargs, think=False)  # type: ignore[attr-defined]
        except TypeError as exc:  # сумісність зі старішими Python-клієнтами Ollama
            if "think" not in str(exc):
                raise
            response = self.client.chat(**kwargs)  # type: ignore[attr-defined]
        content = self._content(response)
        if not content.strip():
            raise RuntimeError("Ollama повернула порожню відповідь")
        return response_model.model_validate_json(content)
