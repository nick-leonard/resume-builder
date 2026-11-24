#!/usr/bin/env python3
"""Generate a tailored resume (.yaml, .docx, .pdf) for a single job application.

A tailoring plan says which summary bullets and which experience bullets per
role to include, in what order, with optional rewrites, a possibly-tailored
headline, and advisory skill suggestions. The plan comes from one Claude API
call (default) or from the coding agent you're working in (--prepare). Either
way the script validates it against the primary file, prints a review, then
builds the resume from primary content only, so the plan can never fabricate
its way into the document. Rendering goes through scripts/resume_yaml_to_docx.py
(docx, then PDF via headless LibreOffice).

Usage:
    # API mode: one Claude API call (ANTHROPIC_API_KEY / RESUME_MODEL in .env)
    python generate_resume.py --jd path/to/jd.txt \
        --company "Acme Corp" --role "VP of Engineering" [--model ID] [--yes]

    # Agent mode: no API call. Writes tailoring_request.md for the agent to
    # answer with tailoring.yaml, which it then renders with --from-plan.
    python generate_resume.py --jd path/to/jd.txt \
        --company "Acme Corp" --role "VP of Engineering" --prepare

    # Validate, review and render a saved plan (no LLM call)
    python generate_resume.py --from-plan \
        "applications/Acme Corp - VP of Engineering/tailoring.yaml"
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
PRIMARY_PATH = ROOT / "data" / "resume_primary.yaml"
STATIC_PATH = ROOT / "data" / "resume_static.yaml"
PROMPT_PATH = ROOT / "prompts" / "tailoring_prompt.md"
# Optional, gitignored: candidate-specific facts the model must never alter.
# See prompts/standing_framings.example.md.
FRAMINGS_PATH = ROOT / "prompts" / "standing_framings.md"
APPLICATIONS_DIR = ROOT / "applications"
ENV_PATH = ROOT / ".env"  # gitignored; holds ANTHROPIC_API_KEY and RESUME_MODEL
NORMALIZER = ROOT / "scripts" / "normalize_resume_yaml.rb"

MODEL = "claude-sonnet-5-5"  # default; override with RESUME_MODEL in .env or --model

RESUME_BASENAME = "Nick_Leonard_Resume"  # .yaml / .docx / .pdf in the application folder
PLAN_FILENAME = "tailoring.yaml"
REQUEST_FILENAME = "tailoring_request.md"

MAX_HIGHLIGHTS = 8  # bolded phrases per resume; more reads as keyword stuffing


# --------------------------------------------------------------------------- #
# Structured-output schema (the LLM fills this in)                             #
# --------------------------------------------------------------------------- #
class BulletChoice(BaseModel):
    id: str  # must match an id in the primary file
    rewritten_text: str | None = None  # None = render the original text verbatim


class RolePlan(BaseModel):
    company: str  # must match a company in the primary file
    bullets: list[BulletChoice] = []  # selected experience bullets, in render order
    summary_rewrites: list[BulletChoice] = []  # optional rewrites of position summaries


class TailoringPlan(BaseModel):
    fit_assessment: str  # blunt fit read; printed to terminal, never rendered
    tailored_headline: str | None = None  # None = keep the primary headline
    headline_rationale: str | None = None  # required when tailored_headline is set
    summary_bullets: list[BulletChoice]  # selected summary bullets, in render order
    roles: list[RolePlan]  # every bullet-bearing role
    suggested_skills: list[str] = []  # advisory only; never auto-rendered
    highlight_terms: list[str] = []  # exact resume phrases to bold, most important first
    jd_key_terms: list[str] = []  # JD terms to check coverage against; never rendered


# --------------------------------------------------------------------------- #
# Loading                                                                      #
# --------------------------------------------------------------------------- #
def load_yaml(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"ERROR: missing required file: {path}")
    with path.open() as f:
        return yaml.safe_load(f)


def load_primary() -> dict:
    return load_yaml(PRIMARY_PATH)


def load_static() -> dict:
    return load_yaml(STATIC_PATH)


def load_env() -> None:
    # Minimal KEY=VALUE reader for .env; variables already exported win.
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("\"'")
        if value:
            os.environ.setdefault(key.strip(), value)


# --------------------------------------------------------------------------- #
# Primary-file indexing (for validation and rendering)                        #
# --------------------------------------------------------------------------- #
def index_primary(primary: dict) -> dict:
    """Collect id lookups so we can validate the plan and render by id."""
    summary_ids = {b["id"] for b in primary.get("summary_bullets", [])}

    bullet_ids_by_company: dict[str, set[str]] = {}
    summary_ids_by_company: dict[str, set[str]] = {}
    companies_with_bullets: set[str] = set()

    for exp in primary.get("experience", []):
        company = exp["company"]
        bullet_ids_by_company.setdefault(company, set())
        summary_ids_by_company.setdefault(company, set())
        for pos in exp.get("positions", []):
            summ = pos.get("summary")
            if summ:
                summary_ids_by_company[company].add(summ["id"])
            for bullet in pos.get("bullets", []) or []:
                bullet_ids_by_company[company].add(bullet["id"])
                companies_with_bullets.add(company)

    return {
        "summary_ids": summary_ids,
        "bullet_ids_by_company": bullet_ids_by_company,
        "summary_ids_by_company": summary_ids_by_company,
        "companies_with_bullets": companies_with_bullets,
    }


# --------------------------------------------------------------------------- #
# LLM call                                                                     #
# --------------------------------------------------------------------------- #
def build_user_content(primary: dict, jd_text: str) -> str:
    primary_yaml_text = yaml.safe_dump(primary, sort_keys=False, allow_unicode=True)
    return (
        f"<primary_resume>\n{primary_yaml_text}\n</primary_resume>\n\n"
        f"<job_description>\n{jd_text}\n</job_description>"
    )


def system_prompt() -> str:
    """The tailoring prompt, plus the private standing framings when present."""
    prompt = PROMPT_PATH.read_text()
    if FRAMINGS_PATH.exists():
        prompt = prompt.rstrip() + "\n\n" + FRAMINGS_PATH.read_text()
    return prompt


def request_plan(primary: dict, jd_text: str, model: str) -> TailoringPlan:
    import anthropic  # imported here so --from-plan / --prepare run without the SDK

    client = anthropic.Anthropic()
    print(f"Calling {model} for a tailoring plan...", flush=True)
    # fallbacks="default": if a safety classifier declines the request, the API
    # re-runs it on Anthropic's recommended fallback model instead of refusing.
    response = client.beta.messages.parse(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=system_prompt(),
        messages=[{"role": "user", "content": build_user_content(primary, jd_text)}],
        output_format=TailoringPlan,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        sys.exit(f"ERROR: model returned no plan (stop_reason={response.stop_reason})")
    usage = response.usage
    print(
        f"  done ({response.model}). tokens in/out: {usage.input_tokens}/{usage.output_tokens}",
        flush=True,
    )
    return response.parsed_output


# --------------------------------------------------------------------------- #
# Agent mode — the coding agent writes the plan instead of the API             #
# --------------------------------------------------------------------------- #
def write_request(primary: dict, jd_text: str, folder: Path) -> Path:
    """Write a self-contained tailoring request for a coding agent to answer."""
    plan_path = folder / PLAN_FILENAME
    schema = json.dumps(TailoringPlan.model_json_schema(), indent=2)
    request = f"""# Tailoring request: {folder.name}

You are producing a tailoring PLAN, not a resume. Follow the instructions in
"System prompt" below exactly, using the primary resume and job description
that follow it. Write the plan as YAML matching "Plan schema" to:

    {rel(plan_path)}

Then validate, review and render it:

    .venv/bin/python generate_resume.py --from-plan "{rel(plan_path)}"

Show the user the review that command prints (fit assessment, headline change,
every rewrite). Never write {RESUME_BASENAME}.yaml, .docx or .pdf yourself, and
never edit data/resume_primary.yaml to make a plan validate.

## System prompt

{system_prompt()}

## Input

{build_user_content(primary, jd_text)}

## Plan schema (JSON Schema; write the plan as YAML)

```json
{schema}
```
"""
    path = folder / REQUEST_FILENAME
    path.write_text(request)
    return path


# --------------------------------------------------------------------------- #
# Validation — the plan may only reference real primary content                #
# --------------------------------------------------------------------------- #
def validate_plan(plan: TailoringPlan, idx: dict) -> None:
    errors: list[str] = []

    for bc in plan.summary_bullets:
        if bc.id not in idx["summary_ids"]:
            errors.append(f"summary bullet id not in primary: {bc.id!r}")

    planned_companies = set()
    for role in plan.roles:
        planned_companies.add(role.company)
        if role.company not in idx["bullet_ids_by_company"]:
            errors.append(f"role company not in primary: {role.company!r}")
            continue
        valid_bullets = idx["bullet_ids_by_company"][role.company]
        valid_summaries = idx["summary_ids_by_company"][role.company]
        for bc in role.bullets:
            if bc.id not in valid_bullets:
                errors.append(
                    f"bullet id {bc.id!r} not found under company {role.company!r}"
                )
        for sr in role.summary_rewrites:
            if sr.id not in valid_summaries:
                errors.append(
                    f"summary id {sr.id!r} not found under company {role.company!r}"
                )

    missing = idx["companies_with_bullets"] - planned_companies
    if missing:
        errors.append(
            "plan omits bullet-bearing roles (every role must appear): "
            + ", ".join(sorted(missing))
        )

    if plan.tailored_headline and not plan.headline_rationale:
        errors.append("tailored_headline set without a headline_rationale")

    if errors:
        print("\nPLAN VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)


# --------------------------------------------------------------------------- #
# Review                                                                       #
# --------------------------------------------------------------------------- #
def _wrap(text: str, indent: str = "    ") -> str:
    return textwrap.fill(
        " ".join(text.split()),
        width=88,
        initial_indent=indent,
        subsequent_indent=indent,
    )


def print_review(plan: TailoringPlan, primary: dict) -> None:
    bullet_text = {}
    summary_text = {}
    for exp in primary["experience"]:
        for pos in exp.get("positions", []):
            summ = pos.get("summary")
            if summ:
                summary_text[summ["id"]] = summ["text"]
            for b in pos.get("bullets", []) or []:
                bullet_text[b["id"]] = b["text"]
    summary_bullet_text = {b["id"]: b["text"] for b in primary["summary_bullets"]}

    line = "=" * 92
    print(f"\n{line}\nFIT ASSESSMENT (not rendered into the resume)\n{line}")
    print(_wrap(plan.fit_assessment, indent="  "))

    if plan.tailored_headline:
        print(f"\n{line}\nHEADLINE — TAILORED (review carefully)\n{line}")
        print(f"  FROM: {primary['headline']}")
        print(f"  TO:   {plan.tailored_headline}")
        print(_wrap(f"Rationale: {plan.headline_rationale}", indent="  "))

    # Summary + experience rewrites (before -> after).
    rewrites: list[tuple[str, str, str]] = []
    for bc in plan.summary_bullets:
        if bc.rewritten_text:
            rewrites.append((f"summary/{bc.id}", summary_bullet_text[bc.id], bc.rewritten_text))
    for role in plan.roles:
        for bc in role.bullets:
            if bc.rewritten_text:
                rewrites.append((f"{role.company}/{bc.id}", bullet_text[bc.id], bc.rewritten_text))
        for sr in role.summary_rewrites:
            if sr.rewritten_text:
                rewrites.append(
                    (f"{role.company}/{sr.id} (summary)", summary_text[sr.id], sr.rewritten_text)
                )

    print(f"\n{line}\nREWRITES ({len(rewrites)}) — before / after\n{line}")
    if not rewrites:
        print("  (none — all selected content passes through verbatim)")
    for label, before, after in rewrites:
        print(f"\n  [{label}]")
        print("  BEFORE:")
        print(_wrap(before, indent="    "))
        print("  AFTER:")
        print(_wrap(after, indent="    "))

    resume, unplaced = apply_plan(plan, primary)
    terms = [t for t in plan.highlight_terms if t.strip()]
    print(f"\n{line}\nHIGHLIGHTS (bold, max {MAX_HIGHLIGHTS}, one per bullet)\n{line}")
    placed = [t for t in terms[:MAX_HIGHLIGHTS] if t not in unplaced]
    print(_wrap("; ".join(placed) or "(none)", indent="  "))
    if unplaced:
        print(_wrap(f"Not bolded (not found, or its bullet already has one): {'; '.join(unplaced)}", indent="  "))
    if terms[MAX_HIGHLIGHTS:]:
        print(_wrap(f"Over the cap, ignored: {'; '.join(terms[MAX_HIGHLIGHTS:])}", indent="  "))

    if plan.jd_key_terms:
        tailored, everything = _tokens(resume_text(resume)), _tokens(resume_text(primary))
        groups: dict[str, list[str]] = {"exact": [], "related": [], "unselected": [], "missing": []}
        for term in plan.jd_key_terms:
            match = term_coverage(term, tailored)
            if match:
                groups[match].append(term)
            elif term_coverage(term, everything):
                groups["unselected"].append(term)
            else:
                groups["missing"].append(term)
        on_resume = len(groups["exact"]) + len(groups["related"])
        print(f"\n{line}\nJD KEY TERMS — {on_resume}/{len(plan.jd_key_terms)} on the resume\n{line}")
        labels = {
            "exact": "On the resume",
            "related": "Related wording only (all the words appear, not the phrase)",
            "unselected": "In your primary file but not selected",
            "missing": "Not in your content (a real gap, or worded differently)",
        }
        for key, label in labels.items():
            if groups[key] or key == "exact":
                print(_wrap(f"{label}: {'; '.join(groups[key]) or '(none)'}", indent="  "))

    if plan.suggested_skills:
        print(f"\n{line}\nSUGGESTED SKILLS (advisory — add by hand only if true)\n{line}")
        print(_wrap(", ".join(plan.suggested_skills), indent="  "))

    print(f"\n{line}")


def confirm_render(plan_path: Path, skip: bool) -> bool:
    if skip:
        print("--yes given; skipping confirmation.")
        return True
    rerun = f'.venv/bin/python generate_resume.py --from-plan "{rel(plan_path)}"'
    if not sys.stdin.isatty():
        # Agents run without a terminal: stop here so the user can review first.
        print(f"Plan saved, not rendered (no terminal to confirm). After review, run:\n  {rerun}")
        return False
    if input("Proceed with rendering? [y/N] ").strip().lower() != "y":
        print(f"Plan saved, not rendered. To render later:\n  {rerun}")
        return False
    return True


# --------------------------------------------------------------------------- #
# Rendering — apply the plan to primary content, then docx + PDF               #
# --------------------------------------------------------------------------- #
def apply_plan(plan: TailoringPlan, primary: dict) -> tuple[dict, list[str]]:
    """Build the tailored full-resume dict (canonical schema) from primary content.

    The plan only selects, orders, rewrites and highlights by id/phrase; every
    other field comes from the primary file unchanged. Also returns the
    highlight terms that couldn't be placed.
    """
    role_by_company = {r.company: r for r in plan.roles}
    summary_src = {b["id"]: b["text"] for b in primary["summary_bullets"]}

    experience = []
    for exp in copy.deepcopy(primary["experience"]):
        rp = role_by_company.get(exp["company"])
        summ_rewrite = {sr.id: sr.rewritten_text for sr in rp.summary_rewrites} if rp else {}
        chosen = rp.bullets if rp else []
        for pos in exp["positions"]:
            summ = pos.get("summary")
            if summ and summ_rewrite.get(summ["id"]):
                summ["text"] = summ_rewrite[summ["id"]]
            src = {b["id"]: b["text"] for b in pos.get("bullets") or []}
            pos["bullets"] = [
                {"id": bc.id, "text": bc.rewritten_text or src[bc.id]}
                for bc in chosen
                if bc.id in src
            ]
        experience.append(exp)

    resume = {
        "headline": plan.tailored_headline or primary["headline"],
        "summary_bullets": [
            {"id": bc.id, "text": bc.rewritten_text or summary_src[bc.id]}
            for bc in plan.summary_bullets
        ],
        "experience": experience,
        "skills": primary["skills"],
    }
    unplaced = add_highlights(resume, plan.highlight_terms)
    return resume, unplaced


def _term_pattern(term: str) -> re.Pattern:
    # Whole-phrase, case-insensitive, whitespace-tolerant ("AI" never matches in "AIM").
    body = r"\s+".join(re.escape(word) for word in term.split())
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def add_highlights(resume: dict, terms: list[str]) -> list[str]:
    """Bold each term once as **term**, at most one per paragraph; return unplaced terms.

    Only summary bullets, role summaries and experience bullets are eligible
    (never the headline, titles or skills). Markers wrap the resume's own text,
    so highlighting can't change wording.
    """
    paragraphs = list(resume["summary_bullets"])
    for exp in resume["experience"]:
        for pos in exp["positions"]:
            if pos.get("summary"):
                paragraphs.append(pos["summary"])
            paragraphs.extend(pos.get("bullets") or [])

    taken: set[int] = set()  # paragraphs that already hold a highlight
    unplaced = []
    for term in [t for t in terms if t.strip()][:MAX_HIGHLIGHTS]:
        pattern = _term_pattern(term)
        for i, para in enumerate(paragraphs):
            if i in taken:
                continue
            text = " ".join(para["text"].split())
            m = pattern.search(text)
            if m:
                para["text"] = f"{text[:m.start()]}**{m.group(0)}**{text[m.end():]}"
                taken.add(i)
                break
        else:
            unplaced.append(term)
    return unplaced


COVERAGE_STOPWORDS = {"a", "an", "and", "as", "for", "in", "of", "on", "or", "the", "to", "with"}


def _tokens(text: str) -> list[str]:
    # Lowercased words with punctuation dropped and a plural "s" trimmed, so
    # "data pipelines" matches "pipeline" and "LLMs" matches "LLM".
    words = re.findall(r"[a-z0-9][a-z0-9+#]*", text.lower())
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words]


def term_coverage(term: str, tokens: list[str]) -> str | None:
    """'exact' if the term appears as a phrase, 'related' if all its words do, else None.

    "X (Y)" counts as covered by either X or Y.
    """
    joined, vocab = f" {' '.join(tokens)} ", set(tokens)
    variants = [re.sub(r"\(.*?\)", " ", term)] + re.findall(r"\((.*?)\)", term)
    result = None
    for variant in variants:
        words = _tokens(variant)
        if not words:
            continue
        if f" {' '.join(words)} " in joined:
            return "exact"
        content = [w for w in words if w not in COVERAGE_STOPWORDS]
        if content and all(w in vocab for w in content):
            result = "related"
    return result


def resume_text(resume: dict) -> str:
    """Plain text of a full-resume dict (tailored or primary), for keyword coverage."""
    parts = [resume["headline"]] + [b["text"] for b in resume["summary_bullets"]]
    for exp in resume["experience"]:
        parts.append(exp["company"])
        for pos in exp["positions"]:
            parts += pos.get("title_lines") or []
            if pos.get("summary"):
                parts.append(pos["summary"]["text"])
            parts += [b["text"] for b in pos.get("bullets") or []]
    for items in resume["skills"].values():
        parts += items
    return " ".join(" ".join(parts).replace("**", "").split())


def write_resume_yaml(resume: dict, path: Path) -> None:
    # Keep the previous version if it differs: older application folders hold
    # hand-tailored YAML that a re-render would otherwise overwrite.
    tmp = path.with_suffix(".yaml.new")
    with tmp.open("w") as f:
        yaml.safe_dump(resume, f, sort_keys=False, allow_unicode=True, width=1000)
    if shutil.which("ruby"):
        subprocess.run(["ruby", str(NORMALIZER), "--in-place", str(tmp)], check=True)
    if path.exists() and path.read_text() != tmp.read_text():
        backup = path.with_suffix(".yaml.bak")
        path.replace(backup)
        print(f"Previous {path.name} differed; kept it as {backup.name}")
    tmp.replace(path)


def render_outputs(plan: TailoringPlan, primary: dict, static: dict, folder: Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from resume_yaml_to_docx import convert_to_pdf, render  # needs python-docx

    resume, _ = apply_plan(plan, primary)
    yaml_path = folder / f"{RESUME_BASENAME}.yaml"
    docx_path = folder / f"{RESUME_BASENAME}.docx"
    write_resume_yaml(resume, yaml_path)
    render(resume, static, docx_path)
    pdf_path = convert_to_pdf(docx_path)
    for p in (yaml_path, docx_path, pdf_path):
        print(f"Rendered: {rel(p)}")


# --------------------------------------------------------------------------- #
# Plan persistence                                                             #
# --------------------------------------------------------------------------- #
def write_plan(plan: TailoringPlan, path: Path) -> None:
    with path.open("w") as f:
        yaml.safe_dump(plan.model_dump(), f, sort_keys=False, allow_unicode=True)


# Companies later nested as client engagements under another entry. Plans saved
# before the move still name the old company, so fold them into the new one.
LEGACY_COMPANY_ALIASES = {
    "Independent Consulting": "Rock House Technologies",
    "xNilio": "Rock House Technologies",
}


def load_plan(path: Path) -> TailoringPlan:
    with path.open() as f:
        plan = TailoringPlan(**yaml.safe_load(f))
    merged: dict[str, RolePlan] = {}
    for role in plan.roles:
        company = LEGACY_COMPANY_ALIASES.get(role.company, role.company)
        if company in merged:
            merged[company].bullets += role.bullets
            merged[company].summary_rewrites += role.summary_rewrites
        else:
            merged[company] = role.model_copy(update={"company": company})
    plan.roles = list(merged.values())
    return plan


def rel(path: Path) -> Path:
    # Project-relative for display, so printed commands run from the repo root.
    path = path.resolve()
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def slug(text: str) -> str:
    return " ".join(text.split()).replace("/", "-")


# --------------------------------------------------------------------------- #
# Entry points                                                                 #
# --------------------------------------------------------------------------- #
def application_folder(jd_path: Path, company: str, role: str) -> tuple[Path, str]:
    folder = APPLICATIONS_DIR / f"{slug(company)} - {slug(role)}"
    folder.mkdir(parents=True, exist_ok=True)
    jd_text = jd_path.read_text()
    (folder / "job_description.txt").write_text(jd_text)
    return folder, jd_text


def run_normal(
    jd_path: Path, company: str, role: str, model: str | None, skip: bool
) -> None:
    load_env()
    model = model or os.environ.get("RESUME_MODEL", MODEL)
    primary = load_primary()
    static = load_static()

    plan = request_plan(primary, jd_path.read_text(), model)
    validate_plan(plan, index_primary(primary))

    # Save the plan before review so a declined or deferred render keeps the
    # (paid-for) plan; --from-plan renders it later.
    folder, _ = application_folder(jd_path, company, role)
    plan_path = folder / PLAN_FILENAME
    write_plan(plan, plan_path)
    print_review(plan, primary)
    if confirm_render(plan_path, skip):
        render_outputs(plan, primary, static, folder)


def run_prepare(jd_path: Path, company: str, role: str) -> None:
    folder, jd_text = application_folder(jd_path, company, role)
    request_path = write_request(load_primary(), jd_text, folder)
    print(f"Wrote {rel(request_path)}")
    print(f"Next: read it, write {rel(folder / PLAN_FILENAME)}, then run")
    print(f'  .venv/bin/python generate_resume.py --from-plan "{rel(folder / PLAN_FILENAME)}"')


def run_from_plan(plan_path: Path) -> None:
    if not plan_path.exists():
        sys.exit(f"ERROR: plan file not found: {plan_path}")
    primary = load_primary()
    static = load_static()
    plan = load_plan(plan_path)
    validate_plan(plan, index_primary(primary))  # guard against drift since save
    print_review(plan, primary)
    render_outputs(plan, primary, static, plan_path.resolve().parent)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a tailored resume.")
    parser.add_argument("--jd", type=Path, help="Path to the job description text file.")
    parser.add_argument("--company", help="Company name (application folder + LLM context).")
    parser.add_argument("--role", help="Job title (application folder name).")
    parser.add_argument(
        "--model", help=f"Model for API mode (default: RESUME_MODEL in .env, else {MODEL})."
    )
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="Agent mode: write tailoring_request.md for the agent instead of calling the API.",
    )
    parser.add_argument(
        "--from-plan",
        type=Path,
        dest="from_plan",
        help="Validate, review and render a saved tailoring.yaml (no LLM call).",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip the review confirmation prompt."
    )
    args = parser.parse_args()

    if args.from_plan:
        run_from_plan(args.from_plan)
        return

    if not (args.jd and args.company and args.role):
        parser.error("--jd, --company, and --role are required (or use --from-plan).")
    if not args.jd.exists():
        sys.exit(f"ERROR: JD file not found: {args.jd}")
    if args.prepare:
        run_prepare(args.jd, args.company, args.role)
    else:
        run_normal(args.jd, args.company, args.role, args.model, args.yes)


if __name__ == "__main__":
    main()
