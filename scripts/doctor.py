from __future__ import annotations

import importlib.util
from importlib.metadata import PackageNotFoundError, version
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def is_directory(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def load_local_env() -> None:
    """Читає прості KEY=VALUE з .env без вимоги до вже встановлених пакетів."""
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        value = raw_line.strip()
        if not value or value.startswith("#") or "=" not in value:
            continue
        key, raw_value = value.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, raw_value.strip().strip("\"'"))


load_local_env()

# The deployment launcher uses the same project-local language pack. Make the
# doctor useful from a fresh PowerShell session as well, where installers may
# not have updated PATH yet.
if sys.platform == "win32":
    runtime_dirs = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama",
        Path("C:/Program Files/Tesseract-OCR"),
    ]
    os.environ["PATH"] = os.pathsep.join(
        [str(path) for path in runtime_dirs if is_directory(path)]
        + [os.environ.get("PATH", "")]
    )
local_tessdata = ROOT / ".runtime" / "tessdata"
if (local_tessdata / "ukr.traineddata").is_file():
    os.environ["TESSDATA_PREFIX"] = str(local_tessdata)

DATA_DIR = Path(os.getenv("AUDIT_DATA_DIR", ROOT / "data"))
if not DATA_DIR.is_absolute():
    DATA_DIR = (ROOT / DATA_DIR).resolve()
OLLAMA_HOST = os.getenv("AUDIT_OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
LLM_MODEL = os.getenv("AUDIT_LLM_MODEL", "qwen3:8b")
EMBED_MODEL = os.getenv("AUDIT_EMBEDDING_MODEL", "qwen3-embedding:0.6b")
OCR_LANGUAGES = {
    item for item in os.getenv("AUDIT_OCR_LANGUAGES", "ukr+eng").split("+") if item
}


def line(ok: bool, label: str, detail: str, fix: str | None = None) -> bool:
    symbol = "OK" if ok else "FAIL"
    print(f"[{symbol}] {label}: {detail}")
    if not ok and fix:
        print(f"       Виправлення: {fix}")
    return ok


def check_packages() -> bool:
    packages = {
        "streamlit": "streamlit",
        "chromadb": "chromadb",
        "ollama": "ollama",
        "posthog": "posthog",
        "pydantic": "pydantic",
        "pydantic-settings": "pydantic_settings",
        "pypdf": "pypdf",
        "python-docx": "docx",
        "charset-normalizer": "charset_normalizer",
    }
    missing = [display for display, module in packages.items() if importlib.util.find_spec(module) is None]
    version_problem = ""
    if "chromadb" not in missing:
        try:
            installed_chroma = version("chromadb")
            if installed_chroma != "0.6.3":
                version_problem = f"; chromadb={installed_chroma}, потрібна 0.6.3"
        except PackageNotFoundError:
            missing.append("chromadb")
    if "posthog" not in missing:
        try:
            installed_posthog = version("posthog")
            if int(installed_posthog.split(".", 1)[0]) >= 6:
                version_problem += (
                    f"; posthog={installed_posthog}, потрібна версія <6 для Chroma 0.6.3"
                )
        except (PackageNotFoundError, ValueError):
            missing.append("posthog")
    return line(
        not missing and not version_problem,
        "Python-залежності",
        ("усі встановлені" if not missing else f"відсутні: {', '.join(missing)}") + version_problem,
        'pip install -e ".[dev]"',
    )


def check_data_dir() -> bool:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = DATA_DIR / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return line(True, "Сховище", str(DATA_DIR))
    except OSError as exc:
        return line(False, "Сховище", str(exc), "Надайте користувачу право запису до AUDIT_DATA_DIR")


def ollama_models() -> tuple[bool, set[str], str]:
    parsed = urllib.parse.urlparse(OLLAMA_HOST)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port is None
    ):
        return False, set(), "AUDIT_OLLAMA_HOST має бути явним локальним HTTP endpoint"
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=5) as response:
            payload = json.load(response)
        names = {str(item.get("name") or item.get("model")) for item in payload.get("models", [])}
        return True, names, "підключено"
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return False, set(), str(exc)


def model_present(expected: str, models: set[str]) -> bool:
    return expected in models or f"{expected}:latest" in models


def find_executable(alternatives: list[str]) -> str | None:
    for item in alternatives:
        found = shutil.which(item)
        if found:
            return found
        candidate = Path(sys.executable).resolve().parent / (
            f"{item}.exe" if sys.platform == "win32" and not item.endswith(".exe") else item
        )
        try:
            if candidate.exists():
                return str(candidate)
        except OSError:
            continue
    return None


def executable(name: str, alternatives: list[str], fix: str) -> bool:
    found = find_executable(alternatives)
    return line(bool(found), name, found or "не знайдено", fix)


def tesseract_languages() -> bool:
    command = find_executable(["tesseract"])
    if not command:
        return line(
            False,
            "OCR-мови",
            "неможливо перевірити без Tesseract",
            "Спочатку встановіть Tesseract, потім додайте ukr та eng language packs",
        )
    completed = subprocess.run(
        [command, "--list-langs"], capture_output=True, text=True, timeout=15, check=False
    )
    languages = set((completed.stdout + completed.stderr).splitlines())
    missing = OCR_LANGUAGES - languages
    return line(
        not missing,
        "OCR-мови",
        " + ".join(sorted(OCR_LANGUAGES)) if not missing else f"відсутні: {', '.join(sorted(missing))}",
        f"Додайте {', '.join(sorted(OCR_LANGUAGES))} language packs у Tesseract",
    )


def main() -> int:
    print("АУДИТ AI — перевірка середовища\n")
    checks: list[bool] = []
    checks.append(
        line(
            sys.version_info[:2] == (3, 11),
            "Python",
            sys.version.split()[0],
            "winget install -e --id Python.Python.3.11",
        )
    )
    checks.append(check_packages())
    checks.append(check_data_dir())

    ollama_ok, models, detail = ollama_models()
    checks.append(line(ollama_ok, "Ollama", detail, "Запустіть Ollama для Windows"))
    checks.append(
        line(
            model_present(LLM_MODEL, models),
            "LLM",
            LLM_MODEL,
            f"ollama pull {LLM_MODEL}",
        )
    )
    checks.append(
        line(
            model_present(EMBED_MODEL, models),
            "Embedding model",
            EMBED_MODEL,
            f"ollama pull {EMBED_MODEL}",
        )
    )
    checks.append(executable("OCRmyPDF", ["ocrmypdf"], "pip install ocrmypdf"))
    checks.append(
        executable(
            "Tesseract",
            ["tesseract"],
            "winget install -e --id UB-Mannheim.TesseractOCR",
        )
    )
    ghostscript = find_executable(["gswin64c", "gswin32c", "gs"])
    line(
        True,
        "Ghostscript (optional)",
        ghostscript or "not installed; OCR uses PDFium with --output-type pdf",
    )
    checks.append(tesseract_languages())
    print("\n" + ("Середовище готове." if all(checks) else "Середовище потребує налаштування."))
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
