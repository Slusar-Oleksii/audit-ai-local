from __future__ import annotations

from pathlib import Path

from audit_ai.config import Settings
from audit_ai.loaders.csv_loader import load_csv
from audit_ai.loaders.docx import load_docx
from audit_ai.loaders.pdf import load_pdf
from audit_ai.loaders.text_code import CODE_EXTENSIONS, load_text_or_code
from audit_ai.schemas import TextUnit


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
}
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".csv"} | TEXT_EXTENSIONS | CODE_EXTENSIONS


def load_document(
    path: Path,
    settings: Settings,
    *,
    ocr_output: Path | None = None,
) -> tuple[list[TextUnit], bool]:
    extension = path.suffix.lower()
    if extension == ".pdf":
        return load_pdf(path, settings, ocr_output=ocr_output)
    if extension == ".docx":
        return load_docx(path, settings), False
    if extension == ".csv":
        return load_csv(path, settings), False
    if extension in TEXT_EXTENSIONS | CODE_EXTENSIONS:
        return load_text_or_code(path, is_code=extension in CODE_EXTENSIONS, settings=settings), False
    raise ValueError(f"Непідтримуваний тип файлу: {extension or '(без розширення)'}")
