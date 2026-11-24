#!/usr/bin/env python3
"""Render a full-resume YAML (canonical schema) plus data/resume_static.yaml to .docx.

Layout mirrors the candidate's original Google Doc resume.

    python scripts/resume_yaml_to_docx.py RESUME.yaml [OUTPUT.docx] [--pdf]

--pdf also converts the .docx to a .pdf beside it with headless LibreOffice
(`brew install --cask libreoffice`), so the PDF matches the docx exactly.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "data" / "resume_static.yaml"
SOFFICE_APP = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
# macOS keeps Arial here, where headless LibreOffice doesn't look (it falls back
# to Liberation Sans); linking the files into its profile's fonts dir fixes that.
SYSTEM_FONTS = Path("/System/Library/Fonts/Supplemental")


from identity import FILE_PREFIX, DISPLAY_NAME, RESUME_BASENAME  # noqa: E402  (name lives in resume_static.yaml)

# Document metadata, carried into the PDF (see ATS-safe rules in the design doc).
DOC_TITLE = f"{DISPLAY_NAME} Resume"

FONT = "Arial"
BODY_PT = 10.25
RIGHT_TAB = Inches(7.45)
SKILL_LABELS = {
    "ai": "AI",
    "languages": "Languages",
    "tools": "Technologies & Tools",
    "architecture_patterns": "Architecture Patterns",
    "engineering_practices": "Engineering Practices",
}

# Vertical breathing room (pt): after each bullet and role summary, and above
# each company.
BULLET_GAP = 1.5
COMPANY_GAP = 7


def set_run(run, *, bold=None, italic=None, size=None, underline=None):
    run.font.name = FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    run.font.size = Pt(size or BODY_PT)
    run.font.color.rgb = RGBColor(0, 0, 0)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if underline is not None:
        run.underline = underline
    return run


def para(doc, *, align=None, before=0, after=0, right_tab=False):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = 1.0
    if align is not None:
        p.alignment = align
    if right_tab:
        pf.tab_stops.add_tab_stop(RIGHT_TAB, WD_TAB_ALIGNMENT.RIGHT)
    return p


def add_hyperlink(p, text, url, size):
    part = p.part
    r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = p.add_run(text)
    set_run(run, size=size, underline=True)
    link.append(run._element)
    p._p.append(link)


def bottom_border(p):
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in {"w:val": "single", "w:sz": "6", "w:space": "4", "w:color": "999999"}.items():
        bottom.set(qn(k), v)
    bdr.append(bottom)
    pPr.append(bdr)


def text_runs(p, text, size=None):
    # **phrase** marks a highlighted (bold) span; generate_resume.py adds them
    # for JD keywords, and they can be added or removed by hand in the YAML.
    for i, chunk in enumerate(" ".join(text.split()).split("**")):
        if chunk:
            set_run(p.add_run(chunk), bold=True if i % 2 else None, size=size)


def bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(BULLET_GAP)
    pf.line_spacing = 1.0
    pf.left_indent = Inches(0.25)
    pf.first_line_indent = Inches(-0.18)
    pf.tab_stops.add_tab_stop(Inches(0.25))
    text_runs(p, text)


def plain_bullets(doc):
    # The default template draws bullets with Symbol's private-use glyph, which
    # LibreOffice swaps for OpenSymbol (taller, so each bullet's first line sits
    # apart from the rest). A Unicode bullet in the body font renders the same
    # in Word and LibreOffice.
    for lvl in doc.part.numbering_part.element.iter(qn("w:lvl")):
        fonts = lvl.find(f"{qn('w:rPr')}/{qn('w:rFonts')}")
        if fonts is None or fonts.get(qn("w:ascii")) != "Symbol":
            continue
        lvl.find(qn("w:lvlText")).set(qn("w:val"), "•")
        for attr in ("w:ascii", "w:hAnsi"):
            fonts.set(qn(attr), FONT)


def title_runs(p, title):
    m = re.match(r"^(.*?)(\s*\(.*\))$", title)
    main, paren = (m.group(1), m.group(2)) if m else (title, "")
    set_run(p.add_run(main), bold=True, italic=True)
    if paren:
        set_run(p.add_run(paren), italic=True)


def heading(doc, text):
    p = para(doc, align=WD_ALIGN_PARAGRAPH.CENTER, before=6, after=2)
    p.paragraph_format.keep_with_next = True
    set_run(p.add_run(text), bold=True, size=12)


def footer(section, name):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run(f"{name} | "), size=8)
    # One run per field part, with an explicit result run: without it LibreOffice
    # renders the page number at the body size instead of this run's size.
    for part in ("begin", "instr", "separate", "result", "end"):
        run = set_run(p.add_run(), size=8)
        if part == "instr":
            instr = OxmlElement("w:instrText")
            instr.set(qn("xml:space"), "preserve")
            instr.text = "PAGE"
            run._r.append(instr)
        elif part == "result":
            run.text = "1"
        else:
            fld = OxmlElement("w:fldChar")
            fld.set(qn("w:fldCharType"), part)
            run._r.append(fld)


def render(resume: dict, static: dict, out: Path) -> None:
    doc = Document()
    plain_bullets(doc)
    # Base style = resume font. Otherwise every paragraph mark falls back to the
    # template default (11pt Calibri, 1.15 spacing), which inflates the last line
    # of each paragraph and pushed a two-page resume onto a third page.
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.font.size = Pt(BODY_PT)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = 1.0
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.left_margin = sec.right_margin = Inches(0.5)
    sec.top_margin = Inches(0.4)
    sec.bottom_margin = Inches(0.5)
    # Keep the page-number footer inside the bottom margin; at Word's default
    # 0.5" distance it pushes body text up and costs about two lines per page.
    sec.footer_distance = Inches(0.25)
    sec.header_distance = Inches(0.2)

    c = static["contact"]
    p = para(doc, align=WD_ALIGN_PARAGRAPH.CENTER)
    set_run(p.add_run(c["name"]), bold=True, size=20)
    p = para(doc, align=WD_ALIGN_PARAGRAPH.CENTER)
    set_run(p.add_run(resume["headline"]), bold=True, italic=True, size=11.5)
    p = para(doc, align=WD_ALIGN_PARAGRAPH.CENTER, after=6)
    set_run(p.add_run(f"{c['phone']} | "), size=10)
    add_hyperlink(p, c["email"], f"mailto:{c['email']}", 10)
    set_run(p.add_run(" | "), size=10)
    add_hyperlink(p, c["linkedin"], f"https://{c['linkedin']}", 10)
    set_run(p.add_run(f" | {c['location']}"), size=10)
    bottom_border(p)

    for b in resume["summary_bullets"]:
        bullet(doc, b["text"])

    heading(doc, "Professional Experience")
    for job in resume["experience"]:
        company, location = job["company"], job.get("location")
        positions = job["positions"]
        compact = not location and len(positions) == 1
        for i, pos in enumerate(positions):
            titles, dates = pos["title_lines"], pos["dates"]
            # Keep a company/title header on the same page as the start of the
            # content under it, so a role never starts at a page bottom. The body
            # itself may split across pages rather than leave a gap on the page.
            has_body = bool(pos.get("summary") or pos["bullets"])
            if i == 0 and not compact:
                p = para(doc, before=COMPANY_GAP, right_tab=True)
                p.paragraph_format.keep_with_next = True
                set_run(p.add_run(company), bold=True, size=11)
                if location:
                    set_run(p.add_run(f"\t{location}"))
            # Client engagement nested under the consulting practice: prefix the
            # client name to the first title line ("xNilio - Chief Technology Officer").
            client = pos.get("client")
            for j, title in enumerate(titles or [None]):
                date = dates[j] if j < len(dates) else ""
                # Gap above a later position's first title only, not between its title lines.
                gap = (7 if client else 3) if (i and j == 0) else 0
                p = para(doc, before=COMPANY_GAP if (compact and j == 0) else gap, right_tab=True)
                if client and j == 0:
                    set_run(p.add_run(client), bold=True)
                    set_run(p.add_run(" - "))
                p.paragraph_format.keep_with_next = has_body
                if compact and j == 0:
                    if not titles and " - " in company:
                        head, tail = company.split(" - ", 1)
                        set_run(p.add_run(f"{head} - "))
                        set_run(p.add_run(tail), bold=True, italic=True)
                    elif title:
                        set_run(p.add_run(company), bold=True, size=11)
                        set_run(p.add_run(" - "))
                        title_runs(p, title)
                    else:
                        set_run(p.add_run(company), bold=True, italic=True, size=11)
                elif title:
                    title_runs(p, title)
                if date:
                    set_run(p.add_run(f"\t{date}"), italic=False)
            if pos.get("summary"):
                p = para(doc, after=BULLET_GAP)
                # Let a role start at a page bottom with one summary line, so
                # LibreOffice (PDF) splits it like Word instead of pushing the
                # whole role to the next page and leaving a gap.
                p.paragraph_format.widow_control = False
                text_runs(p, pos["summary"]["text"])
            for b in pos["bullets"]:
                bullet(doc, b["text"])

    heading(doc, "Technical Skills")
    for key, items in resume["skills"].items():
        p = para(doc)
        set_run(p.add_run(f"{SKILL_LABELS.get(key, key.title())}: "), bold=True, italic=True)
        set_run(p.add_run(", ".join(items)))

    heading(doc, "Education")
    for e in static["education"]:
        p = para(doc, right_tab=True)
        school = re.sub(r"\s*\(.*\)", "", e["school"])
        set_run(p.add_run(f"{school} - "))
        set_run(p.add_run(e["degree"]), bold=True, italic=True)
        set_run(p.add_run(f"\t{e['location']} - {e['date']}"))

    footer(sec, c["name"])
    doc.core_properties.title = DOC_TITLE
    doc.core_properties.author = c["name"]
    doc.save(out)


def convert_to_pdf(docx_path: Path) -> Path:
    soffice = shutil.which("soffice") or (str(SOFFICE_APP) if SOFFICE_APP.exists() else None)
    if not soffice:
        sys.exit("ERROR: --pdf needs LibreOffice: brew install --cask libreoffice")
    # A throwaway profile keeps this working while the LibreOffice app is open.
    with tempfile.TemporaryDirectory() as profile:
        fonts_dir = Path(profile) / "user" / "fonts"
        fonts_dir.mkdir(parents=True)
        for font in SYSTEM_FONTS.glob(f"{FONT}*.ttf"):
            (fonts_dir / font.name).symlink_to(font)
        subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={Path(profile).as_uri()}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(docx_path.parent),
                str(docx_path),
            ],
            check=True,
            capture_output=True,
        )
    pdf_path = docx_path.with_suffix(".pdf")
    if not pdf_path.exists():
        sys.exit(f"ERROR: LibreOffice did not produce {pdf_path}")
    return pdf_path


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--pdf"]
    if len(args) not in (1, 2):
        sys.exit(__doc__)
    src = Path(args[0])
    out = Path(args[1]) if len(args) == 2 else src.with_suffix(".docx")
    render(yaml.safe_load(src.read_text()), yaml.safe_load(STATIC.read_text()), out)
    print(out)
    if "--pdf" in sys.argv[1:]:
        print(convert_to_pdf(out))


if __name__ == "__main__":
    main()
