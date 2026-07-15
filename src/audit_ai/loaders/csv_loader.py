from __future__ import annotations

import csv
import io
from pathlib import Path

from charset_normalizer import from_bytes

from audit_ai.config import Settings
from audit_ai.schemas import TextUnit


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
        raise ValueError("Не вдалося визначити кодування CSV")
    try:
        return raw.decode(match.encoding)
    except (LookupError, UnicodeDecodeError) as exc:
        raise ValueError("CSV містить некоректне або змішане кодування") from exc


def load_csv(path: Path, settings: Settings | None = None) -> list[TextUnit]:
    text = _decode(path)
    if settings is not None and len(text) > settings.max_extracted_chars:
        raise ValueError(
            f"CSV перевищує ліміт {settings.max_extracted_chars:,} символів"
        )
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    # Стандартний ліміт csv (~128 КБ) надто малий для реальних описових полів,
    # але необмежене значення дозволило б одному полю виснажити пам'ять.
    csv.field_size_limit(settings.max_extracted_chars if settings else 12_000_000)
    reader = csv.reader(io.StringIO(text), dialect=dialect)
    try:
        first_row = next(reader)
    except StopIteration:
        raise ValueError("CSV порожній")
    headers = [cell.strip() or f"column_{index + 1}" for index, cell in enumerate(first_row)]
    max_columns = settings.max_csv_columns if settings else 5_000
    if len(headers) > max_columns:
        raise ValueError(f"CSV перевищує ліміт {max_columns:,} колонок")
    units: list[TextUnit] = []
    for row_number, row in enumerate(reader, start=2):
        if settings is not None and row_number > settings.max_csv_rows + 1:
            raise ValueError(f"CSV перевищує ліміт {settings.max_csv_rows:,} рядків даних")
        if len(row) > max_columns:
            raise ValueError(
                f"CSV-рядок {row_number} перевищує ліміт {max_columns:,} колонок"
            )
        # Не втрачаємо значення, якщо рядок ширший за заголовок. Такі дані часто
        # є саме тією структурною аномалією, яку повинен побачити аудитор.
        extra_count = max(0, len(row) - len(headers))
        row_headers = headers + [
            f"extra_column_{index + 1}" for index in range(extra_count)
        ]
        padded = row + [""] * max(0, len(row_headers) - len(row))
        values = [f"{header}: {value.strip()}" for header, value in zip(row_headers, padded)]
        units.append(
            TextUnit(
                text=" | ".join(values),
                kind="csv",
                row_start=row_number,
                row_end=row_number,
            )
        )
    if not units:
        units.append(TextUnit(text=" | ".join(headers), kind="csv", row_start=1, row_end=1))
    return units
