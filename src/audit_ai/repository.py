from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from pathlib import Path

from audit_ai.config import Settings, get_settings
from audit_ai.schemas import AuditReport, AuditRunManifest


_UNSAFE_FILENAME = re.compile(r"[^\w.()\- ]+", flags=re.UNICODE)
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_identifier(value: str, label: str = "ідентифікатор") -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Некоректний {label}") from exc
    canonical = str(parsed)
    if value.casefold() != canonical:
        raise ValueError(f"Некоректний {label}")
    return canonical


def safe_filename(name: str) -> str:
    base = Path(name).name.strip()
    cleaned = _UNSAFE_FILENAME.sub("_", base).strip(" .")
    cleaned = cleaned or "document"
    suffix = Path(cleaned).suffix[:20]
    stem = cleaned[: -len(suffix)] if suffix else cleaned
    # Windows резервує ім'я пристрою до першої крапки, тому CON.foo.txt
    # так само небезпечне, як CON.txt.
    if stem.split(".", 1)[0].casefold() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    max_stem = max(1, 180 - len(suffix))
    return f"{stem[:max_stem].rstrip(' .') or 'document'}{suffix}"


class Repository:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()

    def project_dir(self, project_id: str) -> Path:
        return self.settings.projects_dir / safe_identifier(project_id, "ID проєкту")

    def ensure_project(self, project_id: str) -> Path:
        root = self.project_dir(project_id)
        (root / "documents").mkdir(parents=True, exist_ok=True)
        (root / "derived" / "ocr").mkdir(parents=True, exist_ok=True)
        (root / "reports").mkdir(parents=True, exist_ok=True)
        return root

    def store_document(self, project_id: str, document_id: str, source: Path, original_name: str) -> Path:
        safe_document_id = safe_identifier(document_id, "ID документа")
        target_dir = self.ensure_project(project_id) / "documents" / safe_document_id
        target_dir.mkdir(parents=True, exist_ok=False)
        target = target_dir / safe_filename(original_name)
        shutil.copy2(source, target)
        return target

    def validate_document_path(
        self,
        project_id: str,
        document_id: str,
        stored_path: Path,
    ) -> Path:
        """Забороняє каталогу спрямувати loader за межі сховища документа."""
        safe_document_id = safe_identifier(document_id, "ID документа")
        expected_directory = (
            self.project_dir(project_id) / "documents" / safe_document_id
        ).resolve()
        candidate = Path(stored_path).resolve()
        if not candidate.is_relative_to(expected_directory):
            raise ValueError("Шлях оригіналу документа виходить за межі локального сховища")
        return candidate

    def ocr_output_path(self, project_id: str, document_id: str) -> Path:
        directory = self.project_dir(project_id) / "derived" / "ocr"
        return directory / f"{safe_identifier(document_id, 'ID документа')}.pdf"

    def report_path(self, project_id: str, report_id: str, suffix: str) -> Path:
        if suffix not in {".md", ".json", ".manifest.json"}:
            raise ValueError("Непідтримуваний формат артефакту звіту")
        directory = self.project_dir(project_id) / "reports"
        if not directory.is_dir():
            raise FileNotFoundError("Проєкт видалено до завершення аудиту")
        return directory / f"{safe_identifier(report_id, 'ID звіту')}{suffix}"

    def _write_report_artifact(
        self,
        project_id: str,
        report_id: str,
        suffix: str,
        content: str,
    ) -> Path:
        target = self.report_path(project_id, report_id, suffix)
        temporary = target.with_name(f"{target.name}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return target

    def save_report(self, project_id: str, report_id: str, markdown: str) -> Path:
        return self._write_report_artifact(project_id, report_id, ".md", markdown)

    def save_report_json(self, project_id: str, report: AuditReport) -> Path:
        return self._write_report_artifact(
            project_id,
            report.report_id,
            ".json",
            report.model_dump_json(indent=2),
        )

    def save_manifest(self, project_id: str, manifest: AuditRunManifest) -> Path:
        return self._write_report_artifact(
            project_id,
            manifest.report_id,
            ".manifest.json",
            manifest.model_dump_json(indent=2),
        )

    def load_report(self, project_id: str, report_id: str) -> AuditReport:
        path = self.report_path(project_id, report_id, ".json")
        if not path.is_file():
            raise FileNotFoundError("Структурований файл цього звіту відсутній")
        return AuditReport.model_validate_json(path.read_text(encoding="utf-8"))

    def load_report_markdown(self, project_id: str, report_id: str) -> str:
        path = self.report_path(project_id, report_id, ".md")
        if not path.is_file():
            raise FileNotFoundError("Markdown-файл цього звіту відсутній")
        return path.read_text(encoding="utf-8")

    def delete_report_artifacts(self, project_id: str, report_id: str) -> None:
        for suffix in (".md", ".json", ".manifest.json"):
            self.report_path(project_id, report_id, suffix).unlink(missing_ok=True)

    def delete_document_files(self, project_id: str, document_id: str) -> None:
        safe_document_id = safe_identifier(document_id, "ID документа")
        directory = self.project_dir(project_id) / "documents" / safe_document_id
        if directory.exists():
            shutil.rmtree(directory)
        ocr_path = self.ocr_output_path(project_id, document_id)
        if ocr_path.exists():
            ocr_path.unlink()

    def delete_project_files(self, project_id: str) -> None:
        directory = self.project_dir(project_id)
        if directory.exists():
            shutil.rmtree(directory)
