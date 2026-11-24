#!/usr/bin/env python3
"""Job search tracker: a SQLite database plus a generated HTML dashboard.

The database and page live in applications/_dashboard/ (gitignored). Resumes,
job descriptions and transcripts stay in their application folders; the database
holds status, dates, people and next steps, and links to each folder.

    .venv/bin/python scripts/tracker.py list
    .venv/bin/python scripts/tracker.py set acme stage=Interviewing "next_action=Prep for CTO call" next_date=2026-11-09
    .venv/bin/python scripts/tracker.py event acme --date 2026-11-09 --kind interview --title "CTO round"
    .venv/bin/python scripts/tracker.py contact acme --name "Jane Doe" --title CTO --role "Hiring manager"
    .venv/bin/python scripts/tracker.py add acme company=Acme "role=VP Eng" stage=Applied type=job
    .venv/bin/python scripts/tracker.py check
    .venv/bin/python scripts/tracker.py build

Every write rebuilds the page.
"""
import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
APPS = ROOT / "applications"
DASH = APPS / "_dashboard"
DB_PATH = DASH / "tracker.db"
HTML_PATH = DASH / "dashboard.html"
TEMPLATE_PATH = Path(__file__).resolve().parent / "dashboard_template.html"

GRAND_CENTRAL = (40.7527, -73.9772)
STAGES = ["Lead / to apply", "Applied", "Screening", "Interviewing", "Final round",
          "Offer / SOW", "Active", "Closed"]
HIDDEN_DOC_SUFFIXES = {".yaml", ".bak", ".drawio", ".bkp", ".url"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    slug TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'job' CHECK (type IN ('job', 'contract')),
    source TEXT,            -- channel used for the source breakdown: Agency, Company site, Recruiter...
    via TEXT,               -- how it actually reaches you, e.g. Agency > Client
    stage TEXT NOT NULL,
    closed_from TEXT,       -- furthest stage reached, for closed opportunities
    status_note TEXT,
    next_owner TEXT CHECK (next_owner IN ('me', 'them') OR next_owner IS NULL),
    next_action TEXT,
    next_date TEXT,
    industry TEXT,
    work_mode TEXT NOT NULL DEFAULT 'Unknown',
    work_detail TEXT,       -- e.g. Mon-Wed in office
    location TEXT,
    neighborhood TEXT,
    address TEXT,
    lat REAL,
    lon REAL,
    gct_commute TEXT,       -- rough estimate from Grand Central
    comp_posted TEXT,
    comp_target TEXT,
    jd_url TEXT,            -- web link, or a path relative to applications/
    folder TEXT,            -- path relative to applications/
    logo TEXT,              -- file name in _dashboard/logos/
    confidential INTEGER NOT NULL DEFAULT 0,
    needs_verify TEXT,      -- what you should check, when a value was inferred
    updated TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL REFERENCES opportunities(slug) ON DELETE CASCADE,
    date TEXT NOT NULL,
    time TEXT,
    kind TEXT NOT NULL,     -- applied, submitted, call, interview, email, doc, feedback, note
    title TEXT NOT NULL,
    detail TEXT,
    source TEXT
);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    title TEXT,
    org TEXT,
    email TEXT,
    linkedin TEXT,
    UNIQUE (name, org)
);
CREATE TABLE IF NOT EXISTS opportunity_contacts (
    slug TEXT NOT NULL REFERENCES opportunities(slug) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    role TEXT,
    PRIMARY KEY (slug, contact_id)
);
"""


def connect():
    DASH.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    return db


def miles_from_grand_central(lat, lon):
    """Straight-line distance, not a travel route."""
    if lat is None or lon is None:
        return None
    lat1, lon1 = map(math.radians, GRAND_CENTRAL)
    lat2, lon2 = math.radians(lat), math.radians(lon)
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return round(3958.8 * 2 * math.asin(math.sqrt(h)), 1)


def href(rel_path):
    """Link from _dashboard/dashboard.html to a path under applications/."""
    return "../" + quote(rel_path)


def folder_docs(folder):
    """Documents in an application folder, skipping older versions and source YAML."""
    if not folder or not (APPS / folder).is_dir():
        return []
    base = APPS / folder
    docs = []
    for path in sorted(base.rglob("*")):
        parts = path.relative_to(base).parts
        if not path.is_file() or path.name.startswith(".") or path.suffix.lower() in HIDDEN_DOC_SUFFIXES:
            continue
        if any(p.startswith("previous-") or p == "zArchive" for p in parts[:-1]) or ".bak." in path.name:
            continue
        docs.append({"name": str(Path(*parts)), "href": href(f"{folder}/{Path(*parts)}")})
    return docs


def unmatched_folders(db):
    """Application folders with no opportunity pointing at them."""
    tracked = [r["folder"] for r in db.execute("SELECT folder FROM opportunities WHERE folder IS NOT NULL")]
    missing = []
    for path in sorted(APPS.iterdir()):
        if not path.is_dir() or path.name.startswith(("_", ".")) or path.name == "zArchive":
            continue
        if not any(f == path.name or f.startswith(path.name + "/") for f in tracked):
            missing.append(path.name)
    return missing


def broken_folders(db):
    return [r["folder"] for r in db.execute("SELECT folder FROM opportunities WHERE folder IS NOT NULL")
            if not (APPS / r["folder"]).is_dir()]


def load_data(db):
    opps = []
    for row in db.execute("SELECT * FROM opportunities ORDER BY company, role"):
        opp = dict(row)
        opp["gct_miles"] = miles_from_grand_central(opp["lat"], opp["lon"])
        opp["folder_href"] = href(opp["folder"]) + "/" if opp["folder"] else None
        url = opp["jd_url"]
        opp["jd_href"] = (url if url.startswith(("http://", "https://")) else href(url)) if url else None
        opp["logo_href"] = "logos/" + quote(opp["logo"]) if opp["logo"] else None
        opp["events"] = [dict(e) for e in db.execute(
            "SELECT date, time, kind, title, detail, source FROM events WHERE slug = ? ORDER BY date, id", (opp["slug"],))]
        opp["contacts"] = [dict(c) for c in db.execute(
            """SELECT c.name, c.title, c.org, c.email, c.linkedin, oc.role
               FROM opportunity_contacts oc JOIN contacts c ON c.id = oc.contact_id
               WHERE oc.slug = ? ORDER BY c.name""", (opp["slug"],))]
        opp["docs"] = folder_docs(opp["folder"])
        opps.append(opp)
    return {
        "built": datetime.now().strftime("%b %-d, %Y at %-I:%M %p"),
        "stages": STAGES,
        "opportunities": opps,
        "unmatched_folders": unmatched_folders(db),
        "broken_folders": broken_folders(db),
    }


def build(db):
    payload = json.dumps(load_data(db), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE_PATH.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"Built {HTML_PATH}")


def columns(db):
    return {r["name"] for r in db.execute("PRAGMA table_info(opportunities)")}


def parse_fields(db, pairs):
    allowed = columns(db) - {"slug"}
    fields = {}
    for pair in pairs:
        if "=" not in pair:
            sys.exit(f"Expected field=value, got: {pair}")
        key, value = pair.split("=", 1)
        if key not in allowed:
            sys.exit(f"Unknown field: {key}. Fields: {', '.join(sorted(allowed))}")
        fields[key] = value if value != "" else None
    if fields.get("stage") and fields["stage"] not in STAGES:
        sys.exit(f"Unknown stage: {fields['stage']}. Stages: {', '.join(STAGES)}")
    return fields


def require(db, slug):
    if not db.execute("SELECT 1 FROM opportunities WHERE slug = ?", (slug,)).fetchone():
        sys.exit(f"No opportunity with slug: {slug}. Run the list command to see slugs.")


def cmd_list(db, _args):
    for r in db.execute("""SELECT slug, stage, company, role, next_owner, next_action FROM opportunities
                           ORDER BY stage = 'Closed', company"""):
        print(f"{r['slug']:<24} {r['stage']:<16} {r['company']} | {r['role']}"
              + (f"  -> [{r['next_owner']}] {r['next_action']}" if r["next_action"] else ""))


def cmd_set(db, args):
    require(db, args.slug)
    fields = parse_fields(db, args.fields)
    fields["updated"] = datetime.now().isoformat(timespec="seconds")
    db.execute(f"UPDATE opportunities SET {', '.join(k + ' = ?' for k in fields)} WHERE slug = ?",
               (*fields.values(), args.slug))
    db.commit()
    build(db)


def cmd_add(db, args):
    fields = parse_fields(db, args.fields)
    for key in ("company", "role", "stage"):
        if not fields.get(key):
            sys.exit(f"add needs {key}=...")
    fields.update(slug=args.slug, updated=datetime.now().isoformat(timespec="seconds"))
    db.execute(f"INSERT INTO opportunities ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
               tuple(fields.values()))
    db.commit()
    build(db)


def cmd_event(db, args):
    require(db, args.slug)
    db.execute("INSERT INTO events (slug, date, time, kind, title, detail, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (args.slug, args.date, args.time, args.kind, args.title, args.detail, args.source))
    db.commit()
    build(db)


def cmd_contact(db, args):
    require(db, args.slug)
    db.execute("""INSERT INTO contacts (name, title, org, email, linkedin) VALUES (?, ?, ?, ?, ?)
                  ON CONFLICT (name, org) DO UPDATE SET
                    title = COALESCE(excluded.title, title),
                    email = COALESCE(excluded.email, email),
                    linkedin = COALESCE(excluded.linkedin, linkedin)""",
               (args.name, args.title, args.org, args.email, args.linkedin))
    contact_id = db.execute("SELECT id FROM contacts WHERE name = ? AND org IS ?", (args.name, args.org)).fetchone()["id"]
    db.execute("INSERT OR REPLACE INTO opportunity_contacts (slug, contact_id, role) VALUES (?, ?, ?)",
               (args.slug, contact_id, args.role))
    db.commit()
    build(db)


def cmd_check(db, _args):
    problems = [f"Folder has no record: {f}" for f in unmatched_folders(db)]
    problems += [f"Record points at a missing folder: {f}" for f in broken_folders(db)]
    problems += [f"Needs verifying, {r['slug']}: {r['needs_verify']}"
                 for r in db.execute("SELECT slug, needs_verify FROM opportunities WHERE needs_verify IS NOT NULL")]
    print("\n".join(problems) or "No problems found.")


def cmd_build(db, _args):
    build(db)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build").set_defaults(func=cmd_build)
    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("check").set_defaults(func=cmd_check)
    for name, func in (("set", cmd_set), ("add", cmd_add)):
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.add_argument("fields", nargs="+", metavar="field=value")
        p.set_defaults(func=func)
    p = sub.add_parser("event")
    p.add_argument("slug")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--time", help="Display text, e.g. 1:00 PM ET")
    p.add_argument("--kind", required=True,
                   choices=["applied", "submitted", "call", "interview", "email", "doc", "feedback", "note"])
    p.add_argument("--title", required=True)
    p.add_argument("--detail")
    p.add_argument("--source")
    p.set_defaults(func=cmd_event)
    p = sub.add_parser("contact")
    p.add_argument("slug")
    p.add_argument("--name", required=True)
    p.add_argument("--title")
    p.add_argument("--org")
    p.add_argument("--email")
    p.add_argument("--linkedin")
    p.add_argument("--role", help="Their part in this opportunity, e.g. Recruiter")
    p.set_defaults(func=cmd_contact)
    args = parser.parse_args()
    with connect() as db:
        args.func(db, args)


if __name__ == "__main__":
    main()
