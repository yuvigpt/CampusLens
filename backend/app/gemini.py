"""
CampusLens - Gemini image + text analysis.

Wraps the approach already proven by backend/test_gemini.py (which succeeded
with gemini-3.8-flash and validated all seven fields), and turns it into a
reusable function that NEVER raises at the caller.

What this module does
---------------------
* Reads the complaint photo + description and asks Gemini for seven fields.
* Validates what comes back before treating it as a success.
* Returns either the validated analysis or a readable error.

What this module deliberately does NOT do
-----------------------------------------
* No priority scoring and no category weights  -> that is app/priority.py.
* No storing of complaints and no SQLite        -> that is app/database.py.
* No FastAPI imports, so it can be tested on its own.

Error safety
------------
Every failure (missing key, bad image, network problem, unknown model,
malformed JSON, invalid field values) is converted into an AnalysisResult with
ok=False and a readable `error`. The API key is scrubbed from every message by
redact(), so it can never leak into logs or a 500 response.

Return format (what the future API should use)
----------------------------------------------
    analyze_complaint(image_path, description, *, api_key=None, model=None,
                      timeout_ms=REQUEST_TIMEOUT_MS) -> AnalysisResult

`AnalysisResult` is a frozen dataclass:

    ok              bool            True only when all seven fields validated
    analysis        dict | None     the 7 canonical fields when ok, else None
    error           str | None      readable, redacted message when not ok
    error_kind      str | None      'config' | 'input' | 'image' | 'api' | 'validation'
    model           str             the model actually used
    elapsed_seconds float           wall-clock time for the whole call
    warnings        tuple[str, ...] non-fatal notes (e.g. unexpected extra fields)
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "gemini-3.8-flash"
REQUEST_TIMEOUT_MS = 90_000        # Gemini can take a few seconds; be generous.
TEMPERATURE = 0.2                  # Low = stable, repeatable classifications.
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB guard: fail fast instead of at the API.

ALLOWED_LEVELS: tuple[str, ...] = ("Low", "Medium", "High")
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

# Derived from THIS file (app/ -> backend/), so the current working directory
# never matters when locating backend/.env.
BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BACKEND_DIR / ".env"

# error_kind values
ERROR_CONFIG = "config"          # missing API key / credentials
ERROR_INPUT = "input"            # bad arguments from the caller
ERROR_IMAGE = "image"            # missing, empty, oversized or unsupported image
ERROR_API = "api"                # network, auth, quota, unknown model, SDK error
ERROR_VALIDATION = "validation"  # response was not usable JSON / failed validation


class Analysis(BaseModel):
    """Exactly the seven fields CampusLens needs Gemini to return.

    Identical to the schema validated in the smoke test.
    """

    category: str = Field(
        description=(
            "Single best-fitting complaint category. Prefer one of: Electrical, "
            "Plumbing, Cleanliness, Infrastructure, Safety, WiFi/IT, Furniture, Other."
        )
    )
    issue_summary: str = Field(
        description="One short sentence describing the physical problem (max ~20 words)."
    )
    safety_risk: Literal["Low", "Medium", "High"] = Field(
        description="Risk of injury to people if this is left alone."
    )
    functional_impact: Literal["Low", "Medium", "High"] = Field(
        description="How much normal campus activity this disrupts."
    )
    urgency: Literal["Low", "Medium", "High"] = Field(
        description="How soon someone should act on this."
    )
    evidence_from_image: str = Field(
        description="What is actually visible in the photo that supports your classification."
    )
    uncertainty_or_missing_information: str = Field(
        description="What you cannot determine from this image and text. Use 'none' if nothing is missing."
    )


REQUIRED_FIELDS: tuple[str, ...] = tuple(Analysis.model_fields.keys())
TEXT_FIELDS: tuple[str, ...] = (
    "category",
    "issue_summary",
    "evidence_from_image",
    "uncertainty_or_missing_information",
)
LEVEL_FIELDS: tuple[str, ...] = ("safety_risk", "functional_impact", "urgency")


@dataclass(frozen=True)
class AnalysisResult:
    """The outcome of analysing one complaint. This is what the API receives."""

    ok: bool
    analysis: Optional[dict[str, Any]]      # the 7 canonical fields, or None
    error: Optional[str]                    # readable + redacted, or None
    error_kind: Optional[str]               # one of the ERROR_* values, or None
    model: str
    elapsed_seconds: float
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Flat, JSON-serializable view for an API response."""
        return {
            "ok": self.ok,
            "model": self.model,
            "analysis": self.analysis,
            "error": self.error,
            "error_kind": self.error_kind,
            "warnings": list(self.warnings),
            "elapsed_seconds": self.elapsed_seconds,
        }


class AnalysisFailure(Exception):
    """Internal signal used by the helpers in this module.

    Caught by analyze_complaint() and converted into an AnalysisResult, so it
    never reaches the caller.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------
def redact(text: str, *secrets: str) -> str:
    """Safety net so an API key can never surface in an error message.

    Gemini/Auth errors sometimes echo the full request URL, which may contain
    the key as a query parameter, so that pattern is scrubbed too.
    """
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "***REDACTED***")
    return re.sub(r"(key=)[^&\s]+", r"\1***REDACTED***", text, flags=re.IGNORECASE)


def _canonical(value: str) -> str:
    """'  high ' -> 'High'; 'MODERATE' -> 'Moderate'.

    Same normalization the rest of the codebase uses (database._validate_level
    and priority._canonical). It is normalization, never a fallback: an
    unrecognised word is always rejected.
    """
    return value.strip().title()


# ---------------------------------------------------------------------------
# Configuration resolution
# ---------------------------------------------------------------------------
def load_env_file() -> bool:
    """Load backend/.env into os.environ. Returns True if the file was found.

    The path is derived from this file's location, so the result is the same no
    matter which directory the process was started from. Real environment
    variables are NOT overwritten (override=False), so a shell-provided
    GEMINI_API_KEY / GEMINI_MODEL still wins during deployment.
    """
    if not ENV_PATH.is_file():
        return False
    return bool(load_dotenv(ENV_PATH, override=False))


def _resolve_model(explicit: Optional[str] = None) -> str:
    """Pick the model: explicit argument, then GEMINI_MODEL, then the default."""
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    load_env_file()
    return os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL


def _resolve_api_key(explicit: Optional[str] = None) -> str:
    """Return the API key, or raise AnalysisFailure(ERROR_CONFIG).

    The key is returned to the caller but is never printed here.
    """
    if explicit and str(explicit).strip():
        return str(explicit).strip()

    load_env_file()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise AnalysisFailure(
            ERROR_CONFIG,
            "GEMINI_API_KEY is not set. Add it to backend/.env as "
            "GEMINI_API_KEY=<your key>.",
        )
    return key


def _require_description(description: Any) -> str:
    """Validate the caller's complaint text."""
    if not isinstance(description, str) or not description.strip():
        raise AnalysisFailure(
            ERROR_INPUT, "The complaint description is empty."
        )
    return description.strip()


# ---------------------------------------------------------------------------
# Image loading (same rules as the smoke test)
# ---------------------------------------------------------------------------
def load_image(path_str: Any) -> tuple[bytes, str]:
    """Read an image and work out its MIME type.

    Returns (bytes, mime_type). Raises AnalysisFailure(ERROR_IMAGE) with a
    friendly message for anything the caller can act on.
    """
    if not isinstance(path_str, (str, os.PathLike)):
        raise AnalysisFailure(ERROR_IMAGE, "An image path must be provided.")

    path = Path(path_str)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()

    if not path.is_file():
        raise AnalysisFailure(ERROR_IMAGE, f"Image not found: {path}")

    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type == "image/jpg":            # some systems report this non-standard value
        mime_type = "image/jpeg"
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise AnalysisFailure(
            ERROR_IMAGE,
            f"Unsupported image type for '{path.name}' "
            f"(detected: {mime_type or 'unknown'}). "
            f"Supported: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}",
        )

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise AnalysisFailure(ERROR_IMAGE, f"Could not read image '{path.name}': {exc}") from exc

    if not data:
        raise AnalysisFailure(ERROR_IMAGE, f"Image file is empty: {path}")
    if len(data) > MAX_IMAGE_BYTES:
        raise AnalysisFailure(
            ERROR_IMAGE,
            f"Image is too large ({len(data) / (1024 * 1024):.1f} MB). "
            f"Limit is {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
        )
    return data, mime_type


# ---------------------------------------------------------------------------
# Prompt (extends the smoke test's wording with explicit contradiction rules)
# ---------------------------------------------------------------------------
def build_prompt(description: str) -> str:
    """Build the analysis prompt.

    The rules keep the model honest: it must separate what it can SEE from what
    is only CLAIMED, must flag contradictions, and must not invent evidence.
    """
    return (
        "You are the analysis engine for CampusLens, a campus complaint triage "
        "system used by university facility staff.\n\n"
        "A student has submitted the complaint below, together with an attached "
        "photo.\n\n"
        f'STUDENT DESCRIPTION:\n"""{description}"""\n\n'
        "Analyse the photo AND the description, then classify the complaint.\n\n"
        "Rules:\n"
        "1. Separate what you can SEE from what is only CLAIMED. evidence_from_image "
        "may contain ONLY details that are directly visible in the photo. Never "
        "describe anything you cannot actually see.\n"
        "2. If the photo contradicts the description (for example the described "
        "damage is not present, or the photo shows a different object or area than "
        "described), state that contradiction explicitly in "
        "uncertainty_or_missing_information.\n"
        "3. Do not invent, assume or embellish evidence. Absence of evidence is not "
        "evidence of absence: if the image cannot verify the complaint, say so "
        "plainly. Use 'none' in uncertainty_or_missing_information only when there "
        "genuinely is nothing uncertain.\n"
        "4. Judge safety_risk, functional_impact and urgency conservatively, using "
        "only what is visible or read. Do not upgrade severity to sound helpful.\n"
        "5. If the image is unusable (too dark, blurry, unrelated, or shows no "
        "problem), still return every field, keep the levels low, and explain why "
        "in uncertainty_or_missing_information.\n"
        "6. Use 'Low', 'Medium' or 'High' exactly (capitalised) for the three "
        "levels.\n"
        "7. Return JSON only, matching the given schema."
    )


# ---------------------------------------------------------------------------
# The Gemini request
# ---------------------------------------------------------------------------
def call_gemini(
    *,
    api_key: str,
    model: str,
    image_bytes: bytes,
    mime_type: str,
    description: str,
    timeout_ms: int = REQUEST_TIMEOUT_MS,
) -> str:
    """Perform the real multimodal request and return the raw response text.

    This is the ONLY function in the module that talks to the network. Tests
    replace it with a stub, so no test ever spends API quota.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout_ms),
    )

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            build_prompt(description),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Analysis,   # constrains Gemini to our fields + enum values
            temperature=TEMPERATURE,
        ),
    )
    return response.text or ""


# ---------------------------------------------------------------------------
# Validation of what came back
# ---------------------------------------------------------------------------
def validate_analysis(payload: Any) -> tuple[Optional[dict[str, Any]], list[str], list[str]]:
    """Check a parsed JSON payload against the seven-field contract.

    Returns (cleaned, problems, warnings):
        cleaned  the seven fields with normalized values, or None if invalid
        problems serious issues that make the analysis unusable
        warnings non-fatal notes (e.g. unexpected extra fields)

    Levels are normalized for case/whitespace and then must be exact, matching
    database._validate_level and priority._canonical.
    """
    problems: list[str] = []
    warnings: list[str] = []

    if not isinstance(payload, dict):
        return None, [f"top-level JSON is {type(payload).__name__}, expected an object"], warnings

    for name in REQUIRED_FIELDS:
        if name not in payload:
            problems.append(f"missing field: {name}")

    cleaned: dict[str, Any] = {}

    for name in TEXT_FIELDS:
        if name in payload:
            value = payload[name]
            if not isinstance(value, str) or not value.strip():
                problems.append(f"field '{name}' must be a non-empty string")
            else:
                cleaned[name] = value.strip()

    for name in LEVEL_FIELDS:
        if name in payload:
            value = payload[name]
            if not isinstance(value, str) or _canonical(value) not in ALLOWED_LEVELS:
                problems.append(
                    f"field '{name}' must be one of {list(ALLOWED_LEVELS)}, got {value!r}"
                )
            else:
                cleaned[name] = _canonical(value)

    unexpected = sorted(set(payload) - set(REQUIRED_FIELDS))
    if unexpected:
        warnings.append(f"extra field(s) not in our schema: {', '.join(unexpected)}")

    if problems:
        return None, problems, warnings

    ordered = {name: cleaned[name] for name in REQUIRED_FIELDS}
    return ordered, problems, warnings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def _failure(
    kind: str,
    message: str,
    model_name: str,
    started_at: float,
    secret: str = "",
) -> AnalysisResult:
    """Build a failed result. The message is always redacted before it is stored."""
    return AnalysisResult(
        ok=False,
        analysis=None,
        error=redact(str(message), secret),
        error_kind=kind,
        model=model_name,
        elapsed_seconds=round(time.perf_counter() - started_at, 2),
    )


def analyze_complaint(
    image_path: Any,
    description: Any,
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    timeout_ms: int = REQUEST_TIMEOUT_MS,
) -> AnalysisResult:
    """Analyse one complaint photo + description with Gemini.

    Args:
        image_path: path to the complaint photo (jpg, jpeg, png or webp).
        description: the student's complaint text.
        api_key: optional override; otherwise GEMINI_API_KEY from backend/.env
            or the real environment is used.
        model: optional override; otherwise GEMINI_MODEL, then DEFAULT_MODEL.
        timeout_ms: request timeout in milliseconds.

    Returns:
        AnalysisResult. This function NEVER raises - every failure comes back as
        ok=False with a readable, redacted `error` and an `error_kind`.
    """
    model_name = _resolve_model(model)
    started_at = time.perf_counter()
    secret = ""                      # bound early so error paths can redact

    try:
        secret = _resolve_api_key(api_key)
        description_text = _require_description(description)
        image_bytes, mime_type = load_image(image_path)

        raw_text = call_gemini(
            api_key=secret,
            model=model_name,
            image_bytes=image_bytes,
            mime_type=mime_type,
            description=description_text,
            timeout_ms=timeout_ms,
        )

        try:
            payload = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AnalysisFailure(
                ERROR_VALIDATION, f"Gemini did not return valid JSON: {exc}"
            ) from exc

        cleaned, problems, warnings = validate_analysis(payload)
        if problems:
            raise AnalysisFailure(
                ERROR_VALIDATION,
                "Gemini response failed validation: " + "; ".join(problems),
            )

        return AnalysisResult(
            ok=True,
            analysis=cleaned,
            error=None,
            error_kind=None,
            model=model_name,
            elapsed_seconds=round(time.perf_counter() - started_at, 2),
            warnings=tuple(warnings),
        )

    except AnalysisFailure as exc:
        # Expected, actionable problems (config / input / image / validation).
        return _failure(exc.kind, exc.message, model_name, started_at, secret)

    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        # Anything unexpected: network error, auth failure, unknown model,
        # SDK bug, timeout. Converted so the caller is never crashed.
        return _failure(
            ERROR_API, f"{type(exc).__name__}: {exc}", model_name, started_at, secret
        )


# ---------------------------------------------------------------------------
# Manual use (real API call, for checking one image by hand):
#   backend\venv\Scripts\python.exe backend\app\gemini.py <image> <description...>
# ---------------------------------------------------------------------------
def _main(argv: Optional[list[str]] = None) -> int:
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Analyse one complaint image with Gemini.")
    parser.add_argument("image", help="Path to the complaint photo.")
    parser.add_argument("description", nargs="+", help="The complaint description.")
    args = parser.parse_args(argv)

    result = analyze_complaint(args.image, " ".join(args.description))

    print("=== CampusLens - Gemini analysis ===")
    print(f"Model    : {result.model}")
    print(f"Status   : {'SUCCESS' if result.ok else 'FAILURE'}")
    print(f"Elapsed  : {result.elapsed_seconds}s")
    if result.error:
        print(f"Kind     : {result.error_kind}")
        print(f"Error    : {result.error}")
    for warning in result.warnings:
        print(f"Warning  : {warning}")
    if result.analysis:
        print()
        print("--- Analysis ---")
        print(json.dumps(result.analysis, indent=2, ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(_main())