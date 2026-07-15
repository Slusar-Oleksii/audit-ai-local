from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from pypdf import PdfReader

from audit_ai.config import Settings
from audit_ai.schemas import TextUnit


def _extract_pages(path: Path, settings: Settings) -> tuple[list[TextUnit], bool]:
    reader = PdfReader(path, strict=False)
    if reader.is_encrypted:
        try:
            decrypted = reader.decrypt("")
        except Exception as exc:  # pragma: no cover - залежить від конкретного PDF
            raise ValueError("Зашифрований PDF неможливо прочитати без пароля") from exc
        if not decrypted:
            raise ValueError("Зашифрований PDF неможливо прочитати без пароля")
    if len(reader.pages) > settings.max_pdf_pages:
        raise ValueError(
            f"PDF містить {len(reader.pages)} сторінок; ліміт — {settings.max_pdf_pages}"
        )

    units: list[TextUnit] = []
    extracted_chars = 0
    extraction_failed = False
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").replace("\x00", "").strip()
        except Exception:
            text = ""
            extraction_failed = True
        units.append(TextUnit(text=text, kind="text", page=page_number))
        extracted_chars += len(text)
        if extracted_chars > settings.max_extracted_chars:
            raise ValueError(
                f"Текст PDF перевищує ліміт {settings.max_extracted_chars:,} символів"
            )
    return units, extraction_failed


def _needs_ocr(units: list[TextUnit]) -> bool:
    if not units:
        return False
    useful_pages = sum(len(unit.text.strip()) >= 40 for unit in units)
    total_chars = sum(len(unit.text.strip()) for unit in units)
    return useful_pages < max(1, round(len(units) * 0.4)) or total_chars < len(units) * 60


def _run_ocr(source: Path, output: Path, settings: Settings) -> None:
    executable = shutil.which("ocrmypdf")
    if executable is None:
        candidate = Path(sys.executable).resolve().parent / ("ocrmypdf.exe" if sys.platform == "win32" else "ocrmypdf")
        executable = str(candidate) if candidate.exists() else None
    if executable is None:
        raise RuntimeError(
            "PDF схожий на скан, але OCRmyPDF не знайдено. "
            "Встановіть ocrmypdf, Tesseract і Ghostscript."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        executable,
        "--skip-text",
        "--output-type",
        "pdf",
        "--language",
        settings.ocr_languages,
        str(source),
        str(output),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(120, int(settings.llm_timeout_seconds)),
        check=False,
        shell=False,
    )
    if completed.returncode not in {0, 6}:  # 6: файл уже має текст, залежно від версії
        detail = (completed.stderr or completed.stdout or "невідома помилка OCR").strip()
        raise RuntimeError(f"OCRmyPDF завершився з помилкою: {detail[-1200:]}")
    if not output.exists():
        raise RuntimeError("OCRmyPDF не створив вихідний PDF")


def load_pdf(
    path: Path,
    settings: Settings,
    *,
    ocr_output: Path | None = None,
) -> tuple[list[TextUnit], bool]:
    units, extraction_failed = _extract_pages(path, settings)
    if not extraction_failed and not _needs_ocr(units):
        return [unit for unit in units if unit.text.strip()], False
    if ocr_output is None:
        raise RuntimeError("Для сканованого PDF не задано безпечний шлях OCR-результату")
    _run_ocr(path, ocr_output, settings)
    ocr_units, ocr_extraction_failed = _extract_pages(ocr_output, settings)
    if ocr_extraction_failed:
        raise ValueError("Не вдалося надійно витягти текст з усіх сторінок PDF після OCR")
    useful = [unit for unit in ocr_units if unit.text.strip()]
    if not useful:
        raise ValueError("Після OCR у PDF не знайдено тексту")
    return useful, True
