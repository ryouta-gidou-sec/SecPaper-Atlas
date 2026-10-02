from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.classifier import (
    ClassificationError,
    PaperClassifier,
    build_classification_payload,
    classification_messages,
)


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
    result = classifier.classify(
        title="A Valid Paper About Authorization",
        abstract="This study evaluates authorization failures across applications and reports its findings. "
        * 2,
        keywords=["IDOR"],
    )
    assert result.primary_category.value == "Authorization"
    assert completions.last_kwargs["response_format"].__name__ == "ClassificationResult"


def test_classifier_sanitizes_provider_errors() -> None:
    completions = FakeCompletions(error=RuntimeError("request included a secret and paper text"))
    classifier = PaperClassifier(None, "test-model", client=fake_client(completions))
    with pytest.raises(ClassificationError, match=r"RuntimeError") as error:
        classifier.classify(
            title="A Valid Paper About Authorization",
            abstract="This study evaluates authorization failures across applications and reports its findings. "
            * 2,
            keywords=[],
        )
    assert "secret" not in str(error.value)


def test_classifier_blocks_bad_metadata_before_client_call() -> None:
    completions = FakeCompletions()
    classifier = PaperClassifier(None, "test-model", client=fake_client(completions))
    with pytest.raises(ClassificationError, match="metadata review"):
        classifier.classify(
            title="reprinted from: random document",
            abstract="This abstract is long enough but is paired with a bad title. " * 4,
            keywords=[],
        )
    assert completions.last_kwargs == {}


def test_payload_uses_introduction_only_when_abstract_missing() -> None:
    with_abstract = build_classification_payload(
        title="T", abstract="A", keywords=[], introduction_excerpt="I"
    )
    without_abstract = build_classification_payload(
        title="T", abstract=None, keywords=[], introduction_excerpt="I"
    )
    assert "introduction_excerpt" not in with_abstract
    assert without_abstract["introduction_excerpt"] == "I"


@pytest.fixture
def classification_policy() -> str:
    messages = classification_messages(
        title="Evidence-based Web Security Evaluation",
        abstract="This study evaluates web security using explicit test conditions and reports results. "
        * 2,
        keywords=["Web Security"],
    )
    assert messages[0]["role"] == "system"
    return " ".join(messages[0]["content"].split())


@pytest.mark.parametrize(
    "required_rule",
    [
        "Research methods: require explicit evidence in the abstract, or only when it is missing, "
        "the introduction excerpt.",
        "Title or keywords alone do not establish a method.",
        "Browser Automation: require explicit automated browser operations, a browser automation "
        "framework, or automated browser interaction.",
        "Merely interacting with a web application, sending HTTP requests, using a browser "
        "extension, or manipulating cookies is insufficient.",
        "Black-box Testing: require an explicit statement or clear description of testing through "
        "external interfaces without using the target's source code or internal state/instrumentation.",
        "Automated testing, a scanner, or sending HTTP requests alone is insufficient.",
        "Experimental Study: require actual tests of a proposed method or hypothesis on test cases, "
        "applications, datasets, or services, with test conditions and reported results.",
        "Tool Development: require explicit development/implementation of a proposed tool, "
        "prototype, framework, platform, or system.",
        "Attack Simulation: require reproducing, executing, or simulating actual attacks or "
        "attack steps and checking success/failure.",
        "Automated Detection and Vulnerability Scanner are tags, not research methods in Rubric v1.",
        "Target vulnerabilities: include only specific vulnerability classes directly detected, "
        "evaluated, attacked, defended against, or measured by the paper, with explicit evidence "
        "in the abstract or its substitute introduction excerpt.",
        "Do not infer additional vulnerabilities from attack consequences or background descriptions.",
        "Session Fixation enabling session hijacking does not establish Session Hijacking as an "
        "independent target vulnerability.",
        "Web Application Vulnerabilities is a generic label, not a specific vulnerability class.",
        "A: the main subject/contribution directly addresses Session Management, Session Fixation, "
        "or Session Hijacking, or provides a concrete method directly usable to test/evaluate them.",
        "A general method qualifies for A only if all three conditions hold:",
        "those steps apply directly without designing a new model or detector specific to the "
        "target vulnerability.",
        "B: related security research or transferable methods/insights without that direct contribution",
        "Shared automated testing, Web Security, scanner, black-box, or AI terminology alone "
        "does not justify A.",
        "do not use a fixed default such as 0.95.",
        "Choose relevance_confidence according to evidence strength and classification certainty;",
        "Do not add background-only concepts, generic labels, parent concepts, or attack "
        "consequences without independent evidence.",
    ],
)
def test_shared_prompt_preserves_rubric_v1_rules(
    classification_policy: str, required_rule: str,
) -> None:
    assert required_rule in classification_policy


def test_primary_category_prioritizes_objective_over_evaluation_results(
    classification_policy: str,
) -> None:
    priorities = [
        "1. Main research objective.",
        "2. Security subject directly handled by the proposed approach.",
        "3. Main contribution.",
        "4. Experimental/evaluation results.",
    ]
    positions = [classification_policy.index(rule) for rule in priorities]
    assert positions == sorted(positions)


@pytest.mark.parametrize(
    "required_rule",
    [
        "When a specific security subject is central, prefer Authentication, Session Management, "
        "Authorization, Token Security, OAuth / OIDC / SSO, or Account Management, as appropriate, "
        "even when vulnerability detection/testing is used as a method.",
        "Discovering vulnerabilities only as an evaluation result does not justify "
        "Vulnerability Assessment.",
        "Choose Vulnerability Assessment when vulnerability assessment, scanning, detection, or "
        "security testing itself is the main research objective and no more specific category "
        "above is the central theme; for example, SQL Injection diagnosis or detection of multiple "
        "web vulnerability classes as the main objective.",
    ],
)
def test_primary_category_prompt_distinguishes_subject_methods_and_results(
    classification_policy: str, required_rule: str,
) -> None:
    assert required_rule in classification_policy
