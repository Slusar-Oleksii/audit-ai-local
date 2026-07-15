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
    initial_sidebar_state="auto",
)


APP_CSS = """
<style>
:root {
  --audit-ink: #102a52;
  --audit-muted: #64748b;
  --audit-faint: #94a3b8;
  --audit-border: #d7e0ec;
  --audit-sidebar: #f8faff;
  --audit-soft: #f5f8fd;
  --audit-blue: #0f62e9;
  --audit-blue-hover: #0b4fc4;
  --audit-green: #18a665;
  --audit-amber: #e68a00;
  --audit-red: #e04444;
  --audit-radius: 6px;
}
.stApp {
  background: #ffffff;
  color: var(--audit-ink);
  font-family: "Segoe UI", Inter, system-ui, -apple-system, sans-serif;
}
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"], [data-testid="stDecoration"] { display: none !important; }
.block-container {
  max-width: 1320px;
  padding: 1rem 2.35rem 4rem;
}
[data-testid="stSidebar"] {
  background: var(--audit-sidebar);
  border-right: 1px solid var(--audit-border);
  min-width: 292px;
  max-width: 292px;
}
[data-testid="stSidebar"] > div { padding-top: 1rem; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: .55rem; }
.audit-brand {
  color: var(--audit-ink);
  font-size: 1.55rem;
  font-weight: 800;
  letter-spacing: -0.045em;
  margin: 0 0 .8rem;
}
.audit-status {
  display: flex;
  align-items: center;
  gap: .5rem;
  color: var(--audit-ink);
  font-size: .82rem;
  font-weight: 600;
  margin-bottom: .9rem;
}
.audit-dot { width: .52rem; height: .52rem; border-radius: 50%; display: inline-block; }
.audit-dot.ok { background: var(--audit-green); }
.audit-dot.warn { background: var(--audit-amber); }
.audit-dot.bad { background: var(--audit-red); }
.audit-system-panel {
  border: 1px solid var(--audit-border);
  background: #fff;
  padding: .7rem .8rem;
  border-radius: var(--audit-radius);
  margin: .15rem 0 .65rem;
}
.audit-system-row {
  display: flex;
  justify-content: space-between;
  gap: .8rem;
  padding: .26rem 0;
  font-size: .75rem;
}
.audit-system-row span:last-child { color: var(--audit-muted); text-align: right; }
.audit-sidebar-label {
  color: var(--audit-ink);
  font-size: .78rem;
  font-weight: 750;
  letter-spacing: .02em;
  margin: .75rem 0 .1rem;
  text-transform: uppercase;
}
.audit-doc-meta {
  color: var(--audit-muted);
  font-size: .7rem;
  line-height: 1.35;
  margin-top: -.28rem;
}
.audit-doc-name {
  color: var(--audit-ink);
  font-size: .78rem;
  font-weight: 650;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
[class*="st-key-delete-doc-"] button {
  min-height: 2rem !important;
  padding: .25rem !important;
}
[class*="st-key-delete-doc-"] button p { display: none; }
.audit-workspace-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 58px;
  margin: -.15rem -2.35rem 0;
  padding: .65rem 2.35rem .9rem;
  border-bottom: 1px solid var(--audit-border);
}
.audit-workspace-header h1 {
  color: var(--audit-ink);
  font-size: 1.25rem;
  font-weight: 760;
  letter-spacing: -.025em;
  margin: 0;
}
.audit-workspace-status {
  align-items: center;
  color: var(--audit-muted);
  display: flex;
  font-size: .78rem;
  gap: .5rem;
}
.audit-step-head {
  align-items: center;
  display: flex;
  gap: .85rem;
  margin-bottom: 1rem;
}
.audit-step-number {
  align-items: center;
  background: var(--audit-blue);
  border-radius: 999px;
  color: #fff;
  display: inline-flex;
  flex: 0 0 2rem;
  font-size: .95rem;
  font-weight: 760;
  height: 2rem;
  justify-content: center;
}
.audit-step-copy h2 {
  color: var(--audit-ink);
  font-size: 1.05rem;
  font-weight: 740;
  letter-spacing: -.015em;
  line-height: 1.2;
  margin: 0;
}
.audit-step-copy p {
  color: var(--audit-muted);
  font-size: .78rem;
  margin: .18rem 0 0;
}
.st-key-step-upload,
.st-key-step-setup,
.st-key-step-report {
  border-bottom: 1px solid var(--audit-border);
  padding: 1rem 0 1.2rem;
}
.st-key-step-report { border-bottom: 0; padding-bottom: 0; }
.audit-upload-summary {
  align-items: center;
  color: var(--audit-muted);
  display: flex;
  font-size: .78rem;
  gap: .5rem;
  margin-top: .25rem;
}
.audit-check {
  align-items: center;
  background: var(--audit-green);
  border-radius: 50%;
  color: #fff;
  display: inline-flex;
  font-size: .65rem;
  font-weight: 800;
  height: 1.15rem;
  justify-content: center;
  width: 1.15rem;
}
.audit-report-empty {
  background: var(--audit-soft);
  border: 1px dashed #b7c5d8;
  border-radius: var(--audit-radius);
  color: var(--audit-muted);
  padding: 2.25rem 1.5rem;
  text-align: center;
}
.audit-report-empty strong {
  color: var(--audit-ink);
  display: block;
  font-size: .92rem;
  margin-bottom: .25rem;
}
.stButton > button, .stDownloadButton > button {
  border-radius: var(--audit-radius);
  min-height: 2.45rem;
  font-size: .82rem;
  font-weight: 650;
  transition: background .15s ease, border-color .15s ease, color .15s ease;
}
.stButton > button[kind="primary"] {
  background: var(--audit-blue);
  border-color: var(--audit-blue);
}
.stButton > button[kind="primary"]:hover {
  background: var(--audit-blue-hover);
  border-color: var(--audit-blue-hover);
}
.stButton > button:disabled {
  background: #e5eaf1 !important;
  border-color: #d7dee8 !important;
  color: #77859a !important;
  opacity: 1 !important;
}
.stTextArea textarea, .stTextInput input, [data-baseweb="select"] > div {
  border-radius: var(--audit-radius) !important;
  font-family: "Segoe UI", Inter, system-ui, sans-serif !important;
  font-size: .86rem !important;
}
.stTextArea textarea:focus, .stTextInput input:focus {
  border-color: var(--audit-blue) !important;
  box-shadow: 0 0 0 1px var(--audit-blue) !important;
}
[data-testid="stFileUploaderDropzone"] {
  align-items: center;
  background: #fbfdff;
  border: 1px dashed #9fb0c7;
  border-radius: var(--audit-radius);
  flex-direction: column-reverse;
  gap: .7rem;
  justify-content: center;
  min-height: 108px;
  padding: 1rem;
  text-align: center;
}
[data-testid="stFileUploaderDropzone"] button { border-radius: var(--audit-radius); }
[data-testid="stFileUploaderDropzone"] button p { font-size: 0; }
[data-testid="stFileUploaderDropzone"] button p::after {
  content: "Обрати файли";
  font-size: .8rem;
}
[data-testid="stFileUploaderDropzoneInstructions"] span { color: var(--audit-ink); }
[data-testid="stFileUploaderDropzoneInstructions"] small { color: var(--audit-muted); }
[data-testid="stFileUploaderDropzoneInstructions"] span {
  display: block;
  font-size: 0;
}
[data-testid="stFileUploaderDropzoneInstructions"] span::after {
  color: var(--audit-muted);
  content: "Перетягніть файли сюди · до 100 МБ на файл";
  font-size: .76rem;
}
div[data-testid="stRadio"] { width: 100% !important; }
div[data-testid="stRadio"] > div { width: 100% !important; }
.st-key-step-setup [data-testid="stElementContainer"]:has([data-testid="stRadio"]) {
  width: 100% !important;
}
div[data-testid="stRadio"] [role="radiogroup"] {
  border: 1px solid var(--audit-border);
  border-radius: var(--audit-radius);
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  overflow: hidden;
  width: 100%;
}
div[data-testid="stRadio"] [role="radiogroup"] > label {
  align-items: center;
  border-right: 1px solid var(--audit-border);
  justify-content: center;
  margin: 0;
  min-height: 2.7rem;
  padding: .55rem .35rem;
}
div[data-testid="stRadio"] [role="radiogroup"] > label:last-child { border-right: 0; }
div[data-testid="stRadio"] [role="radiogroup"] > label[data-selected="true"] {
  background: #eef4ff;
  color: var(--audit-blue);
  box-shadow: inset 0 0 0 1px var(--audit-blue);
}
div[data-testid="stRadio"] [data-testid="stRadioOption"] > div > div > div:first-child {
  display: none !important;
}
div[data-testid="stRadio"] [data-testid="stMarkdownContainer"] p { text-align: center; }
div[data-testid="stRadio"] [data-testid="stWidgetLabel"] { display: none; }
div[data-testid="stRadio"] label { font-size: .8rem; }
[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: var(--audit-border) !important;
  border-radius: var(--audit-radius) !important;
}
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 { color: var(--audit-ink); letter-spacing: -.02em; }
[data-testid="stMarkdownContainer"] h1 { font-size: 1.55rem; }
[data-testid="stMarkdownContainer"] h2 { font-size: 1.2rem; }
[data-testid="stMarkdownContainer"] h3 { font-size: 1rem; }
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li { line-height: 1.55; }
[data-testid="stMarkdownContainer"] blockquote {
  border-left-color: var(--audit-blue);
  background: #f4f7ff;
  padding: .75rem 1rem;
}
[data-testid="stSidebar"] .stButton > button { min-height: 2.25rem; }
[data-testid="stSidebar"] [data-testid="stExpander"] {
  background: transparent;
  border-color: var(--audit-border);
  border-radius: var(--audit-radius);
}
footer { visibility: hidden; }
@media (max-width: 900px) {
  .block-container { padding: .75rem 1rem 3rem; }
  .audit-workspace-header {
    align-items: flex-start;
    margin: 0 -1rem;
    padding: .6rem 1rem .9rem;
  }
  .audit-workspace-header h1 { font-size: 1.08rem; }
  .audit-workspace-status { font-size: 0; }
  .audit-step-head { align-items: flex-start; }
  div[data-testid="stRadio"] [role="radiogroup"] {
    grid-template-columns: 1fr;
  }
  div[data-testid="stRadio"] [role="radiogroup"] > label {
    border-bottom: 1px solid var(--audit-border);
    border-right: 0;
  }
  div[data-testid="stRadio"] [role="radiogroup"] > label:last-child { border-bottom: 0; }
  [data-testid="column"] { min-width: 100% !important; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; }
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
    # OCRmyPDF 17 with ``--output-type pdf`` uses PDFium and does not require
    # Ghostscript. Ghostscript remains useful for optional PDF/A workflows.
    ocr_ok = bool(ocrmypdf and tesseract)
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


def core_is_ready(status: dict[str, bool | str]) -> bool:
    return bool(status["runtime"] and status["ollama"] and status["llm"] and status["embedding"])


def render_step_header(number: int, title: str, description: str) -> None:
    st.markdown(
        '<div class="audit-step-head">'
        f'<span class="audit-step-number">{number}</span>'
        '<div class="audit-step-copy">'
        f'<h2>{html.escape(title)}</h2>'
        f'<p>{html.escape(description)}</p>'
        '</div></div>',
        unsafe_allow_html=True,
    )


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
    all_ready = core_is_ready(status)
    st.sidebar.markdown('<div class="audit-brand">АУДИТ AI</div>', unsafe_allow_html=True)
    st.sidebar.markdown(
        f'<div class="audit-status"><span class="audit-dot {"ok" if all_ready else "warn"}"></span>'
        f'{"Система готова" if all_ready else "Потрібне налаштування"}</div>',
        unsafe_allow_html=True,
    )
    with st.sidebar.expander("Стан компонентів", expanded=not all_ready):
        st.markdown(
            '<div class="audit-system-panel">'
            f'<div class="audit-system-row"><span>Runtime</span><span>{html.escape(str(status["runtime_detail"]))}</span></div>'
            f'<div class="audit-system-row"><span>Ollama</span><span>{status_word(bool(status["ollama"]), "Підключено")}</span></div>'
            f'<div class="audit-system-row"><span>LLM ({html.escape(settings.llm_model)})</span><span>{status_word(bool(status["llm"]))}</span></div>'
            f'<div class="audit-system-row"><span>Embeddings</span><span>{status_word(bool(status["embedding"]))}</span></div>'
            f'<div class="audit-system-row"><span>OCR</span><span>{status_word(bool(status["ocr"]), "Доступний", "Опційно")}</span></div>'
            '</div>',
            unsafe_allow_html=True,
        )

    st.sidebar.markdown('<div class="audit-sidebar-label">Проєкт</div>', unsafe_allow_html=True)
    projects = catalog().list_projects()

    def create_project_form(*, expanded: bool) -> None:
        with st.sidebar.expander("Новий проєкт", expanded=expanded, icon=":material/add:"):
            with st.form("create-project", clear_on_submit=True):
                name = st.text_input(
                    "Назва нового проєкту",
                    placeholder="Наприклад, Аудит Q2",
                )
                created = st.form_submit_button(
                    "Створити проєкт",
                    icon=":material/add:",
                    use_container_width=True,
                )
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
        create_project_form(expanded=True)
        st.sidebar.caption("Локальний режим · v0.1.0")
        return None

    project_ids = [project.id for project in projects]
    current = st.session_state.get("project_id")
    if current not in project_ids:
        current = project_ids[0]
    selected = st.sidebar.selectbox(
        "Активний проєкт",
        project_ids,
        index=project_ids.index(current),
        format_func=lambda project_id: next(
            project.name for project in projects if project.id == project_id
        ),
        label_visibility="collapsed",
    )
    if selected != st.session_state.get("project_id"):
        st.session_state["project_id"] = selected
        st.session_state.pop("ingestion_feedback", None)
        clear_report_state()
    create_project_form(expanded=False)

    st.sidebar.markdown('<div class="audit-sidebar-label">Документи</div>', unsafe_allow_html=True)
    documents = catalog().list_documents(selected)
    if not documents:
        st.sidebar.caption("Документів ще немає")
    for document in documents:
        with st.sidebar.container(border=True):
            left, right = st.columns([5, 1])
            with left:
                st.markdown(
                    f'<div class="audit-doc-name">{html.escape(document.original_name)}</div>',
                    unsafe_allow_html=True,
                )
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
                    f'{document.size_bytes / 1024:.0f} КБ · {document.chunk_count} chunks<br>{status_label}</div>',
                    unsafe_allow_html=True,
                )
            with right:
                if st.button(
                    "Видалити документ",
                    key=f"delete-doc-{document.id}",
                    icon=":material/delete:",
                    type="tertiary",
                    help="Видалити документ",
                ):
                    try:
                        ingestion_service().delete_document(selected, document.id)
                        clear_report_state()
                        st.rerun()
                    except Exception as exc:
                        st.sidebar.error(str(exc))

    with st.sidebar.expander("Керування проєктом"):
        if documents and st.button(
            "Переіндексувати документи",
            icon=":material/sync:",
            use_container_width=True,
        ):
            try:
                with st.spinner("Повторно будую індекс проєкту…"):
                    result = ingestion_service().reindex_project(selected)
                save_ingestion_feedback(result)
                clear_report_state()
                st.rerun()
            except Exception as exc:
                st.error(f"Не вдалося переіндексувати проєкт: {exc}")
        confirm = st.checkbox("Підтверджую повне видалення")
        if st.button(
            "Видалити проєкт",
            disabled=not confirm,
            icon=":material/delete:",
            use_container_width=True,
        ):
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
status = readiness()
all_ready = core_is_ready(status)

if project_id is None:
    st.markdown(
        '<div class="audit-workspace-header">'
        '<h1>Новий аудит</h1>'
        f'<div class="audit-workspace-status"><span class="audit-dot {"ok" if all_ready else "warn"}"></span>'
        f'{"Система готова" if all_ready else "Перевірте компоненти"}</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="audit-report-empty" style="margin-top:2rem">'
        '<strong>Почніть із нового проєкту</strong>'
        'Створіть проєкт у лівій панелі, щоб ізолювати його документи, індекс і звіти.'
        '</div>',
        unsafe_allow_html=True,
    )
    st.stop()

active_project = catalog().get_project(project_id)
workspace_name = active_project.name if active_project else "Новий аудит"
st.markdown(
    '<div class="audit-workspace-header">'
    f'<h1>{html.escape(workspace_name)}</h1>'
    f'<div class="audit-workspace-status"><span class="audit-dot {"ok" if all_ready else "warn"}"></span>'
    f'{"Система готова" if all_ready else "Перевірте компоненти"}</div>'
    '</div>',
    unsafe_allow_html=True,
)
render_ingestion_feedback()
documents = catalog().list_documents(project_id)

with st.container(key="step-upload"):
    render_step_header(
        1,
        "Додайте документи",
        "Завантажте джерела та побудуйте ізольований індекс цього проєкту.",
    )
    uploaded_files = st.file_uploader(
        "PDF, DOCX, CSV, TXT або вихідний код",
        type=[
            "pdf", "docx", "csv", "txt", "md", "json", "yaml", "yml", "toml", "ini",
            "py", "js", "jsx", "ts", "tsx", "java", "c", "cc", "cpp", "h", "hpp",
            "cs", "go", "rs", "php", "rb", "sql", "html", "css", "scss", "sh", "bash", "ps1",
        ],
        accept_multiple_files=True,
        max_upload_size=get_settings().max_upload_mb,
        key=f"uploads-{project_id}",
        label_visibility="collapsed",
    )
    summary_col, index_col = st.columns([4, 1])
    with summary_col:
        if documents:
            st.markdown(
                '<div class="audit-upload-summary"><span class="audit-check">✓</span>'
                f'{len(documents)} документ(и) у поточному індексі</div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("Індекс порожній. Додайте хоча б один документ перед аудитом.")
    if uploaded_files:
        total_upload_bytes = sum(item.size for item in uploaded_files)
        total_limit = get_settings().max_total_upload_mb * 1024 * 1024
        exceeds_limit = total_upload_bytes > total_limit
        if exceeds_limit:
            st.error(
                f"Сумарний розмір файлів перевищує {get_settings().max_total_upload_mb} МБ."
            )
        with index_col:
            index_clicked = st.button(
                "Індексувати",
                type="primary",
                icon=":material/database:",
                disabled=exceeds_limit,
                use_container_width=True,
            )
        if index_clicked:
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

with st.container(key="step-setup"):
    render_step_header(
        2,
        "Налаштуйте аудит",
        "Оберіть профіль і сформулюйте конкретне завдання для аналізу.",
    )
    profile_options = list(AuditProfile)
    profile = st.radio(
        "Оберіть профіль",
        profile_options,
        format_func=lambda value: PROFILE_LABELS[value],
        horizontal=True,
        key=f"audit-profile-{project_id}",
        label_visibility="collapsed",
    )
    query = st.text_area(
        "Опишіть, що потрібно перевірити",
        height=118,
        placeholder=(
            "Наприклад: Проведи фінансовий аудит звітів, знайди розбіжності, "
            "оціни ризики та наведи джерела для кожного висновку."
        ),
        key=f"audit-query-{project_id}",
    )
    action_left, action_right = st.columns([4, 1])
    can_run = bool(documents) and len(query.strip()) >= 3 and all_ready
    with action_left:
        if not all_ready:
            st.caption("Запуск недоступний: перевірте локальні моделі у блоці «Стан компонентів».")
        elif not documents:
            st.caption("Спочатку додайте та проіндексуйте хоча б один документ.")
        else:
            st.caption(f"{len(query)}/4000 символів · документи трактуються лише як недовірені дані")
    with action_right:
        run_clicked = st.button(
            "Провести аудит",
            type="primary",
            icon=":material/play_arrow:",
            disabled=not can_run,
            use_container_width=True,
        )

    if run_clicked:
        # Старий звіт не повинен виглядати результатом нового, невдалого запиту.
        clear_report_state()
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

with st.container(key="step-report"):
    render_step_header(
        3,
        "Сформуйте звіт",
        "Перегляньте висновки, звірте джерела та експортуйте результат.",
    )
    markdown = st.session_state.get("report_markdown")
    if markdown:
        report_state = st.session_state.get("report") or {}
        report_title, report_action = st.columns([4, 1])
        with report_title:
            source_count = len(report_state.get("sources") or [])
            finding_count = len(report_state.get("findings") or [])
            st.caption(f"{finding_count} висновків · {source_count} джерел")
        with report_action:
            st.download_button(
                "Завантажити Markdown",
                data=markdown,
                file_name="audit-report.md",
                mime="text/markdown",
                icon=":material/download:",
                use_container_width=True,
            )
        with st.container(border=True):
            st.markdown(sanitize_markdown_for_display(markdown))
    else:
        st.markdown(
            '<div class="audit-report-empty">'
            '<strong>Звіт ще не сформовано</strong>'
            'Після аудиту тут з’являться підтверджені висновки, обмеження та реєстр джерел.'
            '</div>',
            unsafe_allow_html=True,
        )
