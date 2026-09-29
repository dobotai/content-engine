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

Then copy `.env.example` to `.env`. The steps below fill it in.

## Get your Airtable token

You do not build the database. The engine builds it for you, so the only manual step is handing it a key.

1. Go to [airtable.com/create/tokens](https://airtable.com/create/tokens) and press **Create token**. Name it anything.
2. Under **Access**, choose **All current and future bases in all current and future workspaces**. The base does not exist yet, so there is nothing narrower to point the token at.
3. Under **Scopes**, add all four:

   | Scope | Why it's needed |
   |---|---|
   | `data.records:read` | Read your content records |
   | `data.records:write` | Create and update records |
   | `schema.bases:read` | See the structure of a base |
   | `schema.bases:write` | Create the base, tables, and fields |

4. Press **Create token** and copy the value. Airtable shows it exactly once.
5. Paste it into `.env`:

```
AIRTABLE_TOKEN=patXXXXXXXXXXXXXX.XXXXXXXX...
```

The two schema scopes are the difference between Claude walking you through 23 fields by hand and Claude building the whole thing in one command.

## Setup Prompt 1 - build the database (paste into Claude Code)

Open Claude Code inside the `content-engine` folder and paste this whole block:

```
Build the Airtable side of this content engine. My AIRTABLE_TOKEN is already in .env with data.records read+write and schema.bases read+write.

Step 1 - the workspace. Ask me for my Airtable workspace URL, and wait for it. I get it by opening airtable.com, clicking my workspace in the sidebar, and copying the address bar. It looks like https://airtable.com/workspaces/wspXXXXXXXX/workspace.

Step 2 - build it. Run:

python execution/setup_airtable.py --workspace "<the URL I gave you>"

That creates the "Content Calendar" base with both tables (All Content and IG Posts), every field, and the link between them, then writes AIRTABLE_BASE_ID, ALL_CONTENT_TABLE_ID and IG_POSTS_TABLE_ID into my .env.

If it stops because I already have a base with that name, do not force it. Ask me whether that base is one I'm already using. If it is, re-run with --name "Content Engine" to build a separate one. Only if I confirm I want the engine built into the existing base, re-run with --reuse, which adds the missing tables and fields and changes nothing else.

Step 3 - confirm. Run:

python execution/check.py

and confirm both tables come back OK. If anything fails, read the error, tell me the exact value to fix and how, then re-run. Never change the table or field names in execution/setup_airtable.py to get past an error, because every other script reads those exact names.

Step 4 - orient me. Open the base link the setup script printed and tell me what I'm looking at: which table I type into, which one the scripts own, and what the link field between them is for.
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
| `execution/setup_airtable.py` | Builds the base, both tables, all fields, and the link, then writes the ids into `.env`. Run once; safe to re-run. |
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
