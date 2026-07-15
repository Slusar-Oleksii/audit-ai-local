from audit_ai.lexical_store import LexicalStore
from audit_ai.schemas import DocumentChunk


def chunk(settings, *, chunk_id: str, project_id: str, document_id: str, text: str):
    return DocumentChunk(
        id=chunk_id,
        project_id=project_id,
        document_id=document_id,
        checksum=f"checksum-{document_id}",
        file_name=f"{document_id}.txt",
        file_type="txt",
        index_signature=settings.index_signature,
        text=text,
        chunk_index=0,
        line_start=1,
        line_end=3,
    )


def test_fts5_search_is_persistent_isolated_and_deletable(settings):
    store = LexicalStore(settings)
    store.upsert(
        [
            chunk(
                settings,
                chunk_id="a-1",
                project_id="project-a",
                document_id="doc-a",
                text="У договорі встановлено штраф 15000 гривень.",
            ),
            chunk(
                settings,
                chunk_id="b-1",
                project_id="project-b",
                document_id="doc-b",
                text="У договорі встановлено штраф 99000 гривень.",
            ),
        ]
    )

    reopened = LexicalStore(settings)
    hits = reopened.query("project-a", "штраф 15000", 5)
    assert [hit.chunk.id for hit in hits] == ["a-1"]
    assert all(hit.chunk.project_id == "project-a" for hit in hits)

    reopened.delete_document("project-a", "doc-a")
    assert reopened.query("project-a", "штраф", 5) == []
    assert reopened.query("project-b", "штраф", 5)


def test_fts5_ignores_empty_or_punctuation_only_query(settings):
    store = LexicalStore(settings)
    assert store.query("project", "--- !!!", 5) == []
