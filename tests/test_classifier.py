from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.classifier import ClassificationError, PaperClassifier, build_classification_payload


class FakeCompletions:
    def __init__(self, parsed: object = None, error: Exception | None = None) -> None:
        self.parsed = parsed
        self.error = error
        self.last_kwargs: dict[str, object] = {}

    def parse(self, **kwargs: object) -> object:
        self.last_kwargs = kwargs
        if self.error:
            raise self.error
        message = SimpleNamespace(parsed=self.parsed, refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def fake_client(completions: FakeCompletions) -> object:
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def test_classifier_validates_structured_result() -> None:
    completions = FakeCompletions(
        {
            "primary_category": "Authorization",
            "tags": ["IDOR"],
            "research_methods": ["Dynamic Analysis"],
            "target_vulnerabilities": ["IDOR"],
            "relevance": "B",
            "relevance_reason": "It evaluates authorization failures.",
            "relevance_confidence": 0.8,
        }
    )
    classifier = PaperClassifier(None, "test-model", client=fake_client(completions))
    result = classifier.classify(title="Paper", abstract="Abstract", keywords=["IDOR"])
    assert result.primary_category.value == "Authorization"
    assert completions.last_kwargs["response_format"].__name__ == "ClassificationResult"


def test_classifier_sanitizes_provider_errors() -> None:
    completions = FakeCompletions(error=RuntimeError("request included a secret and paper text"))
    classifier = PaperClassifier(None, "test-model", client=fake_client(completions))
    with pytest.raises(ClassificationError, match=r"RuntimeError") as error:
        classifier.classify(title="Paper", abstract="Abstract", keywords=[])
    assert "secret" not in str(error.value)


def test_payload_uses_introduction_only_when_abstract_missing() -> None:
    with_abstract = build_classification_payload(
        title="T", abstract="A", keywords=[], introduction_excerpt="I"
    )
    without_abstract = build_classification_payload(
        title="T", abstract=None, keywords=[], introduction_excerpt="I"
    )
    assert "introduction_excerpt" not in with_abstract
    assert without_abstract["introduction_excerpt"] == "I"
