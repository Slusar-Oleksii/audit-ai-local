import pytest
from pydantic import ValidationError

from audit_ai.config import Settings


@pytest.mark.parametrize(
    "host",
    [
        "https://127.0.0.1:11434",
        "http://example.com:11434",
        "http://127.0.0.1:11434/redirect",
        "http://user:pass@127.0.0.1:11434",
    ],
)
def test_ollama_host_rejects_non_local_or_ambiguous_urls(tmp_path, host):
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path, ollama_host=host)


def test_total_upload_limit_cannot_be_smaller_than_single_file_limit(tmp_path):
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path, max_upload_mb=100, max_total_upload_mb=50)


def test_single_upload_limit_matches_streamlit_hard_cap(tmp_path):
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path, max_upload_mb=101)
