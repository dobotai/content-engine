# The Content Engine

A source of truth for your content, built from three parts you already have access to: Airtable, Claude Code, and your own Instagram analytics.

It keeps one ledger with two tables. **All Content** holds every idea you've ever made, and **IG Posts** holds every Instagram post you've ever published, one row per post, keyed by Instagram's permanent Media ID. Every post links back to the idea it came from, and your analytics flow in automatically every morning. At any scale, you can answer three questions in seconds: what have I made, what have I posted, and how did it perform.

The engine does not write content and it never posts anything. It keeps the record that makes your content decisions honest.

## What you need

- [Claude Code](https://claude.com/claude-code) installed
- An Airtable account (free tier works)
- An Instagram **Business or Creator** account (switch for free in the Instagram app under settings)
- Python 3.10+

## Install

```
git clone https://github.com/dobotai/content-engine.git
cd content-engine
pip install -r requirements.txt
```

Then copy `.env.example` to `.env`. The two setup prompts below fill it in.

## Setup Prompt 1 - Airtable (paste into Claude Code)

Open Claude Code inside the `content-engine` folder and paste this whole block:

```
Set up the Airtable side of this content engine with me, interactively, one step at a time. Wait for me to confirm each step before moving on.

Step 1 - the base. Walk me through creating an Airtable base called "Content Calendar" with two tables.

Table 1, "All Content", with these exact fields:
- Content Title (single line text, the primary field)
- Platform (multiple select: Instagram, TikTok, YouTube, LinkedIn)
- Content Type (single select: Educational, Story, Demo)
- Status (single select: Idea, Scripted, Recorded, Published)
- Hook (long text)
- Script (long text)
- Caption (long text)
- Post Date (date)
- IG Post Link (URL)
- Notes (long text)

Table 2, "IG Posts", with these exact fields:
- Media ID (single line text, the primary field)
- Permalink (URL)
- Posted (date)
- Product Type (single line text)
- Caption (long text)
- Views (number)
- Reach (number)
- Likes (number)
- Comments (number)
- Saved (number)
- Shares (number)
- Total Interactions (number)
- Analytics Updated (date)

Then have me add a field called "Content" to IG Posts, type "Link to another record", pointing at All Content, and rename the auto-created reverse field in All Content to "IG Posts".

Step 2 - credentials. Walk me through creating a personal access token in Airtable's developer hub with data.records:read and data.records:write scopes, granted to this base only. Then help me find the base ID (starts with "app", in the base URL) and both table IDs (start with "tbl", in each table's URL).

Step 3 - wire it up. Put AIRTABLE_TOKEN, AIRTABLE_BASE_ID, ALL_CONTENT_TABLE_ID, and IG_POSTS_TABLE_ID into my .env file (I'll paste the values when you ask), then run:

python execution/check.py

and confirm both tables come back OK. If anything fails, tell me exactly which value to fix and how.
```

## Setup Prompt 2 - Instagram (paste into Claude Code)

```
Now set up the Instagram side of this content engine with me, interactively, one step at a time. Wait for my confirmation at each step, and if what's on my screen doesn't match what you describe, I'll paste what I see so you can reroute me. Meta moves these menus around, so navigate by what I report, not by assumption.

Step 1 - the app. Walk me through creating an app at developers.facebook.com and adding the Instagram product to it, using the setup path for Business/Creator accounts ("API setup with Instagram login").

Step 2 - the token. Walk me through connecting my Instagram professional account to the app and generating an access token (it starts with "IGAA"). Make sure the permissions during the connect flow include reading my own media and insights. If the token I get is short-lived, walk me through exchanging it for the long-lived version.

Step 3 - wire it up. Put the token into .env as INSTAGRAM_ACCESS_TOKEN, then run:

python execution/check.py

and confirm the Instagram line prints my username and post count. Then run:

python execution/ig_pull.py --limit 5

and show me the five rows it wrote to analytics/instagram_metrics.csv so I can sanity-check the numbers against the Instagram app.
```

## First run - fill the ledger (paste into Claude Code)

```
Both setups check out. Now fill the ledger.

1. Run python execution/ig_pull.py with no limit, so the snapshot reaches the very beginning of my account. Compare the post count it reports to my actual Instagram profile and tell me if there's a meaningful gap.

2. Run python execution/sync.py --dry-run and walk me through the plan: how many post rows it will create, and how many posts it can't attribute to an idea.

3. If the plan looks right to me, run python execution/sync.py for real.

4. Open .tmp/sync_review.md. These are the posts the sync refused to guess at. Help me work through them: for each one, either find the matching All Content record and paste the post's permalink into that record's IG Post Link field, or create a record for it with python execution/add_content.py using ONLY what's true (the caption and date from the post itself, Status "Published"). Never invent titles, dates, or numbers.

5. Re-run the sync until it reports 100 percent link coverage.
```

If you're starting from zero recorded ideas, that review list is your whole posting history introducing itself. Working through it once is the last time you'll ever do content archaeology.

## Daily use

Two habits keep the ledger true forever:

1. **The intake rule.** Every new idea gets a record before it ships (`python execution/add_content.py --title "..."`), and when you post it, you paste the post's link into the record's IG Post Link field. That paste is the strongest evidence the sync has, and a post recorded this way can never end up unattributed.
2. **The daily loop.** Schedule `python execution/daily.py` every morning (ask Claude Code to set it up in Task Scheduler or cron for you). It pulls fresh numbers, syncs them into the ledger, refreshes the local mirror files in `sources/`, and logs one line to `analytics/sync_log.txt`. If the log line ever shows unlinked posts, you're one paste away from fixing it.

## The scripts

| Script | What it does |
|---|---|
| `execution/check.py` | Proves your credentials reach Airtable and Instagram. Run it first when anything fails. |
| `execution/ig_pull.py` | Snapshots every post's metrics from the Instagram API into `analytics/` (append-only). |
| `execution/sync.py` | Upserts one IG Posts row per post and links each post to its idea. `--dry-run` previews. |
| `execution/add_content.py` | Registers one idea as an All Content record. |
| `execution/export.py` | Mirrors both tables to `sources/*.md` so your AI agent can read the ledger locally. |
| `execution/daily.py` | Runs pull, sync, and export in order and appends to the log. Schedule this one. |

## Why the sync refuses to guess

The sync links a post to an idea on two kinds of evidence: a link you pasted yourself (always trusted), or a text match that passes every test at once (the record is actually Published, the dates corroborate, the match score is high, and it clearly beats the runner-up). Anything less lands in `.tmp/sync_review.md` for you to decide.

The reason is a rule worth keeping even if you change everything else here: an unattributed post costs you one manual paste, while a misattributed post silently corrupts the numbers you make decisions with. The engine will always choose asking you over being confidently wrong.

## License

MIT. Use it, change it, ship it.
