from __future__ import annotations

from importlib.resources import files

from audit_ai.schemas import AuditProfile, AuditRequest, RetrievalPlan


PROFILE_LABELS = {
    AuditProfile.auto: "Авто",
    AuditProfile.financial: "Фінансовий",
    AuditProfile.legal: "Юридичний",
    AuditProfile.technical: "Технічний",
    AuditProfile.universal: "Універсальний",
}


def load_prompt(name: str) -> str:
    return files("audit_ai.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")


def profile_prompt(profile: AuditProfile) -> str:
    selected = profile if profile != AuditProfile.auto else AuditProfile.universal
    return load_prompt(selected.value)


def fallback_plan(request: AuditRequest) -> RetrievalPlan:
    profile = request.profile if request.profile != AuditProfile.auto else AuditProfile.universal
    return RetrievalPlan(profile=profile, queries=[request.query])
