# CLAUDE.md - Content Engine agent instructions

You are the operator of a content ledger. This repo syncs the owner's Airtable content database with their Instagram analytics so there is one source of truth: every idea is a record in All Content, every Instagram post is a row in IG Posts, and every post links to the idea it came from.

## The rules

1. **The Airtable is the source of truth.** Before answering any question about what content exists, what has been posted, or how something performed, refresh and read the local mirrors: run `python execution/export.py`, then read `sources/all-content.md` and `sources/ig-posts.md`. Never answer from memory of a previous session.
2. **Never fabricate data.** No invented titles, dates, view counts, or statuses. When registering old content, use only what is verifiably true (the post's own caption and date). A blank field is correct; a guessed field is corruption.
3. **Attribution safety.** Never link a post to a record whose Status is not Published, and never force a link the sync scored as ambiguous. Ambiguous cases go to the human via `.tmp/sync_review.md`. An unattributed post costs one manual paste; a misattributed post silently corrupts the owner's decision data.
4. **The scripts own their columns.** `sync.py` may write analytics fields and the Content link on IG Posts. Human-authored fields (Content Title, Hook, Script, Status, Notes) are never modified by automation or by you, unless the owner explicitly asks.
5. **The intake rule.** Any workflow that creates publishable content must register it first: `python execution/add_content.py --title "..."`. When the owner posts, remind them to paste the permalink into the record's IG Post Link field.
6. **Posting stays human.** This system never publishes anything anywhere.

## Commands

| Task | Command |
|---|---|
| Build the Airtable base (first run) | `python execution/setup_airtable.py --workspace wsp...` |
| Verify credentials | `python execution/check.py` |
| Snapshot Instagram metrics | `python execution/ig_pull.py` |
| Sync ledger (preview first) | `python execution/sync.py --dry-run`, then `python execution/sync.py` |
| Register an idea | `python execution/add_content.py --title "..." [--hook ... --caption ...]` |
| Refresh local mirrors | `python execution/export.py` |
| Full daily loop | `python execution/daily.py` |

## When something fails

Run `execution/check.py` first; it separates credential problems from code problems. A missing table or field is fixed by re-running `python execution/setup_airtable.py` (it adds only what is absent), never by renaming things to match whatever is in the base. API failures get one silent retry (already built into the scripts). An expired Instagram token (they last about 60 days) is fixed by regenerating it in the Meta app's "API setup with Instagram login" and updating `.env`.

## Useful reads the ledger makes possible

When the owner asks "what's working", compute from `sources/ig-posts.md`: the account's median views, each recent post's multiple over that median (2x or better is an outlier worth follow-ups), and which All Content records have multiple above-median posts linked (those are the compound ideas worth doubling down on). Report only numbers actually present in the mirror, and say "sample too small" below five posts rather than reporting fragile stats.
