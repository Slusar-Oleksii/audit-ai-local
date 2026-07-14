from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


LimitedText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class AuditProfile(str, Enum):
    auto = "auto"
    financial = "financial"
    legal = "legal"
    technical = "technical"
    universal = "universal"


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class EvidenceStatus(str, Enum):
    confirmed = "confirmed"
    hypothesis = "hypothesis"


class TextUnit(BaseModel):
    """Фрагмент документа до загального chunking."""

    text: str
    kind: str = "text"
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    row_start: int | None = None
    row_end: int | None = None


class DocumentChunk(BaseModel):
    id: str
    project_id: str
    document_id: str
    checksum: str
    file_name: str
    file_type: str
    index_signature: str = ""
    text: str
    chunk_index: int
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    row_start: int | None = None
    row_end: int | None = None

    def location(self) -> str:
        if self.page is not None:
            return f"стор. {self.page}"
        if self.line_start is not None:
            end = self.line_end or self.line_start
            return f"рядки {self.line_start}–{end}"
        if self.row_start is not None:
            end = self.row_end or self.row_start
            return f"CSV-рядки {self.row_start}–{end}"
        return f"фрагмент {self.chunk_index + 1}"


class ProjectRecord(BaseModel):
    id: str
    name: str
    created_at: datetime


class DocumentRecord(BaseModel):
    id: str
    project_id: str
    checksum: str
    original_name: str
    stored_path: Path
    file_type: str
    size_bytes: int
    chunk_count: int
    status: str
    index_signature: str = ""
    collection_name: str = ""
    created_at: datetime


class IngestionItem(BaseModel):
    file_name: str
    status: str
    message: str
    document_id: str | None = None
    chunk_count: int = 0


class IngestionResult(BaseModel):
    project_id: str
    items: list[IngestionItem] = Field(default_factory=list)

    @property
    def successful(self) -> int:
        return sum(item.status == "indexed" for item in self.items)


class AuditRequest(BaseModel):
    project_id: str = Field(min_length=1)
    query: str = Field(min_length=3, max_length=4000)
    profile: AuditProfile = AuditProfile.auto

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        return " ".join(value.split())


class RetrievalPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: AuditProfile
    queries: list[str] = Field(min_length=1, max_length=3)

    @field_validator("queries")
    @classmethod
    def unique_queries(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = " ".join(value.split())[:1000]
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                result.append(cleaned)
        if not result:
            raise ValueError("Пошуковий план не містить запитів")
        return result[:3]


class RetrievalHit(BaseModel):
    chunk: DocumentChunk
    rank: int
    distance: float
    fused_score: float = 0.0


class SourceRef(BaseModel):
    source_id: str
    chunk_id: str
    file_name: str
    location: str
    score: float
    excerpt: str


class AuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    category: str = Field(min_length=1, max_length=120)
    severity: Severity
    evidence_status: EvidenceStatus = EvidenceStatus.confirmed
    description: str = Field(min_length=1, max_length=4000)
    impact: str = Field(min_length=1, max_length=2000)
    recommendation: str = Field(min_length=1, max_length=2000)
    confidence: Confidence
    source_ids: list[str] = Field(default_factory=list, max_length=12)
    evidence_quote: str | None = Field(default=None, max_length=500)


class AuditDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: str = Field(min_length=1, max_length=6000)
    scope: str = Field(min_length=1, max_length=4000)
    methodology: str = Field(min_length=1, max_length=4000)
    findings: list[AuditFinding] = Field(default_factory=list, max_length=30)
    limitations: list[LimitedText] = Field(default_factory=list, max_length=20)


class AuditReport(AuditDraft):
    report_id: str
    project_id: str
    query: str
    profile: AuditProfile
    sources: list[SourceRef] = Field(default_factory=list)
    model: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
