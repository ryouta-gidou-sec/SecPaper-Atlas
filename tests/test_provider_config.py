from dataclasses import replace

import pytest

from src.classifier import ClassificationError, create_classifier, PaperClassifier, OpenAIClassifier
from src.config import get_settings


def test_default_local_does_not_create_openai_client(tmp_path, monkeypatch):
    monkeypatch.delenv("CLASSIFIER_PROVIDER", raising=False)
    monkeypatch.setenv("LOCAL_LLM_MODEL", "configured-model")
    monkeypatch.setenv("OPENAI_API_KEY", "unused-test-secret")
    monkeypatch.setattr("src.classifier.OpenAIClassifier", lambda *_: pytest.fail("OpenAI must not be created"))
    settings = get_settings(tmp_path)
    classifier = create_classifier(settings)
    try:
        assert classifier.provider == "local"
        assert classifier.model == "configured-model"
        assert settings.classifier_model == "configured-model"
    finally:
        classifier.close()


def test_openai_provider_switch_preserves_existing_mock_contract(tmp_path, monkeypatch):
    settings = get_settings(tmp_path)
    captured = []
    sentinel = object()

    def factory(key, model):
        captured.append((key, model))
        return sentinel

    monkeypatch.setattr("src.classifier.OpenAIClassifier", factory)
    settings = replace(settings, classifier_provider="openai", openai_api_key="test-key", openai_model="mock-openai")
    assert create_classifier(settings) is sentinel
    assert captured == [("test-key", "mock-openai")]
    assert settings.classifier_model == "mock-openai"
    assert PaperClassifier is OpenAIClassifier


def test_settings_repr_never_exposes_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-never-display")
    assert "test-secret-never-display" not in repr(get_settings(tmp_path))


def test_invalid_provider_does_not_fall_back(tmp_path):
    with pytest.raises(ClassificationError, match="must be local or openai"):
        create_classifier(replace(get_settings(tmp_path), classifier_provider="invalid"))
