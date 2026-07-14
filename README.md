# АУДИТ AI

[![CI](https://github.com/Slusar-Oleksii/audit-ai-local/actions/workflows/ci.yml/badge.svg)](https://github.com/Slusar-Oleksii/audit-ai-local/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Локальна система ШІ-аудиту документів із RAG, ChromaDB та Ollama. Документи розділені
за проєктами, а кожен висновок у звіті посилається на конкретний фрагмент джерела.

> Це інструмент підтримки аудитора. Він не замінює кваліфікований фінансовий,
> юридичний, технічний або безпековий висновок.

## Можливості MVP

- PDF, включно зі сканами через OCRmyPDF/Tesseract.
- DOCX із параграфами й таблицями.
- CSV із різними delimiter і кодуваннями.
- TXT, Markdown, JSON/YAML/TOML та основні формати вихідного коду.
- Окремі проєкти з жорстким metadata-фільтром у ChromaDB.
- Профілі Auto, фінансовий, юридичний, технічний та універсальний.
- Multi-query retrieval, Reciprocal Rank Fusion і структурований звіт.
- Перевірені посилання `[S1]`, `[S2]` на сторінки, рядки або CSV-записи.
- AI-висновки завжди позначаються як такі, що потребують перевірки аудитором; цитата доводить походження тексту, але не правильність інтерпретації.
- Локальний Markdown export. Завантажений код ніколи не виконується.

## Архітектура

```text
Streamlit -> loaders/OCR -> chunking -> Ollama embeddings -> ChromaDB
     |                                                |
     +-> audit query -> profile/router -> retrieval --+
                              |
                         Qwen3 structured output -> Markdown
```

Оригінали зберігаються в `data/projects`, вектори — в `data/chroma`, каталог проєктів
і документів — у `data/catalog.sqlite3`. Каталог `data` не додається до Git.

## Системні вимоги

- Windows 10/11, Linux або macOS, 64-bit.
- Python 3.11.x. Ця версія є обов'язковою через Windows-сумісність локального Chroma backend.
- Рекомендовано 16 ГБ RAM.
- Ollama. GPU не обов'язковий, але CPU-аналіз може тривати кілька хвилин.
- Для сканів: Tesseract, українська й англійська мовні моделі та Ghostscript.

## Встановлення на Windows

Відкрийте PowerShell від імені адміністратора для системних пакетів:

```powershell
winget install -e --id Python.Python.3.11
winget install -e --id Ollama.Ollama
winget install -e --id UB-Mannheim.TesseractOCR
winget install -e --id ArtifexSoftware.GhostScript
```

Під час інсталяції Tesseract додайте `Ukrainian` та `English`. Після встановлення
відкрийте новий PowerShell і перевірте:

```powershell
tesseract --list-langs
```

Список повинен містити `ukr` і `eng`.

У каталозі проєкту:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
ollama pull qwen3:8b
ollama pull qwen3-embedding:0.6b
python scripts\doctor.py
streamlit run app.py
```

Ollama для Windows зазвичай працює у фоні. Інтерфейс Streamlit відкриється за адресою
`http://localhost:8501`.

## Швидкий сценарій

1. Створіть проєкт у лівій панелі.
2. Завантажте один або кілька документів.
3. Натисніть **Індексувати файли** й дочекайтеся результату для кожного файла.
4. Оберіть профіль аудиту або залиште **Авто**.
5. Опишіть, що саме потрібно перевірити, й натисніть **Провести аудит**.
6. Перегляньте висновки та джерела, потім завантажте Markdown.

## Конфігурація

Скопіюйте `.env.example` у `.env` і змініть лише потрібні параметри. Важливі змінні:

| Змінна | Типове значення | Призначення |
|---|---|---|
| `AUDIT_DATA_DIR` | `data` | Локальне сховище |
| `AUDIT_OLLAMA_HOST` | `http://127.0.0.1:11434` | Лише локальний Ollama |
| `AUDIT_LLM_MODEL` | `qwen3:8b` | Модель звіту |
| `AUDIT_EMBEDDING_MODEL` | `qwen3-embedding:0.6b` | Модель embeddings |
| `AUDIT_COLLECTION_NAME` | `audit_chunks_qwen3_06b_v2` | Версійована Chroma-колекція |
| `AUDIT_OCR_LANGUAGES` | `ukr+eng` | Мови OCR |
| `AUDIT_MAX_UPLOAD_MB` | `100` | Ліміт одного файла |
| `AUDIT_MAX_TOTAL_UPLOAD_MB` | `250` | Сумарний ліміт однієї черги upload |
| `AUDIT_MAX_EXTRACTED_CHARS` | `12000000` | Межа тексту після парсингу/OCR |
| `AUDIT_MAX_CSV_ROWS` | `500000` | Межа рядків одного CSV |
| `AUDIT_MAX_CSV_COLUMNS` | `5000` | Межа колонок одного CSV-рядка |
| `AUDIT_MAX_CHUNKS_PER_DOCUMENT` | `10000` | Захист від вибуху кількості chunks |
| `AUDIT_RETRIEVAL_FINAL_K` | `12` | Максимум chunks у контексті |

`AUDIT_OLLAMA_HOST` навмисно приймає лише `localhost`, `127.0.0.1` або `::1`.
Система зберігає сигнатуру embedding-моделі, chunking та OCR для кожного документа. Після зміни
цих параметрів аудит блокується до натискання **Переіндексувати документи** у керуванні проєктом.
Версія ChromaDB зафіксована на `0.6.3` із Python 3.11. Новіша Rust-гілка має
відкритий Windows-дефект, за якого `PersistentClient` може аварійно завершувати процес під час запису.

## Тести

Основні тести не потребують Ollama:

```powershell
pytest -q -m "not ollama"
```

Після завантаження локальних моделей:

```powershell
$env:RUN_OLLAMA_TESTS="1"
pytest -q -m ollama
```

Окремий нативний тест Chroma persistence на цільовому Python 3.11:

```powershell
$env:RUN_CHROMA_NATIVE_TESTS="1"
pytest -q -m chroma_native
```

## Безпека і приватність

- Runtime-запити виконуються лише до локального Ollama.
- Streamlit слухає тільки `127.0.0.1`. Не змінюйте `server.address` на wildcard без окремої автентифікації та TLS reverse proxy.
- Telemetry ChromaDB і Streamlit вимкнена.
- Імена файлів нормалізуються, а фактичні каталоги мають UUID.
- PDF/DOCX перевіряються за сигнатурою, а binary-вміст із текстовим розширенням відхиляється.
- DOCX перевіряється за розпакованим розміром і коефіцієнтом стиснення.
- OCR запускається списком аргументів без `shell=True`.
- Джерела передаються моделі як JSON Lines; інструкції всередині документів трактуються як недовірені дані.
- Підтверджений finding потребує Source ID і дослівної цитати, яка реально існує у відповідному chunk.
- Аудит, індексація та видалення одного проєкту серіалізовані, щоб не залишати сирітські звіти.
- Код, shell-команди та вкладення не виконуються.

Блокування проєктів є процесним. Не запускайте кілька екземплярів Streamlit одночасно над одним
`AUDIT_DATA_DIR`; для цього MVP підтримується один локальний процес.

Для особливо чутливих матеріалів використовуйте окремий обліковий запис ОС і шифрування диска.
Видалення окремого документа не видаляє вже сформовані аудиторські звіти: це навмисне збереження
історії аудиту. Для повного видалення похідних даних видаліть увесь проєкт.

## Типові проблеми

- **Ollama не підключено:** запустіть Ollama й перевірте `http://127.0.0.1:11434/api/tags`.
- **Модель відсутня:** виконайте відповідну команду `ollama pull`.
- **Скан не читається:** перевірте `ocrmypdf --version`, `tesseract --list-langs` і Ghostscript.
- **Застарілий індекс:** натисніть **Переіндексувати документи**. Оригінали повторно завантажувати не потрібно.
- **Повільна CPU-генерація:** зменште `AUDIT_RETRIEVAL_FINAL_K` або використайте `qwen3:4b`;
  для зміни embedding-моделі обов'язково створіть нову колекцію.

## Ліцензія

Проєкт поширюється за умовами [MIT License](LICENSE).

## Межі MVP

Немає XLSX, зображень як окремого формату, старого DOC, архівів, автентифікації
(тому UI навмисно доступний лише через loopback),
детермінованого бухгалтерського рушія, Semgrep/Bandit або PDF export. Числові,
юридичні та security-висновки потрібно перевіряти людиною.
