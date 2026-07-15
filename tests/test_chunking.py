from audit_ai.chunking import build_chunks
from audit_ai.schemas import TextUnit


def test_code_chunks_have_stable_ids_and_overlap(settings):
    units = [
        TextUnit(text=f"line {index}", kind="code", line_start=index, line_end=index)
        for index in range(1, 29)
    ]
    kwargs = dict(
        project_id="project",
        document_id="document",
        checksum="checksum",
        file_name="app.py",
        file_type="py",
        settings=settings,
    )
    first = build_chunks(units, **kwargs)
    second = build_chunks(units, **kwargs)
    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert first[0].line_start == 1
    assert first[0].line_end == 20
    assert first[1].line_start == 16


def test_pdf_chunks_never_mix_pages(settings):
    units = [
        TextUnit(text="A" * 600, page=1),
        TextUnit(text="B" * 600, page=2),
    ]
    chunks = build_chunks(
        units,
        project_id="p",
        document_id="d",
        checksum="x",
        file_name="report.pdf",
        file_type="pdf",
        settings=settings,
    )
    assert {chunk.page for chunk in chunks} == {1, 2}
    assert all(not ("A" in chunk.text and "B" in chunk.text) for chunk in chunks)


def test_csv_chunks_preserve_row_range(settings):
    units = [
        TextUnit(text=f"name: item-{index} | amount: {index}", kind="csv", row_start=index, row_end=index)
        for index in range(2, 12)
    ]
    chunks = build_chunks(
        units,
        project_id="p",
        document_id="d",
        checksum="x",
        file_name="data.csv",
        file_type="csv",
        settings=settings,
    )
    assert chunks[0].row_start == 2
    assert chunks[-1].row_end == 11


def test_single_long_code_line_is_bounded(settings):
    units = [TextUnit(text="x" * 5000, kind="code", line_start=7, line_end=7)]
    chunks = build_chunks(
        units,
        project_id="p",
        document_id="d",
        checksum="x",
        file_name="minified.js",
        file_type="js",
        settings=settings,
    )
    assert len(chunks) < 20
    assert all(len(chunk.text) <= settings.chunk_size for chunk in chunks)
    assert all(chunk.line_start == chunk.line_end == 7 for chunk in chunks)


def test_invalid_overlap_is_rejected_before_chunking(tmp_path):
    from pydantic import ValidationError

    from audit_ai.config import Settings

    try:
        Settings(data_dir=tmp_path, chunk_size=400, chunk_overlap=400)
    except ValidationError as exc:
        assert "chunk_overlap" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Очікувалася помилка конфігурації")
