"""Who the resume belongs to, for output filenames and document titles.

Read from data/resume_static.yaml (gitignored): an optional
`files: {prefix, display_name}` block, otherwise contact.name. This keeps the
candidate's name out of the code.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

STATIC = Path(__file__).resolve().parents[1] / "data" / "resume_static.yaml"


def identity(static: dict | None = None) -> tuple[str, str]:
    """(file prefix, display name) from the static data."""
    if static is None:
        static = (yaml.safe_load(STATIC.read_text()) if STATIC.exists() else None) or {}
    name = (static.get("contact") or {}).get("name") or "Candidate"
    files = static.get("files") or {}
    display = files.get("display_name") or name
    prefix = files.get("prefix") or re.sub(r"\W+", "_", display).strip("_")
    return prefix, display


FILE_PREFIX, DISPLAY_NAME = identity()
RESUME_BASENAME = f"{FILE_PREFIX}_Resume"  # .yaml / .docx / .pdf in each application folder
