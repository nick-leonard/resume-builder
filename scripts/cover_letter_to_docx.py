#!/usr/bin/env python3
"""Render a cover letter written in Markdown into template/Nick_Leonard_Cover_Letter.docx.

    python scripts/cover_letter_to_docx.py COVER_LETTER.md [OUTPUT.docx] [--pdf]

The header (name, headline, contact links) and footer come from the template.
The headline is replaced with the tailored resume's headline when a
Nick_Leonard_Resume.yaml sits beside the letter, so letter and resume match.
Leading header lines in the Markdown (bold/italic name and title, the contact
line) are skipped; every later paragraph becomes a body paragraph. A
"Subject:" paragraph gets a bold label and a blank line above and below.
**phrase** bolds a keyword, as on the resume, at most one per paragraph.
Output defaults to Nick_Leonard_Cover_Letter.docx beside the Markdown file.
--pdf also converts it with headless LibreOffice.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml
from docx import Document
from docx.shared import Pt

from resume_yaml_to_docx import ROOT, convert_to_pdf, set_run, text_runs

TEMPLATE = ROOT / "template" / "Nick_Leonard_Cover_Letter.docx"
OUTPUT_NAME = "Nick_Leonard_Cover_Letter.docx"
DOC_TITLE = "Nick Leonard Cover Letter"

BODY_PT = 11
PARA_GAP = 10  # pt after each body paragraph
BLANK_LINE = 13  # pt, one empty line at BODY_PT
SUBJECT = "Subject:"


def body_paragraphs(md: str) -> list[str]:
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", md) if p.strip()]
    # The header block: emphasized name/title lines and the "a | b | c" contact line.
    while paras and (paras[0].startswith("*") or " | " in paras[0]):
        paras.pop(0)
    for p in paras:
        if p.count("**") > 2:
            sys.exit(f"ERROR: more than one **highlight** in a paragraph: {p[:70]}...")
    return paras


def render(md_path: Path, out: Path) -> None:
    doc = Document(TEMPLATE)
    # The template's trailing empty bullet paragraphs are placeholders.
    for p in doc.paragraphs:
        if p.style.name == "List Bullet" and not p.text.strip():
            p._element.getparent().remove(p._element)

    resume = md_path.parent / "Nick_Leonard_Resume.yaml"
    if resume.exists():
        headline = yaml.safe_load(resume.read_text())["headline"]
        runs = doc.paragraphs[1].runs
        runs[0].text = headline
        for r in runs[1:]:
            r.text = ""

    body = body_paragraphs(md_path.read_text())
    for i, text in enumerate(body):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.line_spacing = 1.0
        subject = text.startswith(SUBJECT)
        signoff = text.rstrip(",") in {"Sincerely", "Best", "Thanks", "Thank you", "Regards"}
        # Room under the header rule (a blank line more above the subject), a
        # blank line between subject and greeting; sign-off and name sit together.
        pf.space_before = Pt((12 + BLANK_LINE if subject else 12) if i == 0 else 0)
        if subject:
            pf.space_after = Pt(PARA_GAP + BLANK_LINE)
        else:
            pf.space_after = Pt(0 if signoff or i == len(body) - 1 else PARA_GAP)
        if signoff:
            pf.keep_with_next = True
        if subject:
            # text_runs collapses whitespace, so the space goes with the label.
            set_run(p.add_run(f"{SUBJECT} "), bold=True, size=BODY_PT)
            text = text[len(SUBJECT):]
        text_runs(p, text, size=BODY_PT)

    doc.core_properties.title = DOC_TITLE
    doc.save(out)


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--pdf"]
    if len(args) not in (1, 2):
        sys.exit(__doc__)
    src = Path(args[0])
    out = Path(args[1]) if len(args) == 2 else src.parent / OUTPUT_NAME
    render(src, out)
    print(out)
    if "--pdf" in sys.argv[1:]:
        print(convert_to_pdf(out))


if __name__ == "__main__":
    main()
