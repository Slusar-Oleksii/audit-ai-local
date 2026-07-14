from __future__ import annotations

from pathlib import Path

import pytest

from audit_ai.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    value = Settings(
        data_dir=tmp_path / "data",
        chunk_size=400,
        chunk_overlap=50,
        code_chunk_lines=20,
        code_overlap_lines=5,
        embedding_batch_size=2,
        retrieval_per_query=3,
        retrieval_final_k=4,
    )
    value.ensure_directories()
    return value
