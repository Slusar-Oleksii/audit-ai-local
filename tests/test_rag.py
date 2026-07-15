import pytest

from audit_ai.catalog import Catalog
from audit_ai.rag import AuditService
from audit_ai.repository import Repository
from audit_ai.retrieval import RetrievalContext
from audit_ai.schemas import (
    AuditDraft,
    AuditFinding,
    AuditProfile,
    AuditRequest,
    Confidence,
    DocumentChunk,
    RetrievalHit,
    RetrievalPlan,
    Severity,
    SourceRef,
)


class FakeLLM:
    def structured(self, messages, response_model, temperature=0.0):
        if response_model is RetrievalPlan:
            return RetrievalPlan(
                profile=AuditProfile.financial,
                queries=["початковий запит", "розбіжності у сумах"],
            )
        if response_model is AuditDraft:
            return AuditDraft(
                executive_summary="Виявлено одну розбіжність.",
                scope="Наданий звіт.",
                methodology="Пошук релевантних фрагментів.",
                findings=[
                    AuditFinding(
                        title="Розбіжність сум",
                        category="Фінанси",
                        severity=Severity.high,
                        description="Два значення не збігаються.",
                        impact="Ризик неправильного рішення.",
                        recommendation="Звірити первинні записи.",
                        confidence=Confidence.high,
                        source_ids=["S1"],
                        evidence_quote="Сума у звіті 100, а у додатку 120.",
                    )
                ],
            )
        raise AssertionError(f"Неочікувана схема: {response_model}")


class FakeRetrieval:
    def search(self, project_id, queries, *, allowed_document_ids=None):
        document_id = next(iter(allowed_document_ids or {"doc-1"}))
        chunk = DocumentChunk(
            id="chunk-1",
            project_id=project_id,
            document_id=document_id,
            checksum="checksum",
            file_name="report.txt",
            file_type="txt",
            text="Сума у звіті 100, а у додатку 120.",
            chunk_index=0,
            line_start=1,
            line_end=1,
        )
        hit = RetrievalHit(chunk=chunk, rank=1, distance=0.1, fused_score=0.5)
        source = SourceRef(
            source_id="S1",
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            file_name=chunk.file_name,
            location=chunk.location(),
            score=0.5,
            excerpt=chunk.text,
            content=chunk.text,
            retrieval_methods=["bm25", "vector"],
        )
        return RetrievalContext(
            hits=[hit],
            sources=[source],
            context=f'<source id="S1">{chunk.text}</source>',
        )


def test_audit_service_saves_validated_markdown(settings, tmp_path):
    catalog = Catalog(settings)
    project = catalog.create_project("RAG тест")
    repository = Repository(settings)
    source = tmp_path / "report.txt"
    source.write_text("Сума у звіті 100, а у додатку 120.", encoding="utf-8")
    document_id = "8bc55d34-429a-4460-bb0a-70f69cbfbad9"
    stored = repository.store_document(project.id, document_id, source, source.name)
    from audit_ai.repository import file_checksum

    catalog.add_document(
        document_id=document_id,
        project_id=project.id,
        checksum=file_checksum(stored),
        original_name=stored.name,
        stored_path=stored,
        file_type="txt",
        size_bytes=stored.stat().st_size,
        chunk_count=1,
        index_signature=settings.index_signature,
        collection_name=settings.collection_name,
    )
    service = AuditService(
        settings,
        catalog=catalog,
        repository=repository,
        llm=FakeLLM(),
        retrieval=FakeRetrieval(),
    )
    report = service.run_audit(
        AuditRequest(project_id=project.id, query="Перевір суми", profile=AuditProfile.auto)
    )
    assert report.profile == AuditProfile.financial
    assert report.findings[0].source_ids == ["S1"]
    report_path = settings.projects_dir / project.id / "reports" / f"{report.report_id}.md"
    assert report_path.exists()
    assert "Розбіжність сум" in report_path.read_text(encoding="utf-8")
    structured_path = report_path.with_suffix(".json")
    manifest_path = report_path.with_suffix(".manifest.json")
    assert structured_path.exists()
    assert manifest_path.exists()
    restored = repository.load_report(project.id, report.report_id)
    assert restored.manifest is not None
    assert restored.manifest.retrieval_strategy == "hybrid_rrf_chroma_fts5"
    assert restored.manifest.documents[0].checksum == file_checksum(stored)
    assert restored.sources[0].content.startswith("Сума у звіті")
    history = catalog.list_reports(project.id)
    assert [item.id for item in history] == [report.report_id]
    assert history[0].manifest_path == manifest_path


def test_audit_rejects_failed_reindex_before_calling_llm(settings, tmp_path):
    class ExplodingLLM:
        called = False

        def structured(self, *args, **kwargs):
            self.called = True
            raise AssertionError("LLM не можна викликати для неготового індексу")

    catalog = Catalog(settings)
    project = catalog.create_project("Неготовий індекс")
    stored = tmp_path / "report.txt"
    stored.write_text("Дані", encoding="utf-8")
    catalog.add_document(
        document_id="doc-failed",
        project_id=project.id,
        checksum="checksum-failed",
        original_name=stored.name,
        stored_path=stored,
        file_type="txt",
        size_bytes=stored.stat().st_size,
        chunk_count=1,
        status="reindex_error",
        index_signature=settings.index_signature,
        collection_name=settings.collection_name,
    )
    llm = ExplodingLLM()
    service = AuditService(
        settings,
        catalog=catalog,
        repository=Repository(settings),
        llm=llm,
        retrieval=FakeRetrieval(),
    )

    with pytest.raises(ValueError, match="Індекс документів не готовий"):
        service.run_audit(
            AuditRequest(project_id=project.id, query="Перевір дані", profile=AuditProfile.auto)
        )
    assert llm.called is False


def test_audit_rejects_modified_original_before_calling_llm(settings, tmp_path):
    class ExplodingLLM:
        called = False

        def structured(self, *args, **kwargs):
            self.called = True
            raise AssertionError("LLM не можна викликати після зміни оригіналу")

    from audit_ai.repository import file_checksum

    catalog = Catalog(settings)
    repository = Repository(settings)
    project = catalog.create_project("Контроль цілісності")
    source = tmp_path / "source.txt"
    source.write_text("Початкові дані", encoding="utf-8")
    document_id = "57a6bbbf-293e-4baa-bc07-3b7759622c75"
    stored = repository.store_document(project.id, document_id, source, source.name)
    checksum = file_checksum(stored)
    catalog.add_document(
        document_id=document_id,
        project_id=project.id,
        checksum=checksum,
        original_name=source.name,
        stored_path=stored,
        file_type="txt",
        size_bytes=stored.stat().st_size,
        chunk_count=1,
        status="indexed",
        index_signature=settings.index_signature,
        collection_name=settings.collection_name,
    )
    stored.write_text("Змінені дані", encoding="utf-8")
    llm = ExplodingLLM()
    service = AuditService(
        settings,
        catalog=catalog,
        repository=repository,
        llm=llm,
        retrieval=FakeRetrieval(),
    )

    with pytest.raises(ValueError, match="Оригінали документів відсутні або змінені"):
        service.run_audit(
            AuditRequest(project_id=project.id, query="Перевір дані", profile=AuditProfile.auto)
        )
    assert llm.called is False
