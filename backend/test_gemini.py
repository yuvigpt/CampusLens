"""
CampusLens - Gemini smoke test (throwaway diagnostic script).

Purpose
-------
Prove that the backend can send ONE image + a complaint description to Gemini
and get back structured JSON with the fields CampusLens needs.

This script does NOT touch the database and does NOT import any app code.

Usage (run from the project root, C:\\Users\\yuvig\\Campuslens):

    backend\\venv\\Scripts\\python.exe backend\\test_gemini.py <image-path> <complaint description>

Example:

    backend\\venv\\Scripts\\python.exe backend\\test_gemini.py "Screenshot 2026-10-02 232442.png" "Broken fan in Block C computer lab"

The API key is read from backend/.env and is NEVER printed.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "gemini-2.5-flash"
REQUEST_TIMEOUT_MS = 60_000        # Gemini can take a few seconds; be generous.
TEMPERATURE = 0.2                  # Low = stable, repeatable classifications.
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB guard: fail fast instead of at the API.

ALLOWED_LEVELS = ("Low", "Medium", "High")
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

# backend/ is this file's folder. .env sits right next to it.
BACKEND_DIR = Path(__file__).resolve().parent
ENV_PATH = BACKEND_DIR / ".env"


class Analysis(BaseModel):
    """Exactly the seven fields CampusLens needs Gemini to return."""

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


REQUIRED_FIELDS = tuple(Analysis.model_fields.keys())
TEXT_FIELDS = (
    "category",
    "issue_summary",
    "evidence_from_image",
    "uncertainty_or_missing_information",
)
LEVEL_FIELDS = ("safety_risk", "functional_impact", "urgency")


def redact(text: str, *secrets: str) -> str:
    """Safety net so an API key can never surface in an error message.

    Gemini/Auth errors sometimes echo the full request URL, which may contain
    the key as a query parameter, so we scrub that pattern too.
    """
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "***REDACTED***")
    return re.sub(r"(key=)[^&\s]+", r"\1***REDACTED***", text, flags=re.IGNORECASE)


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send one image + a complaint description to Gemini and print the structured JSON it returns.",
    )
    parser.add_argument("image", help="Path to the complaint photo (jpg, jpeg, png or webp).")
    parser.add_argument(
        "description",
        nargs="+",
        help="The complaint description (quotes optional).",
    )
    return parser.parse_args()


def load_image(path_str: str) -> tuple[bytes, str]:
    """Read the image and work out its MIME type. Raises ValueError with a friendly message."""
    path = Path(path_str)
    if not path.is_absolute():
        # Relative paths are resolved against the current working directory,
        # which is why the command is documented to run from the project root.
        path = (Path.cwd() / path).resolve()

    if not path.is_file():
        raise ValueError(f"Image not found: {path}")

    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type == "image/jpg":            # some systems report this non-standard value
        mime_type = "image/jpeg"
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError(
            f"Unsupported image type for '{path.name}' "
            f"(detected: {mime_type or 'unknown'}). "
            f"Supported: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}"
        )

    data = path.read_bytes()
    if not data:
        raise ValueError(f"Image file is empty: {path}")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image is too large ({len(data) / (1024 * 1024):.1f} MB). "
            f"Limit is {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
        )
    return data, mime_type


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------
def build_prompt(description: str) -> str:
    return (
        "You are the analysis engine for CampusLens, a campus complaint triage system "
        "used by university facility staff.\n\n"
        "A student has submitted the complaint below, with an attached photo.\n\n"
        f'STUDENT DESCRIPTION:\n"""{description}"""\n\n'
        "Analyse the photo and the description together, then classify the complaint.\n\n"
        "Rules:\n"
        "- Judge safety_risk, functional_impact and urgency from what you can actually see "
        "and read. Be conservative: do not invent hazards that are not evident.\n"
        "- If the photo does not clearly show the described problem, say so in "
        "evidence_from_image and list what is unclear in "
        "uncertainty_or_missing_information.\n"
        "- Use 'Low', 'Medium' or 'High' exactly (capitalised) for the three levels.\n"
        "- Return JSON only, matching the given schema."
    )


def call_gemini(api_key: str, model: str, image_bytes: bytes, mime_type: str, description: str) -> str:
    """Send the multimodal request. Returns the raw response text. Raises on failure."""
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
    )

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            build_prompt(description),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Analysis,   # constrains Gemini to our exact fields + enum values
            temperature=TEMPERATURE,
        ),
    )
    return response.text or ""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate(payload: Any) -> tuple[list[str], list[str]]:
    """Check the returned JSON against the seven-field contract.

    Returns (problems, warnings). Problems mean the contract was broken;
    warnings are informational only.
    """
    problems: list[str] = []
    warnings: list[str] = []

    if not isinstance(payload, dict):
        return [f"top-level JSON is {type(payload).__name__}, expected an object"], warnings

    for field in REQUIRED_FIELDS:
        if field not in payload:
            problems.append(f"missing field: {field}")

    for field in TEXT_FIELDS:
        if field in payload:
            value = payload[field]
            if not isinstance(value, str) or not value.strip():
                problems.append(f"field '{field}' must be a non-empty string")

    for field in LEVEL_FIELDS:
        if field in payload:
            value = payload[field]
            if value not in ALLOWED_LEVELS:
                problems.append(
                    f"field '{field}' must be one of {list(ALLOWED_LEVELS)}, got {value!r}"
                )

    unexpected = sorted(set(payload) - set(REQUIRED_FIELDS))
    if unexpected:
        warnings.append(f"extra field(s) not in our schema: {', '.join(unexpected)}")

    return problems, warnings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    # Gemini may return non-ASCII text; keep the Windows console from raising.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = parse_args()
    description = " ".join(args.description).strip()

    print("=== CampusLens - Gemini smoke test ===")

    # --- 1. Load backend/.env (the key itself is never printed) ---
    load_dotenv(ENV_PATH)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Config error  : GEMINI_API_KEY was not found in backend/.env")
        print("Fix           : open backend/.env and set GEMINI_API_KEY=<your key>")
        return 2

    model = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    print(f"Model         : {model}")

    if not description:
        print("Config error  : the complaint description is empty.")
        return 2

    # --- 2. Read the image ---
    try:
        image_bytes, mime_type = load_image(args.image)
    except ValueError as exc:
        print(f"Input error   : {exc}")
        return 2

    print(f"Image         : {Path(args.image).name} ({mime_type}, {len(image_bytes) / 1024:.1f} KB)")
    print(f"Description   : {description}")
    print("Calling Gemini ...")

    # --- 3. Call Gemini ---
    started = time.perf_counter()
    try:
        raw_text = call_gemini(api_key, model, image_bytes, mime_type, description)
    except Exception as exc:
        print("Status        : FAILURE")
        print(f"Elapsed       : {time.perf_counter() - started:.1f}s")
        print(f"Error type    : {type(exc).__name__}")
        print(f"Error message : {redact(str(exc), api_key)}")
        return 1

    elapsed = time.perf_counter() - started

    # --- 4. Parse the JSON ---
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print("Status        : FAILURE")
        print(f"Elapsed       : {elapsed:.1f}s")
        print("Reason        : Gemini did not return valid JSON.")
        print(f"Details       : {exc}")
        print("Raw response (first 800 chars):")
        print(raw_text[:800])
        return 1

    # --- 5. Validate the JSON ---
    problems, warnings = validate(payload)

    print(f"Status        : {'SUCCESS' if not problems else 'FAILURE'}")
    print(f"Elapsed       : {elapsed:.1f}s")
    print(f"Validation    : {'OK - all 7 fields present, enums valid' if not problems else 'FAILED'}")
    for warning in warnings:
        print(f"  warning     : {warning}")
    for problem in problems:
        print(f"  problem     : {problem}")

    print()
    print("--- Analysis returned by Gemini ---")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())