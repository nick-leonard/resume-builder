# Resume Builder

A small personal tool for tailoring one resume to one job, so the hiring team can
see quickly how my experience lines up with what they need. It doesn't apply to
jobs, fill in forms or send anything anywhere: every resume it produces is reviewed
and sent by a person. Claude proposes a plan (which of my existing bullets to use,
in what order, with light rewrites), the script prints that plan for review,
including every before-and-after rewrite and which of the job's key terms the resume
covers, and nothing is rendered until I approve it. The resume (docx + PDF) is built
from my own source content only, so the model can't fabricate its way into it.

See [`docs/resume-tailoring-system-design.md`](docs/resume-tailoring-system-design.md)
for the full design and [`docs/Resume_Tailoring_Workflow_and_Prompt.md`](docs/Resume_Tailoring_Workflow_and_Prompt.md)
for the interactive cover-letter workflow.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Create your real data files from the checked-in templates:
cp data/resume_primary.template.yaml data/resume_primary.yaml
cp data/resume_static.template.yaml data/resume_static.yaml
# ...then edit both with your real content. Both are gitignored.

# API key and model go in .env (gitignored), read by generate_resume.py:
#   ANTHROPIC_API_KEY=...
#   RESUME_MODEL=claude-sonnet-5-5

# PDFs are converted from the .docx by headless LibreOffice:
brew install --cask libreoffice
```

## Usage

Every resume goes through `generate_resume.py`, whichever agent (Claude Code,
Codex, Antigravity) or terminal you run it from. The tailoring plan comes from
one of two places:

```bash
# API mode (default): one Claude API call billed to the key in .env.
.venv/bin/python generate_resume.py \
    --jd "path/to/jd.txt" --company "Acme Corp" --role "VP of Engineering" \
    [--model claude-opus-5-5] [--yes]

# Agent mode: no API call. Writes tailoring_request.md; the agent you're in
# writes tailoring.yaml from it, using its own model and quota.
.venv/bin/python generate_resume.py \
    --jd "path/to/jd.txt" --company "Acme Corp" --role "VP of Engineering" --prepare

# Validate, review and render a plan (either mode's), no LLM call.
.venv/bin/python generate_resume.py \
    --from-plan "applications/Acme Corp - VP of Engineering/tailoring.yaml"
```

A run fills `applications/<Company> - <Role>/` with `job_description.txt`,
`tailoring.yaml` (the plan / audit trail), and the tailored
`<Name>_Resume.yaml`, `.docx` and `.pdf`. API mode saves the plan before
asking to render; without a terminal (or if you decline) it stops there, and
`--from-plan` renders it later. `--yes` skips the confirmation.

The review also shows which phrases will be bold (up to 8, at most one per
bullet, always text already in the resume) and how many of the JD's key terms
the resume covers, including the ones it's missing.

To hand-edit a tailored resume, edit its `<Name>_Resume.yaml` (wrap a
phrase in `**...**` to bold it, or remove the markers to unbold it) and
re-render just that file. Re-running `--from-plan` would rebuild the YAML from
the plan (the edited one is kept as `<Name>_Resume.yaml.bak`).

```bash
.venv/bin/python scripts/resume_yaml_to_docx.py \
    "applications/Acme Corp - VP of Engineering/<Name>_Resume.yaml" --pdf
```

## Import a final edited PDF

When the final resume was edited manually in Google Docs or Word, export it to
PDF and rebuild its comparable YAML snapshot with:

```bash
.venv/bin/python scripts/resume_pdf_to_yaml.py \
    "applications/Acme/<Name>_Resume.pdf"
```

The default output is beside the PDF with the same basename and a `.yaml`
extension. Existing output is protected unless `--force` is passed. Use
`--extract-only` to inspect the locally extracted and privacy-sanitized text
without making an API call.

The importer removes the candidate name, contact line, page footers, and the
Education section before sending text to Claude. It uses
`data/resume_primary.yaml` as the default stable-ID reference and emits the
canonical ordering `headline`, `summary_bullets`, `experience`, `skills`.

Native `.gdoc` files contain only a Google Drive pointer, not document text.
Export the Google Doc to PDF before running the importer.

## Privacy model

- `data/resume_primary.yaml` (bullets, sent to the LLM) and
  `data/resume_static.yaml` (contact + education, **never** sent) are gitignored.
- The `*.template.yaml` files are anonymized and checked in, so the repo can be
  published without leaking PII.
- Generated output (`applications/`) is gitignored.
- `.gitignore` is an allowlist: nothing is committed unless it's listed there,
  so notes, transcripts and other private files kept beside the code stay out.

## Private overlays (optional)

- **Standing framings.** Copy `prompts/standing_framings.example.md` to
  `prompts/standing_framings.md` (gitignored) and list the facts about your own
  history the model must never soften or "fix": exact budget figures, title
  arcs, date overlaps. `generate_resume.py` appends it to the tailoring prompt.
- **Cover letter template.** `scripts/cover_letter_to_docx.py` fills a Word
  template with your letterhead at `template/<Name>_Cover_Letter.docx`
  (gitignored, since it carries contact details). Supply your own there.
- **Your name** never appears in the code. Output filenames (`<Name>_Resume.pdf`)
  and document titles come from `data/resume_static.yaml`: an optional
  `files: {prefix, display_name}` block, otherwise `contact.name`.
