from __future__ import annotations

import json

import httpx
import pytest

from src.classifier import ClassificationError
from src.ollama_classifier import OllamaClassifier, local_endpoint


PAPER = {
    "title": "A Study of Web Session Security",
    "abstract": "This study analyzes web session security and evaluates vulnerability detection. " * 3,
    "keywords": ["session", "認証"],
    "introduction_excerpt": "This excerpt must not be sent when an abstract exists.",
}
RESULT = {
    "primary_category": "Session Management", "tags": ["Session Hijacking"],
    "research_methods": ["Dynamic Analysis"], "target_vulnerabilities": ["Session Hijacking"],
    "relevance": "A", "relevance_reason": "Session security is directly relevant.",
    "relevance_confidence": 0.85,
}
SHOW = {"details": {"family": "qwen3"}, "model_info": {"general.architecture": "qwen3"}}


def local_mock(contents: list[str], *, show: dict | None = None):
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append((request.url, payload))
        if request.url.path == "/api/show":
            return httpx.Response(200, json=SHOW if show is None else show)
        content = contents.pop(0) if len(contents) > 1 else contents[0]
        return httpx.Response(200, json={"done": True, "message": {"content": content}})

    return OllamaClassifier("test-model", transport=httpx.MockTransport(handler)), calls


def test_local_provider_validates_json_and_minimizes_input():
    classifier, calls = local_mock([json.dumps(RESULT)])
    try:
        result = classifier.classify(**PAPER)
        assert result.primary_category.value == "Session Management"
        assert classifier.provider == "local"
        assert len(calls) == 2
        assert all(url.host == "127.0.0.1" for url, _ in calls)
        request = calls[1][1]
        assert request["stream"] is False
        assert request["format"]["additionalProperties"] is False
        assert set(request["format"]["required"]) == set(RESULT)
        payload = json.loads(request["messages"][1]["content"].split("Paper metadata:\n")[1])
        assert set(payload) == {"title", "abstract", "keywords"}
        assert "This excerpt" not in json.dumps(request)
        classifier.classify(**PAPER)
        assert [url.path for url, _ in calls].count("/api/show") == 1
    finally:
        classifier.close()


@pytest.mark.parametrize("content", [
    "not JSON", "```json\n{}\n```", "[]", "{}",
    json.dumps({**RESULT, "primary_category": "Invented"}),
    json.dumps({**RESULT, "relevance_confidence": "0.85"}),
    json.dumps({**RESULT, "extra": "value"}),
    json.dumps({key: value for key, value in RESULT.items() if key != "tags"}),
])
def test_invalid_json_or_schema_is_failed_after_one_retry(content):
    classifier, calls = local_mock([content])
    try:
        with pytest.raises(ClassificationError, match="JSON/schema validation"):
            classifier.classify(**PAPER)
        assert len(calls) == 3  # one preflight, at most two generations
    finally:
        classifier.close()


def test_validation_retry_can_return_a_new_valid_response():
    classifier, calls = local_mock(["invalid", json.dumps(RESULT)])
    try:
        assert classifier.classify(**PAPER).relevance.value == "A"
        assert len(calls) == 3
    finally:
        classifier.close()


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_local_connection_error_is_sanitized_without_retry(error_type):
    calls = []

    def handler(request):
        calls.append(request)
        raise error_type("secret and paper text must never surface", request=request)

    classifier = OllamaClassifier("test-model", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ClassificationError) as error:
            classifier.classify(**PAPER)
        assert "secret" not in str(error.value)
        assert error_type.__name__ in str(error.value)
        assert len(calls) == 1
    finally:
        classifier.close()


def test_model_not_installed_is_detected_before_paper_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404, json={"error": "model not found"})

    classifier = OllamaClassifier("missing-model", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ClassificationError, match="not installed"):
            classifier.classify(**PAPER)
        assert len(calls) == 1
        assert json.loads(calls[0].content) == {"model": "missing-model"}
    finally:
        classifier.close()


@pytest.mark.parametrize("show", [
    {**SHOW, "remote_host": "https://ollama.com"},
    {**SHOW, "remote_model": "remote-alias"}, {},
])
def test_cloud_alias_or_unknown_model_metadata_is_rejected(show):
    classifier, calls = local_mock([json.dumps(RESULT)], show=show)
    try:
        with pytest.raises(ClassificationError):
            classifier.classify(**PAPER)
        assert len(calls) == 1
    finally:
        classifier.close()


@pytest.mark.parametrize("url", [
    "https://ollama.com", "http://192.168.0.2:11434", "http://example.com",
    "http://user:secret@127.0.0.1:11434", "http://127.0.0.1/api", "http://127.0.0.1?x=1",
])
def test_local_endpoint_rejects_external_or_credential_urls(url):
    with pytest.raises(ClassificationError, match="loopback"):
        local_endpoint(url)


def test_localhost_is_resolved_to_literal_loopback():
    assert local_endpoint("http://localhost:11434/") == "http://127.0.0.1:11434"
    assert local_endpoint("http://[::1]:11434") == "http://[::1]:11434"


def test_local_quality_gate_precedes_all_requests():
    classifier, calls = local_mock([json.dumps(RESULT)])
    try:
        with pytest.raises(ClassificationError, match="metadata review"):
            classifier.classify(**{**PAPER, "title": "reprinted from: a journal"})
        assert calls == []
    finally:
        classifier.close()


def test_redirect_is_never_followed():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://example.com/"})

    classifier = OllamaClassifier("test-model", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ClassificationError, match="HTTP 307"):
            classifier.classify(**PAPER)
        assert len(calls) == 1
    finally:
        classifier.close()


def test_retry_limit_zero_and_invalid_limits():
    classifier, calls = local_mock(["invalid"])
    classifier.validation_retries = 0
    try:
        with pytest.raises(ClassificationError):
            classifier.classify(**PAPER)
        assert len(calls) == 2
    finally:
        classifier.close()
    with pytest.raises(ClassificationError):
        OllamaClassifier("test-model", validation_retries=2)
    with pytest.raises(ClassificationError):
        OllamaClassifier("")
    with pytest.raises(ClassificationError):
        OllamaClassifier("model:cloud")


def test_local_provider_mock_scan_validates_persists_and_keeps_hash(database, tmp_path, monkeypatch):
    import hashlib
    import logging
    from src.models import ExtractedMetadata
    from src.pdf_parser import ParsedPDF
    from src.scanner import scan_inbox

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic fixture")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr("src.scanner.parse_pdf", lambda *_: ParsedPDF("text", "title", {}, 1))
    monkeypatch.setattr("src.scanner.extract_metadata", lambda *_: ExtractedMetadata(**PAPER))
    classifier, calls = local_mock([json.dumps(RESULT)])
    try:
        kwargs = dict(inbox_dir=inbox, database=database, classifier=classifier, logger=logging.getLogger("test"))
        assert scan_inbox(**kwargs)[0].status == "Classified"
        assert scan_inbox(**kwargs)[0].status == "Skipped"
        paper = database.get_paper_by_hash(before)
        assert paper["classification_status"] == "classified"
        assert paper["classification_provider"] == "local"
        assert paper["classification_model"] == "test-model"
        assert paper["primary_category"] is None
        assert paper["ai_primary_category"] == "Session Management"
        assert len(calls) == 2
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    finally:
        classifier.close()


@pytest.mark.parametrize("done, reason", [(False, None), (True, "length")])
def test_incomplete_generation_is_not_accepted(done, reason):
    def handler(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json=SHOW)
        return httpx.Response(200, json={"done": done, "done_reason": reason, "message": {"content": json.dumps(RESULT)}})

    classifier = OllamaClassifier("test-model", validation_retries=0, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ClassificationError, match="JSON/schema validation"):
            classifier.classify(**PAPER)
    finally:
        classifier.close()
