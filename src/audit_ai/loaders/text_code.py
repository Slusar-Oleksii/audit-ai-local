from __future__ import annotations

from pathlib import Path

from charset_normalizer import from_bytes

from audit_ai.config import Settings
from audit_ai.schemas import TextUnit


CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".go",
    ".rs",
    ".php",
    ".rb",
    ".sql",
    ".html",
    ".css",
    ".scss",
    ".sh",
    ".bash",
    ".ps1",
}


def _decode(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1251")
    except UnicodeDecodeError:
        pass
    match = from_bytes(raw[: 1024 * 1024]).best()
    if match is None:
        raise ValueError("Не вдалося визначити кодування текстового файлу")
    try:
        return raw.decode(match.encoding)
    except (LookupError, UnicodeDecodeError) as exc:
        raise ValueError("Текстовий файл містить некоректне або змішане кодування") from exc


def load_text_or_code(
    path: Path,
    *,
    is_code: bool,
    settings: Settings | None = None,
) -> list[TextUnit]:
    text = _decode(path).replace("\x00", "")
    if not text.strip():
        raise ValueError("Текстовий файл порожній")
    if settings is not None and len(text) > settings.max_extracted_chars:
        raise ValueError(
            f"Текст перевищує ліміт {settings.max_extracted_chars:,} символів"
        )
    kind = "code" if is_code else "text"
    return [
        TextUnit(
            text=line.rstrip(),
            kind=kind,
            line_start=line_number,
            line_end=line_number,
        )
        for line_number, line in enumerate(text.splitlines(), start=1)
        if is_code or line.strip()
    ]
