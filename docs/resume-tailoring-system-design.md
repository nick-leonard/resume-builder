# Resume Tailoring System — Design Spec

## Goal

A simple, reusable system that generates a tailored resume PDF for each job application from a single primary source of truth plus a job description. One LLM call per application selects and (lightly) rewrites content; a Python script renders the PDF.

This is a personal tool for one user. Keep the code simple — no frameworks, no config systems, no premature abstraction.

## Why this approach

- One primary YAML file holds the superset of every bullet, role, and skill the candidate has ever wanted to use.
- A single Claude API call per application reads the whole primary file + the JD and returns a structured "tailoring plan": which summary variant, which bullets per role, and rewritten phrasing where it improves JD alignment.
- The script assembles the PDF **only from content in the primary file** (substituting LLM rewrites where provided), so fabrication is structurally impossible for selection and reviewable for rewrites.
- Avoids manually re-editing a document for every application.

## Repository layout

```text
resume-builder/
├── docs/
│   ├── resume-tailoring-system-design.md      # this file
│   └── Resume_Tailoring_Workflow_and_Prompt.md # interactive (Claude Desktop) workflow + standing framings
├── template/
│   └── <Name>_Resume.pdf                # current live resume — the visual style reference AND content source
├── prompts/
│   └── tailoring_prompt.md                    # LLM prompt text, loaded by the script (checked in — contains no PII)
├── data/
│   ├── resume_primary.yaml                    # GITIGNORED — full bullet superset; this IS sent to the LLM
│   ├── resume_primary.template.yaml           # checked in — same structure, anonymized example values
│   ├── resume_static.yaml                     # GITIGNORED — contact + education; NEVER sent to the LLM
│   └── resume_static.template.yaml            # checked in — same structure, placeholder values
├── applications/                              # GITIGNORED — one folder per job application
│   └── <Job Title> - <Company Name>/
│       ├── job_description.txt                # the JD used for this application
│       ├── tailoring.yaml                     # the LLM's tailoring plan (selection + rewrites) — audit trail & re-render input
│       ├── <Name>_Resume.pdf            # generated output
│       ├── <Name>_Cover_Letter.pdf      # created via the Desktop workflow, saved here manually (out of scope for the script)
│       └── outreach.md                        # optional: LinkedIn message / recruiter email drafts
├── generate_resume.py                         # the entire tool — single script
├── .gitignore
└── requirements.txt
```

### Folder & naming conventions (important)

- Each application gets its own folder named **`<Company Name> - <Job Title>`** (e.g. `applications/Acme Corp - VP of Engineering/`).
- The resume and cover letter filenames are **always** `<Name>_Resume.pdf` and `<Name>_Cover_Letter.pdf` — no company name, no version suffix. This keeps submitted filenames clean and does not hint at a tailoring process. The parent folder carries the company/role identity.
- `.gitignore` must cover: `data/resume_primary.yaml`, `data/resume_static.yaml`, `applications/`. The `*.template.yaml` files are checked in so the repo can eventually be published (blog article planned) without leaking PII.

## Data files

### `data/resume_primary.yaml` — sent to the LLM

Contains everything the LLM needs to select and rewrite: summary variants, skills, and the full experience superset. **No tags** — the LLM reads the actual text and the JD; tag-based scoring machinery was cut for simplicity. **No contact info, no education** — those live in `resume_static.yaml` and are never sent to the LLM (minimizes PII exposure per call).

Every bullet has a stable `id` — this is the key the LLM's output references, and how the script guarantees only real content is rendered.

```yaml
summary_variants:
  - id: technical_leader
    text: >
      Executive-minded engineering leader with 18+ years architecting and
      scaling machine learning, data ingestion, and AI platforms across
      industrial IoT, e-commerce, and enterprise SaaS.
  - id: ai_architect
    text: >
      Founding CTO and hands-on AI platform architect with direct experience
      building RAG pipelines, vector retrieval systems, and LLM-integrated
      production platforms from zero to MVP.

skills:
  languages: [C/C++, Go, Java, JavaScript, Python, SQL]   # always rendered in full
  tools:                                                   # LLM selects & orders a subset
    - Snowflake
    - dbt Cloud
    - Claude Code
    - Terraform
    # ... full superset

experience:
  - company: xNilio
    location: New York, NY (Hybrid)
    title_lines:                       # a role may have multiple title lines (see standing framings)
      - "Fractional CTO / Technical Advisor"
      - "Chief Technology Officer"
    dates:
      - "Dec 2025 - Mar 2026"
      - "Mar 2026 - June 2026"
    bullets:
      - id: xnilio_ingestion
        text: >
          Architected a provenance-rigorous data ingestion pipeline (xIngest)
          processing heterogeneous industrial documents...
      - id: xnilio_cloud
        text: >
          Designed and built a cloud-agnostic platform (GCP first)...
      # ... every bullet ever written for this role (superset)

  # ... remaining roles follow the same pattern. Older roles (Argon ST, GD,
  # HP Autonomy) may be condensed into a single "Early Career" entry with
  # minimal bullets.
```

**Content rules when building this file** (from `template/<Name>_Resume.pdf`):

- The template PDF is the authoritative, up-to-date content source. Extract its content verbatim as the baseline, then add historical superset bullets from older resume versions as the candidate provides them.
- Honor the **standing framings** in `docs/Resume_Tailoring_Workflow_and_Prompt.md` (Part 2, "My standing framings") — xNilio split title lines, Independent Consulting entry, J.Crew capex phrasing, Snowflake cost framing, career-break line. These are already reflected in the template PDF; do not contradict them.

### `data/resume_static.yaml` — never sent to the LLM

Constant content merged in at render time only:

```yaml
contact:
  name: Jane Doe
  phone: "..."
  email: "..."
  linkedin: "..."
  location: NYC Metro Area

education:
  - school: Cornell University
    degree: Master of Engineering in Computer Science
    date: May 2022
  - school: University of Pittsburgh
    degree: Bachelor of Science in Computer Engineering
    date: Dec 2008
```

The checked-in `resume_static.template.yaml` has the same structure with placeholder values.

## Pipeline

> **Update 2026-10-27: rendering and plan sources changed.** WeasyPrint and the
> HTML/CSS template are gone. The plan is applied to primary content as a
> tailored `<Name>_Resume.yaml`, rendered to `.docx` by
> `scripts/resume_yaml_to_docx.py`, then converted to PDF with headless
> LibreOffice. That is the same path as the Gold Standard, and it carries the
> ATS rules below (title/author metadata, contact info in the body). The plan
> can also come from the coding agent instead of the API (`--prepare`). Where
> this spec mentions weasyprint, HTML/CSS or a PDF-only output, `AGENTS.md`
> and `README.md` describe the current behavior.

**Script:** `generate_resume.py` (single file). **Dependencies** (`requirements.txt`): `anthropic`, `pydantic`, `pyyaml`, `weasyprint`.

### CLI

```bash
export ANTHROPIC_API_KEY=...   # or an active `ant auth login` profile

# Normal run — makes one LLM call, creates the application folder, renders the PDF
python generate_resume.py --jd path/to/jd.txt --company "Acme Corp" --role "VP of Engineering"

# Re-render from an existing plan — NO LLM call. For iterating on CSS/layout.
python generate_resume.py --from-plan "applications/Acme Corp - VP of Engineering/tailoring.yaml"
```

### Steps (normal run)

1. **Load** `data/resume_primary.yaml`, `prompts/tailoring_prompt.md`, and the JD text.
2. **One LLM call** using the Python `anthropic` SDK with structured output:

   ```python
   response = client.messages.parse(
       model="claude-opus-4-8",
       max_tokens=16000,
       system=open("prompts/tailoring_prompt.md").read(),
       messages=[{"role": "user", "content": f"<primary_resume>\n{primary_yaml_text}\n</primary_resume>\n\n<job_description>\n{jd_text}\n</job_description>"}],
       output_format=TailoringPlan,
   )
   plan = response.parsed_output  # validated TailoringPlan instance
   ```

   Cost note: ~5–10K input tokens + a few K output per run ≈ a few cents on `claude-opus-4-8`. Negligible at personal-application volume.

3. **Validate** the plan against the primary file (fail loudly on any mismatch):
   - `summary_variant_id` exists in `summary_variants`.
   - Every `roles[].company` matches a primary `experience[].company`, and **every primary role appears** in the plan (roles are never omitted — older roles may carry as few as 1 bullet).
   - Every `bullets[].id` exists under its claimed role.
   - Every `selected_tools` entry exists in `skills.tools`.
4. **Review gate** — print to the terminal:
   - The `fit_assessment` (informational only; not rendered into the PDF).
   - A per-bullet **before → after diff** for every rewrite, so every changed word gets human eyes before anything is generated.
   - Prompt `Proceed? [y/N]` (skippable with `--yes`).
5. **Create the application folder** `applications/<role> - <company>/`, copy the JD in as `job_description.txt`, and write the plan as `tailoring.yaml`.
6. **Render**: merge the plan with `resume_primary.yaml` content and `resume_static.yaml` (contact/education), build HTML from the hardcoded template string, render with `weasyprint` to `<Name>_Resume.pdf` in the application folder.

### Structured output schema (Pydantic — copy verbatim)

```python
from pydantic import BaseModel

class BulletChoice(BaseModel):
    id: str                          # must match a bullet id in resume_primary.yaml
    rewritten_text: str | None = None  # None = use the original text verbatim

class RolePlan(BaseModel):
    company: str                     # must match a company in resume_primary.yaml
    bullets: list[BulletChoice]      # in render order; recent roles ~3-5 bullets, older roles 1-2

class TailoringPlan(BaseModel):
    fit_assessment: str              # blunt 2-4 sentence fit read; printed to terminal, never rendered
    summary_variant_id: str          # must match an id in summary_variants
    roles: list[RolePlan]            # MUST include every role from the primary file
    selected_tools: list[str]        # subset of skills.tools, ordered by JD relevance
```

## Prompt file: `prompts/tailoring_prompt.md`

The prompt lives in its own source file (easier to edit than a Python string) and is loaded as the system prompt. It must contain the following, adapted from the ground rules in `docs/Resume_Tailoring_Workflow_and_Prompt.md`. Starting text — copy into the file and iterate from there:

```text
You are an experienced executive hiring manager and recruiter in the NYC tech
market, tailoring a resume for a specific role. The candidate targets
fractional or full-time CTO, VP of Engineering, and Head of Engineering roles
in AI, ML, data, and general software engineering.

You will receive the candidate's primary resume content (YAML, with a stable
`id` per bullet) and a job description. Produce a tailoring plan in the
required structured format.

## Ground rules (non-negotiable)
1. HONESTY FIRST. Never inflate metrics or claim experience the bullets don't
   already support. A rewrite may re-emphasize and reorder facts already in
   the bullet; it may never add new claims.
2. PRESERVE THE CANDIDATE'S VERBIAGE. Compress and rearrange existing wording;
   do not rewrite bullets into generic resume language. Cut connective tissue,
   never claims — every number and noun in the original must survive a rewrite.
3. REWRITE SPARINGLY. Set rewritten_text only when it meaningfully improves
   JD alignment. Most bullets should pass through unchanged (rewritten_text
   null). Selection is the primary tool; rewriting is the exception.
4. KEYWORD MIRRORING. Mirror the JD's exact terminology and casing for skills
   and technologies ("PostgreSQL" not "Postgres" if the JD says PostgreSQL).
   On first use of an acronym in a rewritten bullet, include both forms —
   e.g. "LLM (large language model)" — so literal ATS keyword matchers hit
   either variant.
5. INCLUDE EVERY ROLE. Never omit a role — vary the bullet count instead
   (recent roles ~3-5 bullets, older roles 1-2). Career continuity is
   non-negotiable.
6. FIT ASSESSMENT: be blunt. Name the match percentage against required
   qualifications and any hard gap no tailoring can fix. This is for the
   candidate's eyes only, not the resume.
```

**Maintenance note:** when a tailoring session surfaces a new reusable framing, it goes into the primary YAML (if content) or this prompt (if instruction) — same discipline as the Desktop workflow doc.

## ATS-safe PDF rules (rendering requirements)

The HTML/CSS template inside `generate_resume.py` must:

- **Visually match** `template/<Name>_Resume.pdf` — same fonts, spacing, section order, and heading treatment. Iterate with `--from-plan` re-renders until side-by-side comparison is close.
- Be **single column**, real selectable text throughout, standard section headings ("Experience", "Skills", "Education").
- Put **contact info in the document body** — never in a PDF header/footer region.
- Use **no tables, no text boxes, no images** for content layout. Standard font (match the template's).
- Use plain hyphen/ASCII bullets — no exotic unicode bullet glyphs.
- Set **PDF metadata**: document title `<Name> Resume`, author `Jane Doe` (via HTML `<title>`/meta — weasyprint carries these into the PDF). No "Copy of..." titles, no leftover hyperlink artifacts.

## Resolved design decisions

Previously open questions — all decided; the builder makes no judgment calls here:

1. **Matching approach:** single LLM call (`claude-opus-4-8`, structured output). No keyword/tag scoring. Tags are removed from the schema entirely.
2. **Summary variant selection:** chosen by the LLM in the tailoring plan.
3. **Styling:** hardcoded HTML/CSS template string in `generate_resume.py`, visually replicating `template/<Name>_Resume.pdf`. No `templates/` directory, no style config file.
4. **Output format:** PDF via `weasyprint`. (DOCX is a possible future addition; nothing in the design should preclude it, but do not build it now.)
5. **Contact & education:** static, in `data/resume_static.yaml`, merged at render time, never sent to the LLM.
6. **Page length:** not enforced by code. The prompt's bullet-count guidance plus human review keeps it ~2 pages; the candidate eyeballs the output.

## Out of scope (do not build)

- Cover letter generation — handled interactively via `docs/Resume_Tailoring_Workflow_and_Prompt.md` in Claude Desktop; the PDF is saved into the application folder manually. (Possible future script.)
- Outreach messages (`outreach.md`) — same: manual/interactive for now, the folder convention just reserves a home for them.
- Page-length enforcement, DOCX output, retry/caching layers, config files, tests beyond a basic smoke run. This is a personal script.

## Build steps (for the implementing model, in order)

1. Create `.gitignore` (`data/resume_primary.yaml`, `data/resume_static.yaml`, `applications/`) and `requirements.txt`.
2. Build `data/resume_primary.yaml` and `data/resume_static.yaml` by extracting content from `template/<Name>_Resume.pdf` (read it directly — it is text-based). Honor the standing framings in `docs/Resume_Tailoring_Workflow_and_Prompt.md`. Ask the candidate for historical superset bullets per role after the baseline is in place. Create the two anonymized `*.template.yaml` files alongside.
3. Create `prompts/tailoring_prompt.md` from the skeleton above.
4. Build `generate_resume.py`: load → LLM call (`messages.parse`) → validate → review gate → folder creation → weasyprint render. Include `--from-plan` and `--yes` flags.
5. Iterate on the HTML/CSS until the rendered PDF visually matches `template/<Name>_Resume.pdf` (use `--from-plan` to re-render without LLM calls).
6. Test end-to-end against 2–3 real job descriptions the candidate is applying to; review diffs and fit assessments together.
