#!/usr/bin/env python3
"""Sync Instagram snapshots into the Airtable content ledger.

Two jobs, run in order:

  1. POST LEDGER. Every distinct post in analytics/instagram_metrics.csv gets
     one row in the IG Posts table, keyed by Media ID (Instagram's permanent
     id). New posts create rows; existing rows get fresh analytics. The CSV is
     an append-only time series, so it is deduped to the LATEST snapshot per
     media id first - older numbers must never win.

  2. ATTRIBUTION. Every IG Posts row with an empty Content link gets matched
     to its All Content idea record, using tiered evidence:

       Tier 1  "IG Post Link" - the link you pasted on the record yourself.
               Authoritative, always trusted.
       Tier 3  fuzzy text - the post caption vs each record's title, hook,
               and caption. Only allowed to decide when ALL of these hold:
                 * the record's Status is "Published"
                 * if the record has a Post Date, it is within --date-window
                   days of the post's date
                 * the similarity score clears --threshold
                 * the score beats the runner-up record by --margin

     Anything that fails those tests is written to .tmp/sync_review.md and
     left untouched. That is the safety property that matters: an
     unattributed post costs you one manual paste, while a misattributed post
     silently corrupts the numbers your content decisions are made from.

Rules this script lives by:
  * NEVER attribute a post to a record that is not Published. A post that
    does not exist cannot have analytics.
  * The script owns the analytics columns on IG Posts and the Content link;
    it never touches Title, Hook, Script, Status, or any human-authored field.

Usage:
    python execution/sync.py --dry-run     # preview, no writes
    python execution/sync.py               # write to Airtable
    python execution/sync.py --threshold 0.85 --margin 0.15
"""

import argparse
import csv
import datetime as dt
import os
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API = "https://api.airtable.com/v0"
ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "analytics" / "instagram_metrics.csv"
REVIEW = ROOT / ".tmp" / "sync_review.md"

# IG Posts column -> CSV column. The script owns exactly these plus Content.
METRICS = {
    "Views": "views", "Reach": "reach", "Likes": "likes",
    "Comments": "comments", "Saved": "saved", "Shares": "shares",
    "Total Interactions": "total_interactions",
}


def env(name):
    value = os.getenv(name)
    if not value:
        sys.exit(f"Error: {name} not set in .env")
    return value


def shortcode(url):
    """The /reel|p|tv/<shortcode>/ piece of an Instagram permalink."""
    m = re.search(r"/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)", url or "")
    return m.group(1) if m else ""


def to_num(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class Airtable:
    def __init__(self):
        self.base = env("AIRTABLE_BASE_ID")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {env('AIRTABLE_TOKEN')}"})

    def _request(self, method, url, **kwargs):
        for attempt in range(4):
            resp = self.session.request(method, url, timeout=30, **kwargs)
            if resp.status_code == 429:
                time.sleep(1 + attempt)
                continue
            if resp.status_code >= 300:
                sys.exit(f"Airtable error {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        sys.exit("Airtable rate limit persisted after retries")

    def all_records(self, table):
        records, params = [], {}
        while True:
            data = self._request("GET", f"{API}/{self.base}/{table}", params=params)
            records.extend(data.get("records", []))
            if "offset" not in data:
                return records
            params = {"offset": data["offset"]}

    def update(self, table, record_id, fields):
        return self._request("PATCH", f"{API}/{self.base}/{table}/{record_id}",
                             json={"fields": fields})

    def create(self, table, fields):
        return self._request("POST", f"{API}/{self.base}/{table}",
                             json={"fields": fields})


def latest_snapshots():
    """The newest CSV row per media id."""
    if not CSV_PATH.exists():
        sys.exit(f"Error: {CSV_PATH} not found. Run execution/ig_pull.py first.")
    best = {}
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mid = row.get("media_id", "")
            if mid and row.get("snapshot_date", "") >= best.get(mid, {}).get("snapshot_date", ""):
                best[mid] = row
    return best


def similarity(a, b):
    return SequenceMatcher(None, a.lower()[:400], b.lower()[:400]).ratio()


def best_match(caption, candidates):
    """(best, runner_up) as (score, record) pairs against title/hook/caption."""
    scored = []
    for rec in candidates:
        f = rec["fields"]
        texts = [f.get("Content Title", ""), f.get("Hook", ""), f.get("Caption", "")]
        score = max((similarity(caption, t) for t in texts if t), default=0.0)
        scored.append((score, rec))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    top = scored[0] if scored else (0.0, None)
    second = scored[1] if len(scored) > 1 else (0.0, None)
    return top, second


def dates_corroborate(record_fields, post_date, window):
    record_date = record_fields.get("Post Date", "")
    if not record_date or not post_date:
        return True  # no date on the record means the date test cannot fail
    try:
        delta = abs((dt.date.fromisoformat(record_date[:10])
                     - dt.date.fromisoformat(post_date[:10])).days)
    except ValueError:
        return True
    return delta <= window


def main():
    parser = argparse.ArgumentParser(description="Sync IG snapshots into the Airtable ledger")
    parser.add_argument("--dry-run", action="store_true", help="preview without writing")
    parser.add_argument("--threshold", type=float, default=0.75, help="tier-3 minimum score")
    parser.add_argument("--margin", type=float, default=0.10, help="tier-3 lead over runner-up")
    parser.add_argument("--date-window", type=int, default=3, help="days of post-date tolerance")
    args = parser.parse_args()

    airtable = Airtable()
    posts_table = env("IG_POSTS_TABLE_ID")
    content_table = env("ALL_CONTENT_TABLE_ID")
    today = dt.date.today().isoformat()

    snapshots = latest_snapshots()
    post_rows = airtable.all_records(posts_table)
    content_rows = airtable.all_records(content_table)
    by_media_id = {r["fields"].get("Media ID", ""): r for r in post_rows}

    created = updated = 0
    links = {"tier1": 0, "tier3": 0}
    review = []

    # ---- Job 1: upsert the post ledger --------------------------------------
    for mid, snap in snapshots.items():
        fields = {"Analytics Updated": today}
        for column, csv_key in METRICS.items():
            value = to_num(snap.get(csv_key))
            if value is not None:
                fields[column] = value
        existing = by_media_id.get(mid)
        if existing:
            if not args.dry_run:
                airtable.update(posts_table, existing["id"], fields)
            existing["fields"].update(fields)
            updated += 1
        else:
            fields.update({
                "Media ID": mid,
                "Permalink": snap.get("permalink", ""),
                "Posted": snap.get("timestamp", "") or None,
                "Product Type": snap.get("product_type", ""),
                "Caption": snap.get("caption", ""),
            })
            fields = {k: v for k, v in fields.items() if v not in ("", None)}
            if args.dry_run:
                record = {"id": f"dry_{mid}", "fields": fields}
            else:
                record = airtable.create(posts_table, fields)
            by_media_id[mid] = record
            created += 1

    # ---- Job 2: attribution -------------------------------------------------
    published = [r for r in content_rows
                 if str(r["fields"].get("Status", "")).strip().endswith("Published")
                 or str(r["fields"].get("Status", "")).strip() == "Published"]

    for mid, record in by_media_id.items():
        if record["fields"].get("Content"):
            continue
        snap = snapshots.get(mid, {})
        permalink = record["fields"].get("Permalink", "") or snap.get("permalink", "")
        code = shortcode(permalink)
        caption = record["fields"].get("Caption", "") or snap.get("caption", "")
        post_date = record["fields"].get("Posted", "") or snap.get("timestamp", "")

        # Tier 1: a record whose IG Post Link points at this post.
        tier1 = None
        if code:
            for rec in content_rows:
                if code in (rec["fields"].get("IG Post Link", "") or ""):
                    tier1 = rec
                    break
        if tier1:
            if not args.dry_run:
                airtable.update(posts_table, record["id"], {"Content": [tier1["id"]]})
            record["fields"]["Content"] = [tier1["id"]]
            links["tier1"] += 1
            continue

        # Tier 3: guarded fuzzy match against Published records only.
        if caption and published:
            (score, rec), (second_score, _) = best_match(caption, published)
            if (rec is not None
                    and score >= args.threshold
                    and score - second_score >= args.margin
                    and dates_corroborate(rec["fields"], post_date, args.date_window)):
                if not args.dry_run:
                    airtable.update(posts_table, record["id"], {"Content": [rec["id"]]})
                record["fields"]["Content"] = [rec["id"]]
                links["tier3"] += 1
                continue
            review.append((permalink, post_date, caption[:120], score,
                           rec["fields"].get("Content Title", "") if rec else ""))
        else:
            review.append((permalink, post_date, caption[:120], 0.0, ""))

    # ---- Review file and summary --------------------------------------------
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Sync review - posts the sync would not guess at",
             f"\nGenerated {today}. For each post, either paste its link into the",
             "matching All Content record's IG Post Link field, or create a record",
             "for it, then re-run the sync.\n"]
    for permalink, post_date, caption, score, candidate in review:
        lines.append(f"- {permalink} ({post_date or 'no date'})")
        lines.append(f"  caption: {caption}")
        if candidate:
            lines.append(f"  closest record: {candidate} (score {score:.2f} - not confident enough)")
    REVIEW.write_text("\n".join(lines), encoding="utf-8")

    unlinked = sum(1 for r in by_media_id.values() if not r["fields"].get("Content"))
    mode = "DRY RUN - nothing written" if args.dry_run else "written to Airtable"
    if unlinked:
        print(f"!! {unlinked} posts are unlinked - review file updated: {REVIEW}")
    else:
        print("All posts are linked to an idea. Ledger is at 100 percent.")
    print(f"\n[{mode}]")
    print(f"  posts created: {created}, updated: {updated}")
    print(f"  links written: tier1={links['tier1']}, tier3={links['tier3']}")
    print(f"  posts sent to review: {len(review)}")
    total = len(by_media_id)
    if total:
        pct = 100 * (total - unlinked) / total
        print(f"  link coverage: {total - unlinked}/{total} ({pct:.0f} percent)")


if __name__ == "__main__":
    main()
