from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Конфігурація застосунку з безпечними локальними значеннями."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="AUDIT_",
        extra="ignore",
    )

    data_dir: Path = PROJECT_ROOT / "data"
    ollama_host: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3:8b"
    embedding_model: str = "qwen3-embedding:0.6b"
    collection_name: str = "audit_chunks_qwen3_06b_v2"
    ocr_languages: str = "ukr+eng"

    max_upload_mb: int = Field(default=100, ge=1, le=100)
    max_total_upload_mb: int = Field(default=250, ge=1, le=4096)
    max_pdf_pages: int = Field(default=500, ge=1, le=10000)
    max_docx_uncompressed_mb: int = Field(default=200, ge=10, le=2048)
    max_extracted_chars: int = Field(default=12_000_000, ge=100_000, le=100_000_000)
    max_csv_rows: int = Field(default=500_000, ge=1_000, le=5_000_000)
    max_csv_columns: int = Field(default=5_000, ge=1, le=50_000)
    max_chunks_per_document: int = Field(default=10_000, ge=100, le=100_000)
    chunk_size: int = Field(default=1800, ge=400, le=12000)
    chunk_overlap: int = Field(default=250, ge=0, le=4000)
    code_chunk_lines: int = Field(default=120, ge=20, le=1000)
    code_overlap_lines: int = Field(default=20, ge=0, le=500)
    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    vector_batch_size: int = Field(default=500, ge=1, le=5000)
    retrieval_per_query: int = Field(default=6, ge=1, le=50)
    retrieval_final_k: int = Field(default=12, ge=1, le=50)
    llm_context_size: int = Field(default=16384, ge=2048, le=131072)
    llm_max_output_tokens: int = Field(default=4096, ge=512, le=32768)
    llm_timeout_seconds: float = Field(default=600, ge=10, le=3600)

    @field_validator("data_dir", mode="before")
    @classmethod
    def resolve_data_dir(cls, value: object) -> Path:
        path = Path(str(value)).expanduser()
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @field_validator("ollama_host")
    @classmethod
    def local_ollama_only(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parsed = urlparse(normalized)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Некоректний порт Ollama") from exc
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or port is None
        ):
            raise ValueError("Ollama має працювати локально: localhost або 127.0.0.1")
        return normalized

    @model_validator(mode="after")
    def validate_relational_limits(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap має бути меншим за chunk_size")
        if self.code_overlap_lines >= self.code_chunk_lines:
            raise ValueError("code_overlap_lines має бути меншим за code_chunk_lines")
        if self.max_total_upload_mb < self.max_upload_mb:
            raise ValueError("max_total_upload_mb не може бути меншим за max_upload_mb")
        return self

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def catalog_path(self) -> Path:
        return self.data_dir / "catalog.sqlite3"

    @property
    def index_signature(self) -> str:
        payload = {
            "schema": "audit-index-v2",
            "collection": self.collection_name,
            "embedding_model": self.embedding_model,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "code_chunk_lines": self.code_chunk_lines,
            "code_overlap_lines": self.code_overlap_lines,
            "ocr_languages": self.ocr_languages,
        }
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
