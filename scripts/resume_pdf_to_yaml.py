#!/usr/bin/env python3
"""Convert a final, edited resume PDF into canonical Resume Builder YAML.

The PDF is extracted locally. Contact information, the candidate name, page
footers, and the Education section are removed before the remaining resume text
is sent to Claude for semantic structuring. The resulting YAML intentionally
contains only: headline, summary_bullets, experience, and skills.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = ROOT / "data" / "resume_primary.yaml"
DEFAULT_MODEL = "claude-opus-4-8"
ROOT_KEYS = ["headline", "summary_bullets", "experience", "skills"]

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]\d{4}(?!\d)"
)
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/\S+", re.I)
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
EDUCATION_HEADING_RE = re.compile(r"^\s*education\s*$", re.I)
PAGE_FOOTER_RE = re.compile(r"^\s*.+?\s*\|\s*\d+\s*$")
ID_PATTERN = r"^[a-z][a-z0-9_]*$"


class ContentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    text: str = Field(min_length=1)


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_lines: list[str]
    dates: list[str]
    summary: ContentItem | None = None
    bullets: list[ContentItem] = Field(default_factory=list)


class Experience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str = Field(min_length=1)
    location: str | None = None
    positions: list[Position] = Field(min_length=1)


class Skills(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai: list[str]
    languages: list[str]
    tools: list[str]
    architecture_patterns: list[str]


class ResumeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1)
    summary_bullets: list[ContentItem]
    experience: list[Experience]
    skills: Skills


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract PDF text locally, preferring pypdf's layout mode."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - exercised by installation state
        raise RuntimeError(
            "pypdf is required. Install project dependencies with "
            "`.venv/bin/pip install -r requirements.txt`."
        ) from exc

    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text(extraction_mode="layout") or ""
        except TypeError:
            text = page.extract_text() or ""
        pages.append(text)
    return "\n\n".join(pages)


def _looks_like_name(line: str) -> bool:
    """Conservative heuristic for the first visible resume line."""
    value = " ".join(line.split())
    words = value.split()
    if not 2 <= len(words) <= 4 or len(value) > 60:
        return False
    if any(token in value for token in ("|", "@", ":", "/")):
        return False
    return all(word[:1].isupper() for word in words if word)


def sanitize_resume_text(text: str) -> str:
    """Remove content that must never appear in per-version YAML or model input."""
    lines = text.replace("\u00a0", " ").splitlines()

    education_index = next(
        (i for i, line in enumerate(lines) if EDUCATION_HEADING_RE.match(line)), None
    )
    if education_index is not None:
        lines = lines[:education_index]

    first_content = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first_content is not None and _looks_like_name(lines[first_content]):
        lines[first_content] = ""

    cleaned: list[str] = []
    for line in lines:
        if PAGE_FOOTER_RE.match(line):
            continue
        if (
            EMAIL_RE.search(line)
            or PHONE_RE.search(line)
            or LINKEDIN_RE.search(line)
            or URL_RE.search(line)
        ):
            continue
        cleaned.append(line.rstrip())

    result = "\n".join(cleaned)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()

    leaked = []
    if EMAIL_RE.search(result):
        leaked.append("email")
    if PHONE_RE.search(result):
        leaked.append("phone")
    if LINKEDIN_RE.search(result) or URL_RE.search(result):
        leaked.append("URL")
    if any(EDUCATION_HEADING_RE.match(line) for line in result.splitlines()):
        leaked.append("Education section")
    if leaked:
        raise ValueError("privacy sanitization failed for: " + ", ".join(leaked))
    return result


def load_reference(path: Path | None) -> str:
    if path is None:
        return ""
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"reference YAML is not a mapping: {path}")
    forbidden = {"contact", "education"} & set(data)
    if forbidden:
        raise ValueError(
            f"reference YAML contains forbidden keys {sorted(forbidden)}: {path}"
        )
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def request_resume_document(
    resume_text: str,
    reference_yaml: str,
    model: str,
) -> tuple[ResumeDocument, str]:
    """Ask Claude to transcribe the sanitized resume into the strict schema."""
    import anthropic

    prompt_path = ROOT / "prompts" / "resume_pdf_to_yaml.md"
    system_prompt = prompt_path.read_text()
    reference_block = reference_yaml or "No reference YAML was supplied."
    user_content = (
        f"<reference_resume>\n{reference_block}\n</reference_resume>\n\n"
        f"<sanitized_pdf_text>\n{resume_text}\n</sanitized_pdf_text>"
    )

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
        output_format=ResumeDocument,
    )
    document = response.parsed_output
    if document is None:
        raise RuntimeError("Claude returned no structured resume document")
    usage = response.usage
    usage_text = f"tokens in/out: {usage.input_tokens}/{usage.output_tokens}"
    return document, usage_text


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _wrap_text(value: str, width: int) -> list[str]:
    normalized = " ".join(value.split())
    return textwrap.wrap(
        normalized,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]


def _emit_text(lines: list[str], indent: int, value: str) -> None:
    prefix = " " * indent
    lines.append(f"{prefix}text: >-")
    for line in _wrap_text(value, 88 - indent - 2):
        lines.append(f"{prefix}  {line}")


def _emit_string_list(
    lines: list[str], indent: int, key: str, values: list[str]
) -> None:
    prefix = " " * indent
    if not values:
        lines.append(f"{prefix}{key}: []")
        return
    lines.append(f"{prefix}{key}:")
    lines.extend(f"{prefix}  - {_quote(value)}" for value in values)


def render_resume_yaml(document: ResumeDocument) -> str:
    """Render the canonical, deliberately quoted Resume Builder YAML format."""
    lines = [f"headline: {_quote(document.headline)}", "", "summary_bullets:"]
    for bullet in document.summary_bullets:
        lines.append(f"  - id: {_quote(bullet.id)}")
        _emit_text(lines, 4, bullet.text)

    lines.extend(["", "experience:"])
    for entry in document.experience:
        lines.append(f"  - company: {_quote(entry.company)}")
        location = "null" if entry.location is None else _quote(entry.location)
        lines.append(f"    location: {location}")
        lines.append("    positions:")
        for position in entry.positions:
            if position.title_lines:
                lines.append("      - title_lines:")
                lines.extend(
                    f"          - {_quote(value)}" for value in position.title_lines
                )
            else:
                lines.append("      - title_lines: []")
            _emit_string_list(lines, 8, "dates", position.dates)
            if position.summary is None:
                lines.append("        summary: null")
            else:
                lines.append("        summary:")
                lines.append(f"          id: {_quote(position.summary.id)}")
                _emit_text(lines, 10, position.summary.text)
            if not position.bullets:
                lines.append("        bullets: []")
            else:
                lines.append("        bullets:")
                for bullet in position.bullets:
                    lines.append(f"          - id: {_quote(bullet.id)}")
                    _emit_text(lines, 12, bullet.text)
        lines.append("")

    lines.append("skills:")
    skill_data = document.skills.model_dump()
    for category in ("ai", "languages", "tools", "architecture_patterns"):
        _emit_string_list(lines, 2, category, skill_data[category])
    lines.append("")
    return "\n".join(lines)


def validate_resume_yaml(yaml_text: str) -> None:
    data = yaml.safe_load(yaml_text)
    if list(data) != ROOT_KEYS:
        raise ValueError(f"unexpected root key order: {list(data)}")
    if {"contact", "education", "source"} & set(data):
        raise ValueError("output contains forbidden root content")
    ids: list[str] = [item["id"] for item in data["summary_bullets"]]
    for entry in data["experience"]:
        for position in entry["positions"]:
            if position["summary"]:
                ids.append(position["summary"]["id"])
            ids.extend(item["id"] for item in position["bullets"])
            if not all(isinstance(value, str) for value in position["dates"]):
                raise ValueError("a date was parsed as a non-string value")
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        raise ValueError(f"duplicate content IDs: {duplicates}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a final resume PDF to canonical Resume Builder YAML."
    )
    parser.add_argument("pdf", type=Path, help="Final edited resume PDF")
    parser.add_argument("-o", "--output", type=Path, help="Output YAML path")
    parser.add_argument(
        "--reference",
        type=Path,
        default=DEFAULT_REFERENCE if DEFAULT_REFERENCE.exists() else None,
        help="Resume YAML used to preserve stable IDs (default: data/resume_primary.yaml)",
    )
    parser.add_argument(
        "--no-reference",
        action="store_true",
        help="Do not provide an existing resume YAML for stable-ID matching",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Print sanitized local PDF text without calling Claude",
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing output YAML"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = args.pdf.resolve()
    if pdf_path.suffix.lower() != ".pdf":
        sys.exit("ERROR: this first version accepts PDF input only")
    if not pdf_path.exists():
        sys.exit(f"ERROR: PDF not found: {pdf_path}")

    try:
        extracted = extract_pdf_text(pdf_path)
        sanitized = sanitize_resume_text(extracted)
    except (RuntimeError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")

    if args.extract_only:
        print(sanitized)
        return

    output_path = (args.output or pdf_path.with_suffix(".yaml")).resolve()
    if output_path.exists() and not args.force:
        sys.exit(f"ERROR: output exists; pass --force to overwrite: {output_path}")

    reference_path = None if args.no_reference else args.reference
    try:
        reference_yaml = load_reference(reference_path)
        document, usage_text = request_resume_document(
            sanitized, reference_yaml, args.model
        )
        yaml_text = render_resume_yaml(document)
        validate_resume_yaml(yaml_text)
    except Exception as exc:
        sys.exit(f"ERROR: {exc}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_text)
    print(f"Created {output_path}")
    print(usage_text)
    print(
        f"Review: {len(document.summary_bullets)} summary bullets, "
        f"{len(document.experience)} experience entries, skills last"
    )


if __name__ == "__main__":
    main()
