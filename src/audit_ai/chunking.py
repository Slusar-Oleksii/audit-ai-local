from __future__ import annotations

import hashlib
from collections.abc import Iterable

from audit_ai.config import Settings
from audit_ai.schemas import DocumentChunk, TextUnit


def _chunk_id(project_id: str, checksum: str, index: int) -> str:
    value = f"{project_id}:{checksum}:{index}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _split_long_text_with_offsets(text: str, size: int, overlap: int) -> list[tuple[str, int, int]]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Некоректні параметри chunking: overlap має бути меншим за size")
    if len(text) <= size:
        return [(text, 0, len(text))]
    chunks: list[tuple[str, int, int]] = []
    start = 0
    while start < len(text):
        hard_end = min(start + size, len(text))
        end = hard_end
        if hard_end < len(text):
            candidates = [text.rfind(separator, start + size // 2, hard_end) for separator in ("\n\n", "\n", ". ", "; ")]
            best = max(candidates)
            if best > start:
                end = best + 1
        segment = text[start:end]
        leading = len(segment) - len(segment.lstrip())
        trailing = len(segment.rstrip())
        cleaned = segment.strip()
        if cleaned:
            chunks.append((cleaned, start + leading, start + trailing))
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _split_long_text(text: str, size: int, overlap: int) -> list[str]:
    return [chunk for chunk, _, _ in _split_long_text_with_offsets(text, size, overlap)]


def _group_units(units: Iterable[TextUnit], size: int) -> list[list[TextUnit]]:
    groups: list[list[TextUnit]] = []
    current: list[TextUnit] = []
    length = 0
    for unit in units:
        addition = len(unit.text) + (2 if current else 0)
        if current and length + addition > size:
            groups.append(current)
            current = []
            length = 0
        current.append(unit)
        length += len(unit.text) + (2 if len(current) > 1 else 0)
    if current:
        groups.append(current)
    return groups


def build_chunks(
    units: list[TextUnit],
    *,
    project_id: str,
    document_id: str,
    checksum: str,
    file_name: str,
    file_type: str,
    settings: Settings,
) -> list[DocumentChunk]:
    extension = f".{file_type.lower().lstrip('.')}"
    raw: list[tuple[str, dict[str, int | None]]] = []

    if units and all(unit.kind == "code" for unit in units):
        stride = max(1, settings.code_chunk_lines - settings.code_overlap_lines)
        for start in range(0, len(units), stride):
            group = units[start : start + settings.code_chunk_lines]
            if not group:
                continue
            raw.append(
                (
                    "\n".join(unit.text for unit in group),
                    {
                        "line_start": group[0].line_start,
                        "line_end": group[-1].line_end,
                        "page": None,
                        "row_start": None,
                        "row_end": None,
                    },
                )
            )
            if start + settings.code_chunk_lines >= len(units):
                break
    elif extension == ".csv" or (units and all(unit.kind == "csv" for unit in units)):
        for group in _group_units(units, settings.chunk_size):
            raw.append(
                (
                    "\n".join(unit.text for unit in group),
                    {
                        "row_start": group[0].row_start,
                        "row_end": group[-1].row_end,
                        "page": None,
                        "line_start": None,
                        "line_end": None,
                    },
                )
            )
    else:
        pages = sorted({unit.page for unit in units if unit.page is not None})
        buckets: list[list[TextUnit]]
        if pages:
            buckets = [[unit for unit in units if unit.page == page] for page in pages]
        else:
            buckets = _group_units(units, settings.chunk_size)

        for bucket in buckets:
            combined = "\n\n".join(unit.text for unit in bucket if unit.text.strip())
            for part in _split_long_text(combined, settings.chunk_size, settings.chunk_overlap):
                line_values = [unit.line_start for unit in bucket if unit.line_start is not None]
                line_ends = [unit.line_end for unit in bucket if unit.line_end is not None]
                raw.append(
                    (
                        part,
                        {
                            "page": bucket[0].page if bucket else None,
                            "line_start": min(line_values) if line_values else None,
                            "line_end": max(line_ends) if line_ends else None,
                            "row_start": None,
                            "row_end": None,
                        },
                    )
                )

    chunks: list[DocumentChunk] = []
    bounded: list[tuple[str, dict[str, int | None]]] = []
    for text, location in raw:
        for part, start_offset, end_offset in _split_long_text_with_offsets(
            text, settings.chunk_size, settings.chunk_overlap
        ):
            precise_location = dict(location)
            if location.get("line_start") is not None and "\n" in text:
                base_line = int(location["line_start"] or 1)
                precise_location["line_start"] = base_line + text[:start_offset].count("\n")
                precise_location["line_end"] = base_line + text[: max(start_offset, end_offset - 1)].count("\n")
            bounded.append((part, precise_location))

    for index, (text, location) in enumerate(bounded):
        if not text.strip():
            continue
        chunks.append(
            DocumentChunk(
                id=_chunk_id(project_id, checksum, index),
                project_id=project_id,
                document_id=document_id,
                checksum=checksum,
                file_name=file_name,
                file_type=file_type,
                index_signature=settings.index_signature,
                text=text.strip(),
                chunk_index=index,
                **location,
            )
        )
    return chunks
