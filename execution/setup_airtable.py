#!/usr/bin/env python3
"""Build the Content Calendar base in Airtable: tables, fields, and the link.

This replaces the click-through setup. Given a token that carries the schema
scopes, it creates the base, both tables, every field, and the two-way link
between them, then writes the resulting ids into .env.

Safe to run twice: pass --reuse (or --base) and only the missing tables and
fields are created. Nothing is ever deleted, and nothing is renamed except the
reverse link field Airtable creates for you. Without --reuse the script stops
rather than touch a base you already have under that name.

Usage:
    python execution/setup_airtable.py --workspace wspXXXXXXXXXXXX
    python execution/setup_airtable.py --workspace https://airtable.com/workspaces/wspXXXX/workspace
    python execution/setup_airtable.py --base appXXXXXXXXXXXX   # extend an existing base
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
API = "https://api.airtable.com/v0/meta"

BASE_NAME = "Content Calendar"
ALL_CONTENT = "All Content"
IG_POSTS = "IG Posts"

LINK_FIELD = "Content"        # on IG Posts, points at All Content
REVERSE_FIELD = "IG Posts"    # the field Airtable auto-creates on All Content

SCOPE_HELP = ("Create a token at https://airtable.com/create/tokens with all four scopes "
              "(data.records:read, data.records:write, schema.bases:read, schema.bases:write) "
              "and access to all current and future bases.")


def _choices(*names):
    return {"choices": [{"name": n} for n in names]}


SCHEMA = {
    ALL_CONTENT: [
        {"name": "Content Title", "type": "singleLineText"},
        {"name": "Platform", "type": "multipleSelects",
         "options": _choices("Instagram", "TikTok", "YouTube", "LinkedIn")},
        {"name": "Content Type", "type": "singleSelect",
         "options": _choices("Educational", "Story", "Demo")},
        {"name": "Status", "type": "singleSelect",
         "options": _choices("Idea", "Scripted", "Recorded", "Published")},
        {"name": "Hook", "type": "multilineText"},
        {"name": "Script", "type": "multilineText"},
        {"name": "Caption", "type": "multilineText"},
        {"name": "Post Date", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
        {"name": "IG Post Link", "type": "url"},
        {"name": "Notes", "type": "multilineText"},
    ],
    IG_POSTS: [
        {"name": "Media ID", "type": "singleLineText"},
        {"name": "Permalink", "type": "url"},
        {"name": "Posted", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
        {"name": "Product Type", "type": "singleLineText"},
        {"name": "Caption", "type": "multilineText"},
        {"name": "Views", "type": "number", "options": {"precision": 0}},
        {"name": "Reach", "type": "number", "options": {"precision": 0}},
        {"name": "Likes", "type": "number", "options": {"precision": 0}},
        {"name": "Comments", "type": "number", "options": {"precision": 0}},
        {"name": "Saved", "type": "number", "options": {"precision": 0}},
        {"name": "Shares", "type": "number", "options": {"precision": 0}},
        {"name": "Total Interactions", "type": "number", "options": {"precision": 0}},
        {"name": "Analytics Updated", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
    ],
}


def api(method, path, token, payload=None):
    """One request, one silent retry, then a readable failure."""
    url = API + path
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    for attempt in (1, 2):
        try:
            resp = requests.request(method, url, headers=headers, json=payload, timeout=30)
        except requests.RequestException as exc:
            if attempt == 1:
                time.sleep(2)
                continue
            sys.exit("FAIL: could not reach Airtable: {}".format(exc))
        if resp.status_code in (401, 403):
            sys.exit("FAIL: Airtable rejected the token ({}) on {} {}.\n      {}\n      {}".format(
                resp.status_code, method, path, SCOPE_HELP, resp.text[:300]))
        if resp.status_code in (429, 500, 502, 503) and attempt == 1:
            time.sleep(2)
            continue
        if resp.status_code >= 300:
            sys.exit("FAIL: {} {} returned {}: {}".format(
                method, path, resp.status_code, resp.text[:400]))
        return resp.json() if resp.text else {}


def find_base(token, name):
    """Return the id of a base with this name, if the token can already see one."""
    offset = None
    while True:
        path = "/bases" + ("?offset=" + offset if offset else "")
        data = api("GET", path, token)
        for base in data.get("bases", []):
            if base.get("name", "").strip().lower() == name.strip().lower():
                return base["id"]
        offset = data.get("offset")
        if not offset:
            return None


def create_base(token, workspace, name):
    payload = {
        "name": name,
        "workspaceId": workspace,
        "tables": [{"name": table, "fields": fields} for table, fields in SCHEMA.items()],
    }
    return api("POST", "/bases", token, payload)["id"]


def get_tables(token, base_id):
    return api("GET", "/bases/{}/tables".format(base_id), token).get("tables", [])


def ensure_tables(token, base_id):
    """Create any missing table, then any missing field. Returns {name: table}."""
    tables = {t["name"]: t for t in get_tables(token, base_id)}
    for name, fields in SCHEMA.items():
        if name not in tables:
            print("  creating table {}".format(name))
            api("POST", "/bases/{}/tables".format(base_id), token,
                {"name": name, "fields": fields})
            continue
        table = tables[name]
        existing = {f["name"] for f in table["fields"]}
        for field in fields:
            if field["name"] not in existing:
                print("  adding field {}.{}".format(name, field["name"]))
                api("POST", "/bases/{}/tables/{}/fields".format(base_id, table["id"]),
                    token, field)
    return {t["name"]: t for t in get_tables(token, base_id)}


def ensure_link(token, base_id, tables):
    """Link IG Posts to All Content, and name the reverse field on All Content."""
    ig, content = tables[IG_POSTS], tables[ALL_CONTENT]
    link = next((f for f in ig["fields"]
                 if f["type"] == "multipleRecordLinks"
                 and f.get("options", {}).get("linkedTableId") == content["id"]), None)
    if link is None:
        print("  linking {}.{} to {}".format(IG_POSTS, LINK_FIELD, ALL_CONTENT))
        link = api("POST", "/bases/{}/tables/{}/fields".format(base_id, ig["id"]), token,
                   {"name": LINK_FIELD, "type": "multipleRecordLinks",
                    "options": {"linkedTableId": content["id"]}})

    inverse_id = link.get("options", {}).get("inverseLinkFieldId")
    content = next(t for t in get_tables(token, base_id) if t["id"] == content["id"])
    reverse = next((f for f in content["fields"] if f["id"] == inverse_id), None)
    if reverse is None:
        reverse = next((f for f in content["fields"]
                        if f["type"] == "multipleRecordLinks"
                        and f.get("options", {}).get("linkedTableId") == ig["id"]), None)
    if reverse is None:
        print("  NOTE: no reverse link field on {}. This base has one-way links enabled; "
              "add a '{}' link field there by hand.".format(ALL_CONTENT, REVERSE_FIELD))
    elif reverse["name"] != REVERSE_FIELD:
        print("  renaming {}.{} to {}".format(ALL_CONTENT, reverse["name"], REVERSE_FIELD))
        api("PATCH", "/bases/{}/tables/{}/fields/{}".format(base_id, content["id"], reverse["id"]),
            token, {"name": REVERSE_FIELD})


def write_env(values):
    """Set or replace keys in .env, leaving every other line untouched."""
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    else:
        example = ROOT / ".env.example"
        lines = example.read_text(encoding="utf-8").splitlines() if example.exists() else []
    for key, value in values.items():
        replaced = False
        for i, line in enumerate(lines):
            if line.strip().startswith(key + "="):
                lines[i] = "{}={}".format(key, value)
                replaced = True
                break
        if not replaced:
            lines.append("{}={}".format(key, value))
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Create the Airtable base this content engine runs on.")
    parser.add_argument("--workspace", help="Workspace id (wsp...) or the workspace URL. "
                                            "Required the first time, unless --base is given.")
    parser.add_argument("--base", help="Use an existing base id (app...) instead of creating one.")
    parser.add_argument("--name", default=BASE_NAME,
                        help='Base name (default: "{}")'.format(BASE_NAME))
    parser.add_argument("--reuse", action="store_true",
                        help="If a base with this name already exists, add the missing tables "
                             "and fields to it instead of stopping.")
    args = parser.parse_args()

    load_dotenv(ENV_PATH)
    token = os.getenv("AIRTABLE_TOKEN")
    if not token:
        sys.exit("FAIL: AIRTABLE_TOKEN is not set in .env.\n      " + SCOPE_HELP)

    base_id = args.base
    if base_id and not base_id.startswith("app"):
        sys.exit("FAIL: --base should be a base id starting with 'app', got " + repr(base_id))

    if not base_id:
        existing = find_base(token, args.name)
        if existing and not args.reuse:
            sys.exit('STOP: you already have a base named "{}" ({}).\n'
                     "      Adding the engine's tables and fields to it would change a base you "
                     "are already using, so this script will not do it on its own.\n"
                     "      Re-run with --reuse to build into that base, or with "
                     '--name "Content Engine" to create a separate one.'.format(args.name, existing))
        if existing:
            print('Reusing the existing base "{}" ({}).'.format(args.name, existing))
            base_id = existing

    if not base_id:
        if not args.workspace:
            sys.exit("FAIL: --workspace is required to create a base.\n"
                     "      Open airtable.com, click your workspace in the sidebar, and copy the "
                     "URL. It looks like https://airtable.com/workspaces/wspXXXXXXXX/workspace.\n"
                     "      Pass the whole URL or just the wsp... id.")
        match = re.search(r"wsp[A-Za-z0-9]+", args.workspace)
        if not match:
            sys.exit("FAIL: no workspace id (wsp...) found in " + repr(args.workspace))
        workspace = match.group(0)
        print('Creating base "{}" in workspace {}'.format(args.name, workspace))
        base_id = create_base(token, workspace, args.name)
        print("  base created: " + base_id)

    tables = ensure_tables(token, base_id)
    missing = [name for name in SCHEMA if name not in tables]
    if missing:
        sys.exit("FAIL: tables still missing after setup: " + ", ".join(missing))
    ensure_link(token, base_id, tables)

    write_env({
        "AIRTABLE_BASE_ID": base_id,
        "ALL_CONTENT_TABLE_ID": tables[ALL_CONTENT]["id"],
        "IG_POSTS_TABLE_ID": tables[IG_POSTS]["id"],
    })

    print("\nDone. Written to .env:")
    print("  AIRTABLE_BASE_ID=" + base_id)
    print("  ALL_CONTENT_TABLE_ID=" + tables[ALL_CONTENT]["id"])
    print("  IG_POSTS_TABLE_ID=" + tables[IG_POSTS]["id"])
    print("\nYour base: https://airtable.com/" + base_id)
    print("Next: python execution/check.py")


if __name__ == "__main__":
    main()
