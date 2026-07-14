from __future__ import annotations

import re

from audit_ai.schemas import (
    AuditDraft,
    AuditReport,
    Confidence,
    EvidenceStatus,
    Severity,
    SourceRef,
)


SEVERITY_LABELS = {
    Severity.critical: "Критична",
    Severity.high: "Висока",
    Severity.medium: "Середня",
    Severity.low: "Низька",
    Severity.info: "Інформаційна",
}
CONFIDENCE_LABELS = {
    Confidence.high: "висока",
    Confidence.medium: "середня",
    Confidence.low: "низька",
}


def _normalized_evidence(value: str) -> str:
    return " ".join(value.split()).casefold()


def validate_citations(
    draft: AuditDraft,
    sources: list[SourceRef],
    source_texts: dict[str, str] | None = None,
) -> AuditDraft:
    allowed = {source.source_id for source in sources}
    source_texts = source_texts or {}
    missing_evidence = False
    requires_human_review = False
    for finding in draft.findings:
        finding.source_ids = [source_id for source_id in finding.source_ids if source_id in allowed]
        quote = _normalized_evidence(finding.evidence_quote or "")
        quote_supported = len(quote) >= 12 and any(
            quote in _normalized_evidence(source_texts.get(source_id, ""))
            for source_id in finding.source_ids
        )
        if not finding.source_ids or not quote_supported:
            missing_evidence = True
        # Дослівна цитата підтверджує походження тексту, але не логічне
        # обґрунтування висновку. Лише людина-аудитор може підвищити статус.
        finding.evidence_status = EvidenceStatus.hypothesis
        finding.confidence = Confidence.low
        requires_human_review = True
    if missing_evidence:
        note = (
            "Окремі припущення не мають перевіреної дослівної цитати "
            "у відібраному контексті."
        )
        if note not in draft.limitations:
            draft.limitations.append(note)
    if requires_human_review:
        note = (
            "Усі висновки сформовані ШІ та потребують перевірки людиною-аудитором; "
            "наявність цитати підтверджує її походження, але не доводить правильність інтерпретації."
        )
        if note not in draft.limitations:
            draft.limitations.append(note)
    return draft


def render_markdown(report: AuditReport) -> str:
    lines = [
        "# Аудиторський звіт",
        "",
        f"**Профіль:** {report.profile.value}",
        f"**Запит:** {report.query}",
        f"**Модель:** `{report.model}`",
        f"**Створено:** {report.generated_at.isoformat()}",
        "",
        "> Звіт є інструментом підтримки аудитора й потребує професійної перевірки.",
        "",
        "## Резюме",
        "",
        report.executive_summary,
        "",
        "## Охоплення",
        "",
        report.scope,
        "",
        "## Методологія",
        "",
        report.methodology,
        "",
        "## Ключові висновки",
        "",
    ]
    if not report.findings:
        lines.extend(["Підтверджених проблем у відібраному контексті не виявлено.", ""])
    for number, finding in enumerate(report.findings, start=1):
        citations = " ".join(f"[{source_id}]" for source_id in finding.source_ids) or "джерело відсутнє"
        status = (
            "підтверджено аудитором"
            if finding.evidence_status == EvidenceStatus.confirmed
            else "потребує перевірки аудитором"
        )
        lines.extend(
            [
                f"### {number}. {finding.title}",
                "",
                f"- **Категорія:** {finding.category}",
                f"- **Серйозність:** {SEVERITY_LABELS[finding.severity]}",
                f"- **Статус доказів:** {status}",
                f"- **Впевненість:** {CONFIDENCE_LABELS[finding.confidence]}",
                f"- **Джерела:** {citations}",
                "",
                *(
                    [f"**Цитата-доказ:** “{finding.evidence_quote}”", ""]
                    if finding.evidence_quote
                    else []
                ),
                finding.description,
                "",
                f"**Вплив:** {finding.impact}",
                "",
                f"**Рекомендація:** {finding.recommendation}",
                "",
            ]
        )
    lines.extend(["## Обмеження", ""])
    if report.limitations:
        lines.extend(f"- {item}" for item in report.limitations)
    else:
        lines.append("- Додаткових обмежень не зафіксовано.")
    lines.extend(["", "## Джерела", ""])
    for source in report.sources:
        lines.append(
            f"- **[{source.source_id}]** `{source.file_name}` — {source.location}. "
            f"Фрагмент: “{source.excerpt}”"
        )
    return sanitize_markdown_for_display("\n".join(lines).strip() + "\n")


_MARKDOWN_IMAGE = re.compile(r"\\*!\[")


def sanitize_markdown_for_display(markdown: str) -> str:
    """Не дозволяє Markdown автоматично завантажувати зовнішні зображення."""

    return _MARKDOWN_IMAGE.sub(lambda _: r"\![", markdown)
