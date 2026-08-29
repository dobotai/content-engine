#!/usr/bin/env python3
"""Instagram analytics snapshot via the Instagram API with Instagram Login.

Pulls owner insights per media (views, reach, likes, comments, saves, shares,
total interactions) plus an account-level roll-up, and appends them to local
CSV snapshot files. Append-only and idempotent per snapshot date: re-running
on the same day replaces that day's rows without touching history.

Requires INSTAGRAM_ACCESS_TOKEN in .env (the "IGAA..." token generated under
your Meta app's "API setup with Instagram login"). The token identifies the
account, and the Instagram account must be a Business or Creator account.

Meta renames insight metrics between API versions, so this script requests a
candidate set per media type and, if the batch is rejected, retries each
metric individually and keeps whatever the API accepts.

Usage:
    python execution/ig_pull.py
    python execution/ig_pull.py --limit 500
"""

import argparse
import csv
import datetime as dt
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
ANALYTICS_DIR = ROOT / "analytics"
MEDIA_CSV = ANALYTICS_DIR / "instagram_metrics.csv"
ACCOUNT_CSV = ANALYTICS_DIR / "instagram_account.csv"

GRAPH = "https://graph.instagram.com/v23.0"

# Candidate insight metrics by media product type. The API accepts a subset
# depending on version/media; unsupported ones are dropped automatically.
MEDIA_METRICS = {
    "REELS": ["reach", "likes", "comments", "saved", "shares",
              "total_interactions", "views"],
    "FEED": ["reach", "saved", "shares", "total_interactions", "views",
             "profile_visits", "follows"],
    "STORY": ["reach", "replies", "shares", "total_interactions", "views",
              "navigation"],
}
ACCOUNT_METRICS = ["reach", "profile_views", "website_clicks"]

MEDIA_FIELDS = [
    "snapshot_date", "media_id", "permalink", "media_type", "product_type",
    "timestamp", "caption", "likes", "comments", "reach", "saved", "shares",
    "total_interactions", "views", "profile_visits", "follows",
]
ACCOUNT_FIELDS = [
    "snapshot_date", "ig_user_id", "username", "account_type", "followers",
    "follows", "media_count", "reach", "profile_views", "website_clicks",
]


def local_date(ts):
    """The calendar day a post went live, in this machine's local time.

    Instagram returns UTC timestamps. Truncating those to a date files evening
    posts under the following day, which corrupts the date signal the sync's
    matcher relies on, so convert to local time first.
    """
    if not ts:
        return ""
    try:
        return (dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
                .astimezone().strftime("%Y-%m-%d"))
    except ValueError:
        return ts[:10]


def get(url, token, **params):
    """GET with one silent retry. `url` may be a node path or a full paging URL."""
    full = url if url.startswith("http") else f"{GRAPH}{url}"
    for attempt in range(2):
        resp = requests.get(full, params={"access_token": token, **params}, timeout=60)
        if resp.status_code == 200:
            return resp.json()
    return {"_error": resp.text[:300], "_status": resp.status_code}


def media_insights(media_id, product_type, token):
    """Return {metric: value} for one media, robust to unsupported metrics."""
    candidates = MEDIA_METRICS.get(product_type, MEDIA_METRICS["FEED"])
    data = get(f"/{media_id}/insights", token, metric=",".join(candidates))
    if "_error" not in data:
        return {m["name"]: m["values"][0]["value"] for m in data.get("data", [])}

    # Batch rejected (usually one bad metric for this media type/version).
    # Fall back to requesting each metric on its own and keep the winners.
    out = {}
    for metric in candidates:
        one = get(f"/{media_id}/insights", token, metric=metric)
        if "_error" not in one:
            for m in one.get("data", []):
                out[m["name"]] = m["values"][0]["value"]
    return out


def account_insights(ig_id, token):
    """Best-effort account-level daily insights; tolerant of API drift."""
    out = {}
    for metric in ACCOUNT_METRICS:
        resp = get(f"/{ig_id}/insights", token, metric=metric,
                   period="day", metric_type="total_value")
        if "_error" in resp:
            resp = get(f"/{ig_id}/insights", token, metric=metric, period="day")
        if "_error" in resp:
            continue
        for m in resp.get("data", []):
            if "total_value" in m:
                out[m["name"]] = m["total_value"].get("value", "")
            elif m.get("values"):
                out[m["name"]] = m["values"][-1]["value"]
    return out


def load_rows(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(path, fields, rows):
    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def replace_today(path, fields, new_rows, today, key="media_id"):
    """Write today's rows, merging rather than clobbering.

    A re-run whose pull came back short (transient API error mid-pagination)
    must not delete media captured by an earlier run the same day. Rows from
    this run win; rows for media this run did not see are preserved.
    """
    existing = load_rows(path)
    kept = [r for r in existing if r.get("snapshot_date") != today]
    fresh_keys = {r.get(key) for r in new_rows}
    preserved = [r for r in existing
                 if r.get("snapshot_date") == today and r.get(key) not in fresh_keys]
    if preserved:
        print(f"  ! this pull returned {len(preserved)} fewer media than an earlier "
              f"run today - keeping the earlier rows for them")
    write_rows(path, fields, kept + new_rows + preserved)
    return len(kept) + len(new_rows) + len(preserved)


def main():
    parser = argparse.ArgumentParser(description="Instagram analytics snapshot")
    parser.add_argument("--limit", type=int, default=10000,
                        help="most recent N media (default: the whole account)")
    args = parser.parse_args()

    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if not token:
        print("ERROR: INSTAGRAM_ACCESS_TOKEN must be set in .env (the IGAA... token from")
        print("  your Meta app's 'API setup with Instagram login' -> Generate token).")
        sys.exit(1)

    today = dt.date.today().isoformat()

    profile = get("/me", token,
                  fields="user_id,username,account_type,media_count,followers_count,follows_count")
    if "_error" in profile:
        print(f"ERROR: token rejected by Instagram API: {profile['_error']}")
        print("  Re-generate the token under 'API setup with Instagram login', or it expired.")
        sys.exit(1)

    ig_id = profile.get("user_id") or profile.get("id")
    print(f"Instagram analytics for @{profile.get('username', '?')} "
          f"({profile.get('account_type', '?')}, {today})")

    acct_vals = account_insights(ig_id, token)
    account_row = {
        "snapshot_date": today, "ig_user_id": ig_id,
        "username": profile.get("username", ""),
        "account_type": profile.get("account_type", ""),
        "followers": profile.get("followers_count", ""),
        "follows": profile.get("follows_count", ""),
        "media_count": profile.get("media_count", ""),
        "reach": acct_vals.get("reach", ""),
        "profile_views": acct_vals.get("profile_views", ""),
        "website_clicks": acct_vals.get("website_clicks", ""),
    }

    media_fields = "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count"
    media = []
    truncated = False
    resp = get("/me/media", token, fields=media_fields, limit=min(args.limit, 100))
    while True:
        if "_error" in resp:
            # Pagination died partway. Say so loudly: silently keeping a short
            # page looks like "the account lost posts" downstream.
            truncated = bool(media)
            if not media:
                print(f"ERROR fetching media: {resp['_error']}")
                sys.exit(1)
            print(f"  ! WARNING: media pagination failed after {len(media)} items "
                  f"({resp['_error'][:120]}) - this snapshot is INCOMPLETE")
            break
        media.extend(resp.get("data", []))
        if len(media) >= args.limit:
            break
        nxt = resp.get("paging", {}).get("next")
        if not nxt:
            break
        resp = get(nxt, token)
    media = media[:args.limit]
    if truncated:
        print(f"  Continuing with the {len(media)} media that were retrieved; "
              f"earlier rows for missing media are preserved.")
    print(f"  {len(media)} media; pulling per-post insights...")

    media_rows = []
    for m in media:
        product_type = m.get("media_product_type", "FEED")
        ins = media_insights(m["id"], product_type, token)
        caption = (m.get("caption") or "").replace("\r\n", " ").replace("\n", " ")
        media_rows.append({
            "snapshot_date": today,
            "media_id": m["id"],
            "permalink": m.get("permalink", ""),
            "media_type": m.get("media_type", ""),
            "product_type": product_type,
            "timestamp": local_date(m.get("timestamp")),
            # Store the caption near-full: the sync's text matcher needs it.
            "caption": caption[:2000],
            "likes": m.get("like_count", ""),
            "comments": m.get("comments_count", ""),
            "reach": ins.get("reach", ""),
            "saved": ins.get("saved", ""),
            "shares": ins.get("shares", ""),
            "total_interactions": ins.get("total_interactions", ""),
            "views": ins.get("views", ""),
            "profile_visits": ins.get("profile_visits", ""),
            "follows": ins.get("follows", ""),
        })

    m_total = replace_today(MEDIA_CSV, MEDIA_FIELDS, media_rows, today)
    replace_today(ACCOUNT_CSV, ACCOUNT_FIELDS, [account_row], today)

    print(f"\nAccount @{account_row['username']}: {account_row['followers']} followers, "
          f"{account_row['media_count']} posts, reach {account_row['reach'] or 'n/a'}")
    print(f"Wrote {len(media_rows)} media rows ({m_total} total) -> {MEDIA_CSV}")
    print(f"Wrote account row -> {ACCOUNT_CSV}")


if __name__ == "__main__":
    main()
