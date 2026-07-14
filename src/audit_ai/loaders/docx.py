from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from audit_ai.config import Settings
from audit_ai.schemas import TextUnit


def _validate_archive(path: Path, settings: Settings) -> None:
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            total_uncompressed = sum(info.file_size for info in infos)
            total_compressed = sum(info.compress_size for info in infos)
    except BadZipFile as exc:
        raise ValueError("DOCX пошкоджений або має неправильний формат") from exc

    limit = settings.max_docx_uncompressed_mb * 1024 * 1024
    if total_uncompressed > limit:
        raise ValueError(
            f"Розпакований DOCX перевищує ліміт {settings.max_docx_uncompressed_mb} МБ"
        )
    if total_uncompressed > 10 * 1024 * 1024 and total_uncompressed / max(total_compressed, 1) > 100:
        raise ValueError("DOCX має підозрілий коефіцієнт стиснення")


def _iter_blocks(document: DocumentObject):
    """Повертає абзаци й таблиці в тому порядку, в якому вони є у DOCX."""
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def load_docx(path: Path, settings: Settings) -> list[TextUnit]:
    _validate_archive(path, settings)
    document = Document(path)
    units: list[TextUnit] = []

    table_number = 0
    for block_number, block in enumerate(_iter_blocks(document), start=1):
        if isinstance(block, Paragraph):
            text = block.text.replace("\x00", "").strip()
            if text:
                units.append(
                    TextUnit(
                        text=text,
                        kind="text",
                        line_start=block_number,
                        line_end=block_number,
                    )
                )
            continue

        table_number += 1
        rows: list[str] = []
        for row in block.rows:
            cells = [" ".join(cell.text.replace("\x00", "").split()) for cell in row.cells]
            rows.append(" | ".join(cells))
        text = "\n".join(row for row in rows if row.strip(" |"))
        if text:
            units.append(
                TextUnit(
                    text=f"Таблиця {table_number}:\n{text}",
                    kind="table",
                    line_start=block_number,
                    line_end=block_number,
                )
            )
    extracted_chars = sum(len(unit.text) for unit in units)
    if extracted_chars > settings.max_extracted_chars:
        raise ValueError(
            f"Текст DOCX перевищує ліміт {settings.max_extracted_chars:,} символів"
        )
    if not units:
        raise ValueError("У DOCX не знайдено тексту або таблиць")
    return units
