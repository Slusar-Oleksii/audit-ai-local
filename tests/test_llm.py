from audit_ai.llm import _OLLAMA_UNSUPPORTED_SCHEMA_KEYS, _ollama_schema
from audit_ai.schemas import AuditDraft


def test_ollama_schema_preserves_contract_shape_without_unsupported_constraints():
    schema = _ollama_schema(AuditDraft.model_json_schema())

    def walk(value):
        if isinstance(value, dict):
            assert not (_OLLAMA_UNSUPPORTED_SCHEMA_KEYS & value.keys())
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(schema)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["findings"]["type"] == "array"
    assert schema["$defs"]["Severity"]["enum"] == [
        "critical",
        "high",
        "medium",
        "low",
        "info",
    ]
