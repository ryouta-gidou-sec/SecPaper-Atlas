from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import ClassificationResult


def valid_classification(**overrides: object) -> ClassificationResult:
    values: dict[str, object] = {
        "primary_category": "Session Management",
        "tags": ["Session Hijacking", "Session Hijacking", " Cookie Security "],
        "research_methods": ["Black-box Testing"],
        "target_vulnerabilities": ["Session Hijacking"],
        "relevance": "A",
        "relevance_reason": "Directly studies automated session hijacking detection.",
        "relevance_confidence": 0.94,
    }
    values.update(overrides)
    return ClassificationResult.model_validate(values)


def test_classification_schema_normalizes_duplicate_labels() -> None:
    result = valid_classification()
    assert result.tags == ["Session Hijacking", "Cookie Security"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("primary_category", "Malware"), ("relevance", "D"), ("relevance_confidence", 1.2)],
)
def test_classification_schema_rejects_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        valid_classification(**{field: value})


def test_classification_schema_forbids_unexpected_fields() -> None:
    with pytest.raises(ValidationError):
        valid_classification(secret="unexpected")
