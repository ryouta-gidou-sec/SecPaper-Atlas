"""Loopback-only Ollama JSON Schema classification with bounded validation retry."""

from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlsplit

import httpx

from src.classifier import (
    ClassificationError, classification_messages, classification_schema,
    validate_classification_json,
)
from src.models import ClassificationResult


def local_endpoint(base_url: str) -> str:
    """Use a literal loopback address; reject credentials, proxies and URL paths."""
    try:
        parts = urlsplit(base_url)
        host = parts.hostname
        if host == "localhost":
            host = "127.0.0.1"
        if (
            parts.scheme != "http" or not host
            or not ipaddress.ip_address(host).is_loopback
            or parts.username is not None or parts.password is not None
            or parts.path not in ("", "/") or parts.query or parts.fragment
        ):
            raise ValueError
        port = parts.port or 11434
        host = f"[{host}]" if ":" in host else host
        return f"http://{host}:{port}"
    except ValueError:
        raise ClassificationError("LOCAL_LLM_BASE_URL must be an HTTP loopback endpoint") from None


class OllamaClassifier:
    provider = "local"

    def __init__(
        self, model: str, base_url: str = "http://127.0.0.1:11434", *,
        timeout: float = 180, validation_retries: int = 1,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        endpoint = local_endpoint(base_url)
        if not model.strip():
            raise ClassificationError("LOCAL_LLM_MODEL is not configured")
        if "cloud" in model.casefold() or "://" in model:
            raise ClassificationError("Local provider requires a locally installed model")
        if not 0 <= validation_retries <= 1 or not 1 <= timeout <= 600:
            raise ClassificationError("Invalid local timeout or validation retry limit")
        self.model = model.strip()
        self.validation_retries = validation_retries
        self.client = httpx.Client(
            base_url=endpoint, timeout=timeout, trust_env=False,
            follow_redirects=False, transport=transport,
        )
        self._model_checked = False

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = self.client.post(path, json=payload)
            if response.status_code == 404:
                raise ClassificationError("Local model is not installed; install it explicitly")
            if response.status_code >= 300:
                raise ClassificationError(f"Ollama request failed (HTTP {response.status_code})")
            result = response.json()
            if not isinstance(result, dict):
                raise ClassificationError("Ollama returned an invalid response envelope")
            return result
        except ClassificationError:
            raise
        except Exception as exc:
            raise ClassificationError(
                f"Ollama request failed ({exc.__class__.__name__})"
            ) from exc

    def check_available(self) -> None:
        """Read model metadata before disclosing any paper text to Ollama."""
        if self._model_checked:
            return
        info = self._post("/api/show", {"model": self.model})
        if info.get("remote_host") or info.get("remote_model"):
            raise ClassificationError("Ollama cloud models are forbidden by the local provider")
        if not isinstance(info.get("details"), dict) or not info.get("model_info"):
            raise ClassificationError("Ollama could not confirm a locally installed model")
        self._model_checked = True

    def classify(
        self, *, title: str | None, abstract: str | None, keywords: list[str],
        introduction_excerpt: str | None = None,
    ) -> ClassificationResult:
        messages = classification_messages(
            title=title, abstract=abstract, keywords=keywords,
            introduction_excerpt=introduction_excerpt,
        )
        self.check_available()
        schema = classification_schema()
        messages[0]["content"] += "\nReturn only JSON matching this schema:\n" + json.dumps(schema)
        for attempt in range(self.validation_retries + 1):
            response = self._post("/api/chat", {
                "model": self.model, "messages": messages, "format": schema,
                "stream": False, "think": False,
                "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1024},
            })
            try:
                if response.get("done") is not True or response.get("done_reason") == "length":
                    raise ValueError("Incomplete generation")
                content = response["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("Missing JSON content")
                return validate_classification_json(content)
            except (ValueError, KeyError, TypeError):
                if attempt == self.validation_retries:
                    raise ClassificationError("Ollama classification failed (JSON/schema validation)") from None
                # No fence removal, field repair, or invalid answer echoing.
                messages.append({
                    "role": "user",
                    "content": "The response failed validation. Generate a complete JSON object with all schema fields and valid types.",
                })
        raise AssertionError("Unreachable")

    def close(self) -> None:
        self.client.close()
