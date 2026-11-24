# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, Antigravity, or others) when working with code in this repository.

Codex and Antigravity read `AGENTS.md` directly; `CLAUDE.md` in this directory is a symlink to it for Claude Code, so every agent reads the same instructions. Edit only `AGENTS.md`.

## What this is

A small personal tool (not a public product) that generates a single tailored
resume (.docx + PDF) for one job application. It combines Nick's primary resume
content (YAML, source of truth) with a job description via a structured
tailoring plan, then renders the resume from that primary content only — the LLM can only
select/reorder/lightly-rewrite existing bullets, never invent content. See
`docs/resume-tailoring-system-design.md` for the full design rationale and
`docs/Resume_Tailoring_Workflow_and_Prompt.md` for the interactive
cover-letter workflow (separate, manual process, not code-driven).

This folder is a public git repository (github.com/nick-leonard/resume-builder).
`.gitignore` is an allowlist because the folder also holds private data
(applications, story bank, writing samples, real resume YAML): never add a
private path to it, and commit or push only when Nick asks.

## Tailoring a resume: required workflow for every agent

When Nick asks for a resume tailored to a job, produce it through
`generate_resume.py`, whichever agent you are. Never write a tailored
`Nick_Leonard_Resume.yaml`, `.docx` or `.pdf` by hand, and never edit
`data/resume_primary.yaml` or `prompts/tailoring_prompt.md` to get a plan past
validation.

1. **JD:** if Nick pasted the job description, save it to a text file first.
2. **Plan**, in one of two modes:
   - **API mode (default):** `.venv/bin/python generate_resume.py --jd JD
     --company "Company" --role "Role"`. Add `--model ID` only if Nick names a
     model. Don't pass `--yes`: without a terminal the script saves
     `tailoring.yaml`, prints the review and stops before rendering.
   - **Agent mode**, when Nick says not to use the API or to use your own
     model: run the same command with `--prepare`, read the
     `tailoring_request.md` it writes into the application folder, and write
     `tailoring.yaml` there yourself, following that file exactly.
3. **Review:** show Nick what the script prints: the fit assessment, any
   headline change, every rewrite before/after, the bolded highlights, and the
   JD key-term coverage (especially terms marked missing).
4. **Render:** `.venv/bin/python generate_resume.py --from-plan
   "applications/<Company> - <Role>/tailoring.yaml"` (API mode: after Nick
   approves). To change the result, edit `tailoring.yaml` and run it again.
5. **Validation errors** mean the plan is wrong: fix `tailoring.yaml`, not the
   data.

## Job search tracker: keep it current

`applications/_dashboard/tracker.db` (SQLite) is the source of truth for the
status of every application and contract, and `dashboard.html` beside it is
generated from it. Both are gitignored because they hold pay and confidential
search details, so never publish them. Files stay in their application folders;
the database only links to them.

When a session reveals a change (application sent, interview booked, feedback,
new next step, a new opportunity), record it with `scripts/tracker.py`, which
rebuilds the page on every write. Check `list` for slugs first. Don't guess: if
a value is inferred, say what to confirm in `needs_verify`, and clear that field
once Nick confirms it.

```bash
.venv/bin/python scripts/tracker.py list
.venv/bin/python scripts/tracker.py set SLUG stage=Interviewing next_owner=me "next_action=Prep for CTO call" next_date=2026-11-09
.venv/bin/python scripts/tracker.py event SLUG --date 2026-11-09 --time "1:00 PM ET" --kind interview --title "CTO round"
.venv/bin/python scripts/tracker.py contact SLUG --name "Name" --title CTO --org Company --role "Hiring manager"
.venv/bin/python scripts/tracker.py add SLUG company=Acme "role=VP Eng" "stage=Lead / to apply" type=job folder="Acme - VP Eng"
.venv/bin/python scripts/tracker.py check   # folders with no record, missing folders, values to confirm
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp data/resume_primary.template.yaml data/resume_primary.yaml
cp data/resume_static.template.yaml data/resume_static.yaml
# then edit both with real content — both are gitignored

# API key: set ANTHROPIC_API_KEY in .env (gitignored, read by generate_resume.py),
# or export it in the shell (takes precedence), or use an `ant auth login` profile.
# RESUME_MODEL in .env picks the tailoring model (default: claude-sonnet-5-5).

brew install --cask libreoffice   # converts the .docx to PDF (headless)
```

## Commands

```bash
# API mode: one LLM call, save the plan, review, then render (see workflow above).
.venv/bin/python generate_resume.py \
    --jd "path/to/jd.txt" --company "Acme Corp" --role "VP of Engineering" \
    [--model ID] [--yes]

# Agent mode: no LLM call; writes tailoring_request.md for the agent to answer.
.venv/bin/python generate_resume.py \
    --jd "path/to/jd.txt" --company "Acme Corp" --role "VP of Engineering" --prepare

# Validate, review and render a saved plan — no LLM call.
.venv/bin/python generate_resume.py \
    --from-plan "applications/Acme Corp - VP of Engineering/tailoring.yaml"

# Render any full-resume YAML (Gold Standard, or a hand-edited tailored one)
# to .docx, and with --pdf also to .pdf via headless LibreOffice.
.venv/bin/python scripts/resume_yaml_to_docx.py \
    "applications/_Gold Standard/Nick_Leonard_Resume.yaml" --pdf

# Render an application's cover_letter.md into template/Nick_Leonard_Cover_Letter.docx
# (header and footer from the template, headline from the tailored resume YAML
# beside it); writes Nick_Leonard_Cover_Letter.docx, and with --pdf a .pdf too.
# **phrase** in the Markdown bolds a JD keyword, at most one per paragraph.
.venv/bin/python scripts/cover_letter_to_docx.py \
    "applications/Acme Corp - VP of Engineering/cover_letter.md" --pdf

# Normalize/reformat a resume YAML file to the canonical schema (whitespace,
# key order, id-carrying text blocks). Used when hand-editing or importing
# content from elsewhere (e.g. a Google Doc snapshot).
ruby scripts/normalize_resume_yaml.rb --copy SOURCE DESTINATION
ruby scripts/normalize_resume_yaml.rb --in-place FILE [FILE ...]
```

There is no test suite, linter, or build step in this repo.

## Architecture

`generate_resume.py` is a pipeline with a validation gate in the middle;
rendering lives in `scripts/resume_yaml_to_docx.py`, which it imports:

1. **Load** `data/resume_primary.yaml` (bullets/summaries with stable `id`s —
   sent to the LLM) and `data/resume_static.yaml` (contact + education —
   never sent to the LLM, merged only at render time).
2. **`index_primary`** builds id lookup sets (summary ids, per-company bullet
   ids, per-company summary ids) used purely for validating the LLM's output.
3. **`request_plan`** (API mode) sends the primary YAML + JD text to Claude
   (`client.beta.messages.parse` with a pydantic `output_format=TailoringPlan`
   and `fallbacks="default"` for refusals), using the system prompt in
   `prompts/tailoring_prompt.md`. **`write_request`** (agent mode,
   `--prepare`) writes the same prompt, input and the plan's JSON Schema to
   `tailoring_request.md` for the agent to answer instead. Either way the
   result is a `TailoringPlan`: which summary/experience bullets to include per
   role, in what order, plus optional `rewritten_text` for specific ids, an
   optional tailored headline, advisory `suggested_skills`, and a
   human-readable `fit_assessment` (never rendered), up to 8 `highlight_terms`
   (exact resume phrases to bold) and the JD's `jd_key_terms` (for the coverage
   report, never rendered).
4. **`validate_plan`** is the fabrication guard: every `id` referenced by the
   plan must exist in the primary file under the right company; every
   bullet-bearing role must appear in the plan (roles can't be silently
   dropped); a tailored headline requires a rationale. Fails hard (exit 1) on
   any violation.
5. **`print_review`** prints the fit assessment, any headline change, a
   before/after diff of every rewrite, the highlights that were placed, and
   JD key-term coverage computed in Python (`term_coverage`: on the resume,
   related wording only, in the primary file but not selected, or missing). In API mode the plan is saved first,
   then **`confirm_render`** asks before rendering (`--yes` skips it; with no
   terminal, as under an agent, it stops so the plan can be reviewed and
   rendered with `--from-plan`).
6. **`apply_plan` + `render_outputs`** build the tailored full-resume YAML
   from primary content by `id` lookup (the plan only selects/orders/rewrites;
   no free-form LLM text gets in outside those two lookup paths). Then
   **`add_highlights`** wraps each highlight phrase in `**...**`, once each and
   at most one per bullet, `MAX_HIGHLIGHTS` total; the markers only bold text
   that is already there, and `resume_yaml_to_docx.text_runs` renders them as
   bold runs (they can be added or removed by hand in the YAML). The result
   is written as `Nick_Leonard_Resume.yaml` (normalized; a differing previous version is
   kept as `.yaml.bak`), then render `.docx` with `resume_yaml_to_docx.render`
   and the PDF with its `convert_to_pdf` (headless LibreOffice). Document
   title/author metadata is set for ATS-safety (see the design doc for the
   rules — no header/footer contact info, etc.).
7. **`write_plan`/`load_plan`** persist the `TailoringPlan` as
   `tailoring.yaml` inside the application's output folder, so `--from-plan`
   can re-render without another LLM call; it is also the audit trail.

A run writes to `applications/<Company> - <Role>/`: `job_description.txt`,
`tailoring.yaml` (plus `tailoring_request.md` in agent mode), and the tailored
`Nick_Leonard_Resume.yaml`, `.docx` and `.pdf`. That directory is gitignored
(contains real application content).

### Data model

`data/resume_primary.yaml`: `headline`, `summary_bullets` (list of
`{id, text}`), `experience` (list of `{company, location, positions}`, each
position has `title_lines`, `dates`, optional `summary: {id, text}`, and
`bullets: [{id, text}]`; a position may also carry `client: "<name>"` to
render as a client engagement nested under a consulting entry, e.g. xNilio
under Rock House Technologies, with the client name prefixed to its first
title line, and its ids then belong to that parent company), `skills` (categorized lists — `SKILL_LABELS` in
`scripts/resume_yaml_to_docx.py` maps category keys to display labels). Every `id` must
be globally stable since it's the join key between the plan and the content —
don't reuse or rename ids casually. `scripts/normalize_resume_yaml.rb`
enforces a canonical key order/formatting for these files and is the safe way
to reformat them after hand-editing.

`data/resume_static.yaml`: `contact` and `education` only — deliberately kept
out of the LLM-facing primary file (see privacy model below).

Both real data files are gitignored; `*.template.yaml` counterparts are
anonymized and checked in so the repo can be published without leaking PII.

### Content rules the tailoring prompt enforces

`prompts/tailoring_prompt.md` encodes non-negotiable constraints for the
model: never inflate metrics or invent claims/tools/scope; preserve the
candidate's own wording (compress/reorder, don't genericize); rewrite only
when it meaningfully improves JD alignment (most content passes through
verbatim); mirror the JD's exact terminology/casing; every bullet-bearing
role must appear (vary bullet count instead of dropping a role); leave the
headline alone unless the JD's title language differs in a way with real
ATS/screener value. It also pins a few facts that must never be
softened/altered (specific budget figures, a specific cost-reduction
narrative, the xNilio fractional-then-full-time title arc, etc.) — read that
file before changing prompt behavior, since those are deliberate anti-drift
guards, not stylistic suggestions.
