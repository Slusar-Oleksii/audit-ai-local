import os

import pytest

from audit_ai.embeddings import EmbeddingsClient
from audit_ai.llm import LLMClient


pytestmark = pytest.mark.ollama


@pytest.mark.skipif(os.getenv("RUN_OLLAMA_TESTS") != "1", reason="RUN_OLLAMA_TESTS не задано")
def test_local_models_are_ready(settings):
    status = LLMClient(settings).readiness()
    assert status["ollama"]
    assert status["llm"]
    assert status["embedding"]
    vector = EmbeddingsClient(settings).embed_query("тестовий аудиторський запит")
    assert len(vector) > 10
