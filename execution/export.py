#!/usr/bin/env python3
"""Export both Airtable tables to local markdown mirror files.

The Airtable is the source of truth; these mirrors are how an AI agent (or
you, with grep) consults it without hammering the API. Re-run before any
session that reads or extends your content.

Writes:
    sources/all-content.md
    sources/ig-posts.md

Usage:
    python execution/export.py
"""

import datetime as dt
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API = "https://api.airtable.com/v0"
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "sources"


def all_records(session, base, table):
    records, params = [], {}
    while True:
        resp = session.get(f"{API}/{base}/{table}", params=params, timeout=30)
        if resp.status_code >= 300:
            sys.exit(f"Airtable error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        records.extend(data.get("records", []))
        if "offset" not in data:
            return records
        params = {"offset": data["offset"]}


def render(records, title, primary_field):
    today = dt.date.today().isoformat()
    field_names = sorted({k for r in records for k in r.get("fields", {})})
    lines = [f"# Airtable: {title}", "",
             f"- Records: {len(records)}",
             f"- Fields: {', '.join(field_names)}",
             f"- Exported: {today}", ""]
    for record in records:
        fields = record.get("fields", {})
        heading = str(fields.get(primary_field, record["id"]))
        lines.append(f"## {heading}")
        for key in field_names:
            if key == primary_field or key not in fields:
                continue
            value = fields[key]
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            value = str(value).replace("\r\n", " ").replace("\n", " ")
            lines.append(f"- {key}: {value[:500]}")
        lines.append("")
    return "\n".join(lines)


def main():
    token = os.getenv("AIRTABLE_TOKEN")
    base = os.getenv("AIRTABLE_BASE_ID")
    content_table = os.getenv("ALL_CONTENT_TABLE_ID")
    posts_table = os.getenv("IG_POSTS_TABLE_ID")
    if not all([token, base, content_table, posts_table]):
        sys.exit("Error: Airtable env vars missing. Run execution/check.py.")

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    content = all_records(session, base, content_table)
    (OUT_DIR / "all-content.md").write_text(
        render(content, "All Content", "Content Title"), encoding="utf-8")
    print(f"Wrote {len(content)} records -> sources/all-content.md")

    posts = all_records(session, base, posts_table)
    (OUT_DIR / "ig-posts.md").write_text(
        render(posts, "IG Posts", "Media ID"), encoding="utf-8")
    print(f"Wrote {len(posts)} records -> sources/ig-posts.md")


if __name__ == "__main__":
    main()
