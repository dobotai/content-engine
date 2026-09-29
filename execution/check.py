#!/usr/bin/env python3
"""Connection check: prove the .env credentials reach both Airtable tables.

Run this first after setup, and first again whenever anything fails later.
It answers the only diagnostic question that matters at the start: is the
problem credentials, or code?

Usage:
    python execution/check.py
"""

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

API = "https://api.airtable.com/v0"


def main():
    token = os.getenv("AIRTABLE_TOKEN")
    base = os.getenv("AIRTABLE_BASE_ID")
    tables = {
        "All Content": os.getenv("ALL_CONTENT_TABLE_ID"),
        "IG Posts": os.getenv("IG_POSTS_TABLE_ID"),
    }
    for name, value in [("AIRTABLE_TOKEN", token), ("AIRTABLE_BASE_ID", base),
                        ("ALL_CONTENT_TABLE_ID", tables["All Content"]),
                        ("IG_POSTS_TABLE_ID", tables["IG Posts"])]:
        if not value:
            sys.exit(f"FAIL: {name} is not set in .env")

    ok = True
    for label, table_id in tables.items():
        resp = requests.get(f"{API}/{base}/{table_id}",
                            headers={"Authorization": f"Bearer {token}"},
                            params={"maxRecords": 3}, timeout=30)
        if resp.status_code == 401 or resp.status_code == 403:
            print(f"FAIL: {label}: token rejected ({resp.status_code}). Regenerate "
                  "AIRTABLE_TOKEN at airtable.com/create/tokens with data.records:read, "
                  "data.records:write, schema.bases:read, schema.bases:write, and access "
                  "to all current and future bases.")
            ok = False
            continue
        if resp.status_code == 404:
            print(f"FAIL: {label}: table not found. Check the tbl... id in .env "
                  "(copy it from the table's URL, not its display name).")
            ok = False
            continue
        if resp.status_code >= 300:
            print(f"FAIL: {label}: {resp.status_code} {resp.text[:200]}")
            ok = False
            continue
        records = resp.json().get("records", [])
        field_names = sorted({k for r in records for k in r.get("fields", {})})
        print(f"OK: {label}: {len(records)} sample record(s); "
              f"fields seen: {', '.join(field_names) if field_names else '(table is empty)'}")

    ig_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if ig_token:
        resp = requests.get("https://graph.instagram.com/v23.0/me",
                            params={"access_token": ig_token,
                                    "fields": "username,media_count"}, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            print(f"OK: Instagram: @{data.get('username', '?')}, "
                  f"{data.get('media_count', '?')} posts")
        else:
            print(f"FAIL: Instagram token rejected: {resp.text[:200]}")
            ok = False
    else:
        print("SKIP: INSTAGRAM_ACCESS_TOKEN not set yet (Prompt 2 sets it up)")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
