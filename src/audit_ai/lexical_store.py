from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Iterator

from audit_ai.config import Settings, get_settings
from audit_ai.schemas import DocumentChunk, RetrievalHit


_TOKEN = re.compile(r"[^\W_]+", flags=re.UNICODE)


def _match_expression(query: str) -> str:
    """Build a literal, injection-safe FTS5 OR query from user text."""

    tokens: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN.findall(query):
        normalized = token.casefold()
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        tokens.append(normalized.replace('"', '""'))
        if len(tokens) == 32:
            break
    return " OR ".join(f'"{token}"' for token in tokens)


class LexicalStore:
    """Project-isolated SQLite FTS5 index used alongside Chroma vectors."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()
        self.path = self.settings.lexical_path
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        try:
            with self.connection() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS audit_chunks_fts USING fts5(
                        chunk_id UNINDEXED,
                        project_id UNINDEXED,
                        document_id UNINDEXED,
                        checksum UNINDEXED,
                        file_name,
                        file_type UNINDEXED,
                        index_signature UNINDEXED,
                        chunk_index UNINDEXED,
                        page UNINDEXED,
                        line_start UNINDEXED,
                        line_end UNINDEXED,
                        row_start UNINDEXED,
                        row_end UNINDEXED,
                        text,
                        tokenize='unicode61 remove_diacritics 2'
                    )
                    """
                )
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                "Python SQLite не підтримує FTS5; встановіть офіційний Python 3.11"
            ) from exc

    def upsert(self, chunks: Sequence[DocumentChunk]) -> None:
        if not chunks:
            return
        rows = [
            (
                chunk.id,
                chunk.project_id,
                chunk.document_id,
                chunk.checksum,
                chunk.file_name,
                chunk.file_type,
                chunk.index_signature,
                chunk.chunk_index,
                chunk.page,
                chunk.line_start,
                chunk.line_end,
                chunk.row_start,
                chunk.row_end,
                chunk.text,
            )
            for chunk in chunks
        ]
        with self.connection() as connection:
            connection.executemany(
                "DELETE FROM audit_chunks_fts WHERE chunk_id = ?",
                [(chunk.id,) for chunk in chunks],
            )
            connection.executemany(
                """
                INSERT INTO audit_chunks_fts(
                    chunk_id, project_id, document_id, checksum, file_name, file_type,
                    index_signature, chunk_index, page, line_start, line_end,
                    row_start, row_end, text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def query(self, project_id: str, query: str, n_results: int) -> list[RetrievalHit]:
        expression = _match_expression(query)
        if not expression or n_results < 1:
            return []
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT *, bm25(audit_chunks_fts, 0.0, 0.0, 0.0, 0.0, 1.0,
                    0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) AS lexical_score
                FROM audit_chunks_fts
                WHERE audit_chunks_fts MATCH ?
                  AND project_id = ?
                  AND index_signature = ?
                ORDER BY lexical_score
                LIMIT ?
                """,
                (expression, project_id, self.settings.index_signature, n_results),
            ).fetchall()
        hits: list[RetrievalHit] = []
        for rank, row in enumerate(rows, start=1):
            data = dict(row)
            score = float(data.pop("lexical_score"))
            chunk = DocumentChunk(
                id=str(data.pop("chunk_id")),
                project_id=str(data.pop("project_id")),
                document_id=str(data.pop("document_id")),
                checksum=str(data.pop("checksum")),
                file_name=str(data.pop("file_name")),
                file_type=str(data.pop("file_type")),
                index_signature=str(data.pop("index_signature")),
                chunk_index=int(data.pop("chunk_index")),
                page=data.pop("page"),
                line_start=data.pop("line_start"),
                line_end=data.pop("line_end"),
                row_start=data.pop("row_start"),
                row_end=data.pop("row_end"),
                text=str(data.pop("text")),
            )
            hits.append(RetrievalHit(chunk=chunk, rank=rank, distance=score))
        return hits

    def delete_document(self, project_id: str, document_id: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "DELETE FROM audit_chunks_fts WHERE project_id = ? AND document_id = ?",
                (project_id, document_id),
            )

    def delete_project(self, project_id: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "DELETE FROM audit_chunks_fts WHERE project_id = ?",
                (project_id,),
            )
