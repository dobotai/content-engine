#!/usr/bin/env python3
"""Register one content idea as a record in the All Content table.

The intake rule of the engine: every idea gets a record BEFORE it ships, and
the post's link gets pasted into the record's IG Post Link field at posting
time. This script makes the record half of that rule a single command.

Only the fields you pass are written. Nothing is defaulted into data fields,
because a blank is a fact you can fix later and a guess is a corruption you
will never find.

Usage:
    python execution/add_content.py --title "Why I fired my CRM" --status Idea
    python execution/add_content.py --title "..." --platform Instagram --hook "..." --caption "..."
"""

import argparse
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

API = "https://api.airtable.com/v0"


def main():
    parser = argparse.ArgumentParser(description="Register a content idea in All Content")
    parser.add_argument("--title", required=True)
    parser.add_argument("--platform", help="e.g. Instagram")
    parser.add_argument("--type", dest="content_type", help="your Content Type value")
    parser.add_argument("--status", default="Idea")
    parser.add_argument("--hook")
    parser.add_argument("--script-file", help="path to a file whose text becomes the Script field")
    parser.add_argument("--caption")
    parser.add_argument("--post-date", help="YYYY-MM-DD")
    parser.add_argument("--ig-post-link")
    parser.add_argument("--notes")
    parser.add_argument("--force", action="store_true", help="create even if the title already exists")
    args = parser.parse_args()

    token = os.getenv("AIRTABLE_TOKEN")
    base = os.getenv("AIRTABLE_BASE_ID")
    table = os.getenv("ALL_CONTENT_TABLE_ID")
    if not all([token, base, table]):
        sys.exit("Error: AIRTABLE_TOKEN, AIRTABLE_BASE_ID, ALL_CONTENT_TABLE_ID must be set in .env")

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    url = f"{API}/{base}/{table}"

    if not args.force:
        escaped = args.title.replace("'", "\\'")
        resp = session.get(url, params={
            "filterByFormula": f"{{Content Title}} = '{escaped}'", "maxRecords": 1}, timeout=30)
        if resp.status_code < 300 and resp.json().get("records"):
            existing = resp.json()["records"][0]
            sys.exit(f"A record with this title already exists ({existing['id']}). "
                     "Use --force to create anyway.")

    fields = {"Content Title": args.title, "Status": args.status}
    if args.platform:
        fields["Platform"] = [args.platform]
    if args.content_type:
        fields["Content Type"] = args.content_type
    if args.hook:
        fields["Hook"] = args.hook
    if args.script_file:
        with open(args.script_file, encoding="utf-8") as f:
            fields["Script"] = f.read()
    if args.caption:
        fields["Caption"] = args.caption
    if args.post_date:
        fields["Post Date"] = args.post_date
    if args.ig_post_link:
        fields["IG Post Link"] = args.ig_post_link
    if args.notes:
        fields["Notes"] = args.notes

    resp = session.post(url, json={"fields": fields}, timeout=30)
    if resp.status_code >= 300:
        sys.exit(f"Airtable error {resp.status_code}: {resp.text[:300]}")
    record = resp.json()
    print(f"Created {record['id']}: {args.title} (Status: {args.status})")


if __name__ == "__main__":
    main()
