from audit_ai.retrieval import RetrievalService
from audit_ai.schemas import DocumentChunk, RetrievalHit


class FakeEmbeddings:
    def embed_query(self, text):
        return [float(len(text))]


class FakeStore:
    def __init__(self, hits_by_call):
        self.hits_by_call = list(hits_by_call)

    def query(self, project_id, embedding, n_results):
        return self.hits_by_call.pop(0)


def hit(chunk_id, rank, file_name="a.txt"):
    chunk = DocumentChunk(
        id=chunk_id,
        project_id="p",
        document_id="d",
        checksum="x",
        file_name=file_name,
        file_type="txt",
        text=f"Evidence {chunk_id}",
        chunk_index=rank,
        line_start=rank,
        line_end=rank,
    )
    return RetrievalHit(chunk=chunk, rank=rank, distance=rank / 10)


def test_rrf_deduplicates_and_prioritizes_repeated_hit(settings):
    store = FakeStore(
        [
            [hit("common", 2), hit("only-a", 1)],
            [hit("common", 1), hit("only-b", 2)],
        ]
    )
    service = RetrievalService(settings, embeddings=FakeEmbeddings(), vector_store=store)
    result = service.search("p", ["query one", "query two"])
    assert result.hits[0].chunk.id == "common"
    assert [source.source_id for source in result.sources] == ["S1", "S2", "S3"]
    assert '"source_id":"S1"' in result.context


def test_retrieval_rejects_stale_document_vectors(settings):
    store = FakeStore([[hit("stale", 1), hit("current", 2)]])
    store.hits_by_call[0][0].chunk.document_id = "deleted-document"
    store.hits_by_call[0][1].chunk.document_id = "current-document"
    service = RetrievalService(settings, embeddings=FakeEmbeddings(), vector_store=store)
    result = service.search(
        "p",
        ["query"],
        allowed_document_ids={"current-document"},
    )
    assert [item.chunk.id for item in result.hits] == ["current"]
    assert "stale" not in result.context
