"""Validated domain models shared by extraction, classification, and storage."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PrimaryCategory(str, Enum):
    AUTHENTICATION = "Authentication"
    SESSION_MANAGEMENT = "Session Management"
    AUTHORIZATION = "Authorization"
    TOKEN_SECURITY = "Token Security"
    OAUTH_OIDC_SSO = "OAuth / OIDC / SSO"
    ACCOUNT_MANAGEMENT = "Account Management"
    VULNERABILITY_ASSESSMENT = "Vulnerability Assessment"
    OTHER_SECURITY = "Other Security"


class Relevance(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class PaperStatus(str, Enum):
    UNREAD = "Unread"
    SCREENED = "Screened"
    READ = "Read"
    IMPORTANT = "Important"


DEFAULT_TAGS = (
    "Authentication",
    "Password",
    "MFA",
    "Passkey",
    "WebAuthn",
    "Session Management",
    "Cookie Security",
    "Session ID",
    "Session Hijacking",
    "Session Fixation",
    "Session Timeout",
    "Logout",
    "Session Revocation",
    "Concurrent Session",
    "Authorization",
    "Access Control",
    "IDOR",
    "BOLA",
    "Broken Access Control",
    "Horizontal Privilege Escalation",
    "Vertical Privilege Escalation",
    "JWT",
    "Access Token",
    "Refresh Token",
    "Token Leakage",
    "OAuth",
    "OpenID Connect",
    "SSO",
    "Password Reset",
    "Account Recovery",
    "Black-box Testing",
    "White-box Testing",
    "Automated Detection",
    "Vulnerability Scanner",
    "Browser Automation",
    "Attack Simulation",
)

RESEARCH_METHODS = (
    "Black-box Testing",
    "White-box Testing",
    "Static Analysis",
    "Dynamic Analysis",
    "Browser Automation",
    "Attack Simulation",
    "Measurement Study",
    "Formal Verification",
    "Machine Learning",
    "Survey",
    "Tool Development",
    "Experimental Study",
    "Empirical Study",
)


class ExtractedMetadata(BaseModel):
    """Metadata recovered locally from a PDF without AI inference."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1900, le=2100)
    venue: str | None = None
    abstract: str | None = None
    keywords: list[str] = Field(default_factory=list)
    introduction_excerpt: str | None = None
    metadata_sources: dict[str, str] = Field(default_factory=dict)

    @field_validator("title", "venue", "abstract", "introduction_excerpt")
    @classmethod
    def blank_strings_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @field_validator("authors", "keywords")
    @classmethod
    def clean_string_lists(cls, values: list[str]) -> list[str]:
        return _deduplicate(values)


class ClassificationResult(BaseModel):
    """Strict schema for the model response."""

    model_config = ConfigDict(extra="forbid")

    primary_category: PrimaryCategory
    tags: list[str] = Field(default_factory=list, max_length=30)
    research_methods: list[str] = Field(default_factory=list, max_length=20)
    target_vulnerabilities: list[str] = Field(default_factory=list, max_length=30)
    relevance: Relevance
    relevance_reason: str = Field(min_length=1, max_length=500)
    relevance_confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("tags", "research_methods", "target_vulnerabilities")
    @classmethod
    def clean_labels(cls, values: list[str]) -> list[str]:
        return _deduplicate(values)

    @field_validator("relevance_reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("relevance_reason must not be blank")
        return cleaned


def enum_values(enum_type: type[Enum]) -> list[str]:
    """Return user-facing values for a string enum."""

    return [str(item.value) for item in enum_type]


def _deduplicate(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value).split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result
