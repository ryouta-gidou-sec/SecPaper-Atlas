"""OpenAI Structured Outputs boundary for paper classification."""

from __future__ import annotations

import json
from typing import Any

from src.models import (
    ClassificationResult,
    DEFAULT_TAGS,
    PrimaryCategory,
    RESEARCH_METHODS,
    enum_values,
)
from src.metadata_extractor import classification_input_issues


class ClassificationError(RuntimeError):
    """A safe, user-displayable classification failure."""


SYSTEM_PROMPT = """You classify cybersecurity research papers for literature triage.
Use only the supplied title, abstract, keywords, and optional introduction excerpt.
Do not infer bibliographic facts. Select exactly one primary category.
Tags and vulnerabilities may include concise new labels when necessary.
Relevance measures fit with authentication/authorization research exploration, not paper quality.
A: strongest fit, especially session management or hijacking/fixation combined with automated,
black-box, browser-based, or vulnerability assessment methods. B: useful authentication,
authorization, token, OAuth/OIDC, IDOR/BOLA work. C: security research outside those interests.
Keep the relevance reason factual and under 40 words."""


class PaperClassifier:
    """Classify minimal paper metadata using a Pydantic response schema."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        client: Any | None = None,
    ) -> None:
        if client is None:
            if not api_key:
                raise ClassificationError("OPENAI_API_KEY is not configured")
            try:
                from openai import OpenAI

                client = OpenAI(api_key=api_key)
            except Exception as exc:
                raise ClassificationError(
                    f"OpenAI client initialization failed ({exc.__class__.__name__})"
                ) from exc
        self.client = client
        self.model = model

    def classify(
        self,
        *,
        title: str | None,
        abstract: str | None,
        keywords: list[str],
        introduction_excerpt: str | None = None,
    ) -> ClassificationResult:
        """Return a schema-validated classification or a sanitized error."""

        issues = classification_input_issues(
            title=title,
            abstract=abstract,
            introduction_excerpt=introduction_excerpt,
        )
        if issues:
            raise ClassificationError("Classification held for metadata review")

        payload = build_classification_payload(
            title=title,
            abstract=abstract,
            keywords=keywords,
            introduction_excerpt=introduction_excerpt,
        )
        user_prompt = (
            "Allowed primary categories: "
            + ", ".join(enum_values(PrimaryCategory))
            + "\nPreferred tags (new concise tags are allowed): "
            + ", ".join(DEFAULT_TAGS)
            + "\nResearch methods: "
            + ", ".join(RESEARCH_METHODS)
            + "\nPaper metadata:\n"
            + json.dumps(payload, ensure_ascii=False)
        )
        try:
            completion = self.client.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=ClassificationResult,
            )
            message = completion.choices[0].message
            if getattr(message, "refusal", None):
                raise ClassificationError("The model refused the classification request")
            parsed = getattr(message, "parsed", None)
            if parsed is None:
                raise ClassificationError("The model returned no structured classification")
            return ClassificationResult.model_validate(parsed)
        except ClassificationError:
            raise
        except Exception as exc:
            # Do not surface provider payloads, prompts, paper text, or credentials.
            raise ClassificationError(
                f"OpenAI classification failed ({exc.__class__.__name__})"
            ) from exc


def build_classification_payload(
    *,
    title: str | None,
    abstract: str | None,
    keywords: list[str],
    introduction_excerpt: str | None,
) -> dict[str, Any]:
    """Build the intentionally small API payload used for one paper."""

    payload: dict[str, Any] = {
        "title": (title or "Unknown")[:500],
        "abstract": abstract[:6000] if abstract else None,
        "keywords": keywords[:30],
    }
    if not abstract and introduction_excerpt:
        payload["introduction_excerpt"] = introduction_excerpt[:2500]
    return payload
