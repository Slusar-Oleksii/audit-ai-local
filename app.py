from __future__ import annotations

import html
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

import streamlit as st

from audit_ai.catalog import Catalog
from audit_ai.config import get_settings
from audit_ai.ingestion import IngestionService
from audit_ai.llm import LLMClient
from audit_ai.profiles import PROFILE_LABELS
from audit_ai.rag import AuditService
from audit_ai.reporting import render_markdown, sanitize_markdown_for_display
from audit_ai.schemas import AuditProfile, AuditRequest


st.set_page_config(
    page_title="АУДИТ AI",
    page_icon="◫",
    layout="wide",
    initial_sidebar_state="expanded",
)


APP_CSS = """
<style>
:root {
  --audit-ink: #12213f;
  --audit-muted: #64748b;
  --audit-border: #d8e0ec;
  --audit-soft: #f7f9fc;
  --audit-blue: #155eef;
  --audit-green: #16a34a;
  --audit-amber: #d97706;
  --audit-red: #dc2626;
}
.stApp { background: #ffffff; color: var(--audit-ink); }
[data-testid="stSidebar"] {
  background: #fbfcfe;
  border-right: 1px solid var(--audit-border);
}
[data-testid="stSidebar"] > div { padding-top: 1.25rem; }
.audit-brand {
  color: var(--audit-ink);
  font-size: 1.65rem;
  font-weight: 800;
  letter-spacing: -0.035em;
  margin: 0 0 1.25rem 0;
}
.audit-status {
  display: flex;
  align-items: center;
  gap: .55rem;
  color: var(--audit-ink);
  font-size: .86rem;
  font-weight: 650;
  margin-bottom: .7rem;
}
.audit-dot { width: .58rem; height: .58rem; border-radius: 50%; display: inline-block; }
.audit-dot.ok { background: var(--audit-green); }
.audit-dot.warn { background: var(--audit-amber); }
.audit-dot.bad { background: var(--audit-red); }
.audit-system-panel {
  border: 1px solid var(--audit-border);
  background: #fff;
  padding: .75rem .85rem;
  border-radius: .4rem;
  margin-bottom: 1.4rem;
}
.audit-system-row {
  display: flex;
  justify-content: space-between;
  gap: .8rem;
  padding: .32rem 0;
  font-size: .78rem;
}
.audit-system-row span:last-child { color: var(--audit-muted); text-align: right; }
.audit-doc-meta { color: var(--audit-muted); font-size: .72rem; margin-top: -.35rem; }
.audit-page-title {
  font-size: 2rem;
  line-height: 1.15;
  font-weight: 780;
  letter-spacing: -0.035em;
  color: var(--audit-ink);
  margin: .2rem 0 1.25rem;
}
.audit-section-title {
  color: var(--audit-ink);
  font-size: 1.12rem;
  font-weight: 720;
  margin: 1.3rem 0 .35rem;
}
.audit-report-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  border-top: 1px solid var(--audit-border);
  padding-top: 1.1rem;
  margin-top: 1.5rem;
}
.audit-report-head h2 { margin: 0; font-size: 1.35rem; letter-spacing: -.02em; }
.audit-empty {
  border: 1px dashed #b9c6d8;
  background: var(--audit-soft);
  padding: 2rem;
  text-align: center;
  color: var(--audit-muted);
  border-radius: .4rem;
}
.stButton > button, .stDownloadButton > button {
  border-radius: .35rem;
  min-height: 2.55rem;
  font-weight: 650;
  font-size: .86rem;
}
.stTextArea textarea, .stTextInput input, [data-baseweb="select"] > div {
  border-radius: .35rem !important;
  font-size: .9rem !important;
}
[data-testid="stFileUploaderDropzone"] {
  background: #fbfcfe;
  border: 1px dashed #b9c6d8;
  border-radius: .4rem;
  padding-top: 1.25rem;
  padding-bottom: 1.25rem;
}
[data-testid="stFileUploaderDropzone"] button { border-radius: .35rem; }
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 { color: var(--audit-ink); letter-spacing: -.02em; }
[data-testid="stMarkdownContainer"] blockquote {
  border-left-color: var(--audit-blue);
  background: #f4f7ff;
  padding: .75rem 1rem;
}
div[data-testid="stRadio"] label { font-size: .86rem; }
footer { visibility: hidden; }
@media (max-width: 900px) {
  .audit-page-title { font-size: 1.65rem; }
  [data-testid="column"] { min-width: 100% !important; }
}
</style>
"""
st.markdown(APP_CSS, unsafe_allow_html=True)


@st.cache_resource
def catalog() -> Catalog:
    return Catalog(get_settings())


@st.cache_resource
def ingestion_service() -> IngestionService:
    return IngestionService(get_settings(), catalog=catalog())


@st.cache_resource
def audit_service() -> AuditService:
    return AuditService(get_settings(), catalog=catalog())


@st.cache_data(ttl=15, show_spinner=False)
def readiness() -> dict[str, bool | str]:
    settings = get_settings()
    try:
        status = LLMClient(settings).readiness()
    except Exception as exc:
        status = {"ollama": False, "llm": False, "embedding": False, "detail": str(exc)}
    try:
        chroma_version = version("chromadb")
    except PackageNotFoundError:
        chroma_version = "не встановлено"
    status["runtime"] = sys.version_info[:2] == (3, 11) and chroma_version == "0.6.3"
    status["runtime_detail"] = (
        f"Python {sys.version_info.major}.{sys.version_info.minor} · Chroma {chroma_version}"
    )
    ocrmypdf = shutil.which("ocrmypdf")
    tesseract = shutil.which("tesseract")
    ghostscript = next(
        (path for name in ("gswin64c", "gswin32c", "gs") if (path := shutil.which(name))),
        None,
    )
    ocr_ok = bool(ocrmypdf and tesseract and ghostscript)
    if ocr_ok and tesseract:
        try:
            completed = subprocess.run(
                [tesseract, "--list-langs"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            languages = set((completed.stdout + completed.stderr).splitlines())
            required_languages = set(settings.ocr_languages.split("+"))
            ocr_ok = completed.returncode == 0 and required_languages <= languages
        except (OSError, subprocess.SubprocessError):
            ocr_ok = False
    status["ocr"] = ocr_ok
    return status


def status_word(ok: bool, yes: str = "Готово", no: str = "Не готово") -> str:
    return yes if ok else no


def clear_report_state() -> None:
    """Не дозволяє показати звіт, що належить старому стану проєкту."""
    st.session_state.pop("report", None)
    st.session_state.pop("report_markdown", None)


def save_ingestion_feedback(result) -> None:
    st.session_state["ingestion_feedback"] = [
        {
            "status": item.status,
            "message": f"{item.file_name}: {item.message}"
            + (f" ({item.chunk_count} chunks)" if item.chunk_count else ""),
        }
        for item in result.items
    ]


def render_ingestion_feedback() -> None:
    for item in st.session_state.pop("ingestion_feedback", []):
        if item["status"] == "indexed":
            st.success(item["message"])
        elif item["status"] in {"duplicate", "needs_reindex"}:
            st.warning(item["message"])
        else:
            st.error(item["message"])


def render_sidebar() -> str | None:
    settings = get_settings()
    status = readiness()
    all_ready = bool(
        status["runtime"] and status["ollama"] and status["llm"] and status["embedding"]
    )
    st.sidebar.markdown('<div class="audit-brand">АУДИТ AI</div>', unsafe_allow_html=True)
    st.sidebar.markdown(
        f'<div class="audit-status"><span class="audit-dot {"ok" if all_ready else "warn"}"></span>'
        f'{"Система готова" if all_ready else "Потрібне налаштування"}</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        '<div class="audit-system-panel">'
        f'<div class="audit-system-row"><span>Runtime</span><span>{html.escape(str(status["runtime_detail"]))}</span></div>'
        f'<div class="audit-system-row"><span>Ollama</span><span>{status_word(bool(status["ollama"]), "Підключено")}</span></div>'
        f'<div class="audit-system-row"><span>LLM ({html.escape(settings.llm_model)})</span><span>{status_word(bool(status["llm"]))}</span></div>'
        f'<div class="audit-system-row"><span>Embeddings</span><span>{status_word(bool(status["embedding"]))}</span></div>'
        f'<div class="audit-system-row"><span>OCR</span><span>{status_word(bool(status["ocr"]), "Доступний", "Опційно")}</span></div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.sidebar.subheader("Проєкт")
    projects = catalog().list_projects()
    with st.sidebar.form("create-project", clear_on_submit=True):
        name = st.text_input("Назва нового проєкту", placeholder="Наприклад, Аудит Q2")
        created = st.form_submit_button("＋ Створити проєкт", use_container_width=True)
        if created:
            try:
                project = ingestion_service().create_project(name)
                clear_report_state()
                st.session_state["project_id"] = project.id
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if not projects:
        st.sidebar.info("Створіть перший проєкт, щоб завантажити документи.")
        return None

    project_ids = [project.id for project in projects]
    current = st.session_state.get("project_id")
    if current not in project_ids:
        current = project_ids[0]
    selected = st.sidebar.selectbox(
        "Активний проєкт",
        project_ids,
        index=project_ids.index(current),
        format_func=lambda project_id: next(project.name for project in projects if project.id == project_id),
    )
    if selected != st.session_state.get("project_id"):
        st.session_state["project_id"] = selected
        clear_report_state()

    st.sidebar.subheader("Документи")
    documents = catalog().list_documents(selected)
    if not documents:
        st.sidebar.caption("Документів ще немає")
    for document in documents:
        left, right = st.sidebar.columns([5, 1])
        with left:
            st.text(document.original_name)
            is_current = (
                document.index_signature == settings.index_signature
                and document.collection_name == settings.collection_name
            )
            if document.status == "reindexing":
                status_label = "Переіндексація…"
            elif document.status == "reindex_error":
                status_label = "Помилка переіндексації"
            elif document.status not in {"indexed", "ocr_indexed"}:
                status_label = "Індекс не готовий"
            elif not is_current:
                status_label = "Потребує переіндексації"
            elif document.status == "ocr_indexed":
                status_label = "OCR + індекс"
            else:
                status_label = "Проіндексовано"
            st.markdown(
                f'<div class="audit-doc-meta">{document.file_type.upper()} · '
                f'{document.size_bytes / 1024:.0f} КБ · {document.chunk_count} chunks · {status_label}</div>',
                unsafe_allow_html=True,
            )
        with right:
            if st.button("×", key=f"delete-doc-{document.id}", help="Видалити документ"):
                try:
                    ingestion_service().delete_document(selected, document.id)
                    clear_report_state()
                    st.rerun()
                except Exception as exc:
                    st.sidebar.error(str(exc))

    with st.sidebar.expander("Керування проєктом"):
        if documents and st.button("Переіндексувати документи", use_container_width=True):
            try:
                with st.spinner("Повторно будую індекс проєкту…"):
                    result = ingestion_service().reindex_project(selected)
                save_ingestion_feedback(result)
                clear_report_state()
                st.rerun()
            except Exception as exc:
                st.error(f"Не вдалося переіндексувати проєкт: {exc}")
        confirm = st.checkbox("Підтверджую повне видалення")
        if st.button("Видалити проєкт", disabled=not confirm, use_container_width=True):
            try:
                ingestion_service().delete_project(selected)
                st.session_state.pop("project_id", None)
                clear_report_state()
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    st.sidebar.caption("Локальний режим · v0.1.0")
    return selected


project_id = render_sidebar()

st.markdown('<div class="audit-page-title">Новий аудит</div>', unsafe_allow_html=True)
render_ingestion_feedback()

if project_id is None:
    st.markdown(
        '<div class="audit-empty">Створіть проєкт у лівій панелі. Після цього тут з’явиться завантаження документів.</div>',
        unsafe_allow_html=True,
    )
    st.stop()

st.markdown('<div class="audit-section-title">Завантажте документи</div>', unsafe_allow_html=True)
uploaded_files = st.file_uploader(
    "PDF, DOCX, CSV, TXT або вихідний код",
    type=[
        "pdf", "docx", "csv", "txt", "md", "json", "yaml", "yml", "toml", "ini",
        "py", "js", "jsx", "ts", "tsx", "java", "c", "cc", "cpp", "h", "hpp",
        "cs", "go", "rs", "php", "rb", "sql", "html", "css", "scss", "sh", "bash", "ps1",
    ],
    accept_multiple_files=True,
    max_upload_size=get_settings().max_upload_mb,
)
if uploaded_files:
    total_upload_bytes = sum(item.size for item in uploaded_files)
    total_limit = get_settings().max_total_upload_mb * 1024 * 1024
    if total_upload_bytes > total_limit:
        st.error(f"Сумарний розмір файлів перевищує {get_settings().max_total_upload_mb} МБ.")
    elif st.button("Індексувати файли", type="primary"):
        try:
            uploads = [(item.name, item.getvalue()) for item in uploaded_files]
            with st.spinner("Витягую текст, створюю chunks та embeddings…"):
                result = ingestion_service().ingest_uploads(project_id, uploads)
            save_ingestion_feedback(result)
            if result.successful:
                clear_report_state()
            st.rerun()
        except Exception as exc:
            st.error(f"Не вдалося індексувати файли: {exc}")

st.markdown('<div class="audit-section-title">Профіль аудиту</div>', unsafe_allow_html=True)
profile_options = list(AuditProfile)
profile = st.radio(
    "Оберіть профіль",
    profile_options,
    format_func=lambda value: PROFILE_LABELS[value],
    horizontal=True,
    label_visibility="collapsed",
)

st.markdown('<div class="audit-section-title">Ваш запит</div>', unsafe_allow_html=True)
query = st.text_area(
    "Опишіть, що потрібно перевірити",
    height=130,
    placeholder="Наприклад: Проведи фінансовий аудит звітів, знайди розбіжності та поясни ризики.",
    label_visibility="collapsed",
)
action_left, action_right = st.columns([4, 1])
with action_right:
    run_clicked = st.button("Провести аудит", type="primary", use_container_width=True)

if run_clicked:
    # Старий звіт не повинен виглядати результатом нового, невдалого запиту.
    clear_report_state()
    if len(query.strip()) < 3:
        st.error("Введіть змістовний запит для аудиту.")
    elif not catalog().list_documents(project_id):
        st.error("Спочатку завантажте та проіндексуйте хоча б один документ.")
    else:
        with st.spinner("Планую пошук, добираю докази та формую звіт…"):
            try:
                report = audit_service().run_audit(
                    AuditRequest(project_id=project_id, query=query, profile=profile)
                )
                markdown = render_markdown(report)
                st.session_state["report"] = report.model_dump(mode="json")
                st.session_state["report_markdown"] = markdown
            except Exception as exc:
                st.error(f"Не вдалося сформувати аудит: {exc}")

markdown = st.session_state.get("report_markdown")
if markdown:
    st.markdown(
        '<div class="audit-report-head"><h2>Аудиторський звіт</h2></div>',
        unsafe_allow_html=True,
    )
    st.download_button(
        "⇩ Завантажити Markdown",
        data=markdown,
        file_name="audit-report.md",
        mime="text/markdown",
    )
    st.markdown(sanitize_markdown_for_display(markdown))
else:
    st.markdown(
        '<div class="audit-report-head"><h2>Аудиторський звіт</h2></div>',
        unsafe_allow_html=True,
    )
    st.caption("Звіт з’явиться тут після завершення аудиту.")
