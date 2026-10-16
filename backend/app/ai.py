"""
CampusLens - optional AI analysis.

This module is deliberately isolated so that NOTHING here can affect whether a
complaint is saved. The submission path calls the provider only AFTER the
complaint row is committed, and treats every outcome - success, HTTP 503,
timeout, malformed output - as non-fatal.

A returned analysis is a SUGGESTION. It is written only to the ``ai_*`` columns.
The scorer reads ``confirmed_*`` exclusively (see scoring.py), so no AI
response can change a score, a status or a public approval.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger("campuslens.ai")

REQUEST_TIMEOUT_SECONDS = 20.0
DEFAULT_MODEL = "gemini-2.5-flash"

MODEL_ENV_VAR = "GEMINI_MODEL"
API_KEY_ENV_VAR = "GEMINI_API_KEY"

_SECRET_LIKE = re.compile(r"eyJ[A-Za-z0-9._-]+")
_URL_LIKE = re.compile(r"https?://\S+", re.IGNORECASE)


class AnalysisUnavailable(RuntimeError):
    """The provider could not be reached or refused. Never fatal."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class AnalysisInvalid(AnalysisUnavailable):
    """The provider replied with something unusable."""


def redact(text: str, *secrets: Optional[str]) -> str:
    """Strip keys, JWTs and URLs so a failure reason can be stored safely."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return _URL_LIKE.sub("[redacted]", _SECRET_LIKE.sub("[redacted]", text))


def is_configured() -> bool:
    """True only when an API key is present."""
    import os

    return bool((os.environ.get(API_KEY_ENV_VAR) or "").strip())


def _normalise_level(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    candidate = value.strip().title()
    return candidate if candidate in {"Low", "Medium", "High"} else None


def parse_analysis(payload: Any) -> dict[str, Any]:
    """Validate a provider response into the ai_* column shape.

    Raises AnalysisInvalid when nothing usable can be extracted, so a partial
    or guessed suggestion is never stored.
    """
    if not isinstance(payload, dict):
        raise AnalysisInvalid("invalid", "AI returned an unusable response.")

    fields = {
        "ai_category": payload.get("category"),
        "ai_summary": payload.get("summary"),
        "ai_evidence": payload.get("evidence"),
        "ai_uncertainty": payload.get("uncertainty"),
    }

    urgency = _normalise_level(payload.get("urgency"))
    impact = _normalise_level(payload.get("impact"))
    safety = _normalise_level(payload.get("safety"))

    if not any(urgency or impact or safety or fields["ai_summary"]):
        raise AnalysisInvalid("invalid", "AI response contained no usable fields.")

    clean: dict[str, Any] = {}
    for key, value in fields.items():
        if isinstance(value, str) and value.strip():
            clean[key] = value.strip()[:4000]
    if urgency:
        clean["ai_urgency"] = urgency
    if impact:
        clean["ai_impact"] = impact
    if safety:
        clean["ai_safety"] = safety
    return clean


def analyse(*, description: str, image_bytes: Optional[bytes] = None,
            image_mime: Optional[str] = None) -> dict[str, Any]:
    """Ask the provider for a suggestion.

    Raises AnalysisUnavailable on ANY provider problem. Callers must catch it;
    the complaint has already been saved by then.
    """
    import os

    api_key = (os.environ.get(API_KEY_ENV_VAR) or "").strip()
    if not api_key:
        raise AnalysisUnavailable("not_configured", "AI provider is not configured.")

    model = (os.environ.get(MODEL_ENV_VAR) or "").strip() or DEFAULT_MODEL

    prompt = (
        "You help a university facilities team triage student complaints. "
        "Reply with JSON only, no prose. Use exactly these keys: "
        "category (short noun), summary (one sentence), evidence (what in the "
        "image or text supports this), uncertainty (what is missing), and "
        "urgency / impact / safety each exactly one of Low, Medium, High.\n\n"
        f"Complaint: {description}"
    )

    try:
        from google import genai
    except Exception:
        raise AnalysisUnavailable("unavailable", "AI provider SDK is not installed.") from None

    try:
        client = genai.Client(api_key=api_key)
        parts = [prompt]
        if image_bytes:
            mime = image_mime or "image/jpeg"
            parts.append({"inline_data": {"mime_type": mime, "data": image_bytes}})
        response = client.models.generate_content(model=model, contents=parts)
        text = getattr(response, "text", None) or ""
    except Exception as exc:
        # 503, timeouts, quota errors and anything else collapse into one
        # non-fatal failure. The class name only, never the message.
        logger.warning("AI provider call failed (%s)", type(exc).__name__)
        raise AnalysisUnavailable("provider", "AI provider is unavailable.") from None

    if not text.strip():
        raise AnalysisUnavailable("empty", "AI provider returned no content.")

    import json

    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise AnalysisInvalid("invalid", "AI response was not JSON.")

    try:
        payload = json.loads(text[start : end + 1])
    except ValueError:
        raise AnalysisInvalid("invalid", "AI response was not valid JSON.") from None

    return parse_analysis(payload)