import os

import pytest

from audit_ai.schemas import DocumentChunk
from audit_ai.vector_store import VectorStore


pytestmark = [
    pytest.mark.chroma_native,
    pytest.mark.skipif(
        os.getenv("RUN_CHROMA_NATIVE_TESTS") != "1",
        reason="RUN_CHROMA_NATIVE_TESTS не задано",
    ),
]


def chunk(
    project_id: str,
    document_id: str,
    chunk_id: str,
    text: str,
    index_signature: str,
) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        project_id=project_id,
        document_id=document_id,
        checksum=f"checksum-{document_id}",
        file_name=f"{document_id}.txt",
        file_type="txt",
        index_signature=index_signature,
        text=text,
        chunk_index=0,
        line_start=1,
        line_end=1,
    )


def test_persistent_chroma_filters_projects_and_deletes(settings):
    store = VectorStore(settings)
    chunks = [
        chunk("project-a", "doc-a", "a1", "alpha evidence", settings.index_signature),
        chunk("project-b", "doc-b", "b1", "beta evidence", settings.index_signature),
    ]
    vector_a = [1.0] + [0.0] * 15
    vector_b = [0.0, 1.0] + [0.0] * 14
    store.upsert(chunks, [vector_a, vector_b])

    result_a = store.query("project-a", vector_a, n_results=5)
    result_b = store.query("project-b", vector_b, n_results=5)
    assert [hit.chunk.id for hit in result_a] == ["a1"]
    assert [hit.chunk.id for hit in result_b] == ["b1"]

    store.delete_document("project-a", "doc-a")
    assert store.query("project-a", vector_a, n_results=5) == []
    assert [hit.chunk.id for hit in store.query("project-b", vector_b, n_results=5)] == ["b1"]

    reopened = VectorStore(settings)
    assert [hit.chunk.id for hit in reopened.query("project-b", vector_b, n_results=5)] == ["b1"]
