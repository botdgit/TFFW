# ⚽ The Football Final Whistle — Autonomous Instagram Agent

A fully autonomous, zero-cost agent that runs a football commentary
Instagram page 24/7: it monitors live matches, results, league tables,
transfer news and breaking stories, **verifies every claim against
multiple sources**, generates branded green-and-white graphics and
captions, and publishes on a safe cadence — with a full audit trail and
admin dashboard.

**Designed to cost £0**: it runs on GitHub Actions cron (free for public
repos), uses free sports/news data sources, renders graphics with Pillow,
and hosts media + dashboard straight from this repository.

---

## How it works

```
        ┌────────────────────── GitHub Actions (free cron) ──────────────────────┐
        │                                                                        │
 every 10 min          twice an hour                daily 07:00 UTC              │
 ┌─────────────┐      ┌──────────────┐             ┌──────────────┐              │
 │ agent-live  │      │ agent-news   │             │ agent-digest │              │
 └──────┬──────┘      └──────┬───────┘             └──────┬───────┘              │
        ▼                    ▼                            ▼                      │
  football-data.org    BBC / Sky / Guardian / ESPN   standings + fixtures        │
  + TheSportsDB        RSS feeds                                                 │
        │                    │                            │                      │
        └───────────► VERIFICATION GATE ◄─────────────────┘                      │
                      • match facts: official feed + cross-check (2 sources)     │
                      • news: ≥2 independent outlets or it is NOT posted         │
                      • confidence < MIN_CONFIDENCE → skipped, logged            │
                             │
                             ▼
                      CONTENT ENGINE
                      • formats: LIVE WHISTLE · FINAL WHISTLE · TRANSFER WHISTLE
                        VAR CHECK · TEAM SHEET · BREAKING
                      • Claude-written captions (template fallback), hashtags,
                        alt text, engagement prompts
                      • Pillow-rendered branded green/white graphics
                             │
                             ▼
                      QUEUE (SQLite, deduped, rate-limited)
                             │
                             ▼
                      PUBLISHER  →  Buffer → Instagram   (or IG Graph API)
                             │
                             ▼
                      DASHBOARD (dashboard/index.html) + full audit log
```

State (SQLite DB), generated media and the dashboard are committed back to
the repo by each run, so the agent has persistent memory with zero
infrastructure.

## Folder structure

```
tffw/
├── config.py              # all env-driven configuration
├── db.py                  # SQLite schema + queue/claims/audit helpers
├── http_client.py         # retries, backoff, rate-limit handling, API log
├── main.py                # CLI entrypoint (live|news|digest|publish|dashboard)
├── pipeline.py            # detect → verify → generate → queue → publish
├── verification.py        # two-source verification + confidence scoring
├── dashboard.py           # static admin dashboard generator
├── sources/
│   ├── football_data.py   # football-data.org (scores, fixtures, tables)
│   ├── thesportsdb.py     # TheSportsDB (free cross-check + keyless fallback)
│   └── rss_news.py        # BBC / Sky / Guardian / ESPN feeds
├── content/
│   ├── formats.py         # recurring formats, hashtags, engagement prompts
│   ├── captions.py        # Claude captions (brand voice) + template fallback
│   └── graphics.py        # Pillow green/white templates (1080×1350)
└── publish/
    ├── buffer_api.py      # Buffer GraphQL → Instagram
    └── instagram_graph.py # direct Instagram Graph API
.github/workflows/         # the three cron loops
scripts/selfcheck.py       # offline end-to-end smoke test
data/tffw.sqlite3          # agent memory (committed by the workflows)
output/media/              # generated graphics (served via raw.githubusercontent)
dashboard/index.html       # admin dashboard (regenerated every run)
docs/DEPLOYMENT.md         # step-by-step production setup
```

## Quick start (local)

```bash
pip install -r requirements.txt
python scripts/selfcheck.py          # offline smoke test, no keys needed
cp .env.example .env                 # optional: add keys
python -m tffw.main news             # run a real ingestion cycle
python -m tffw.main live
open dashboard/index.html            # see the queue + audit trail
```

The agent works **with zero API keys** (TheSportsDB + RSS, template
captions, DRY_RUN queueing). Each key you add upgrades it:

| Key | Free? | Unlocks |
|---|---|---|
| `FOOTBALL_DATA_TOKEN` | ✅ free tier | minute-level live scores, kick-offs, league tables |
| `ANTHROPIC_API_KEY` | pay-per-use (pennies/post) | Claude-written captions in the brand voice |
| `BUFFER_ACCESS_TOKEN` + `BUFFER_CHANNEL_ID` | ✅ Buffer free plan | autonomous publishing to Instagram via Buffer |
| `IG_USER_ID` + `IG_ACCESS_TOKEN` | ✅ free | direct Instagram Graph API publishing |

## Safety / editorial rules (enforced in code)

- **Never invent information** — captions are generated only from the
  verified facts dict; the Claude prompt hard-forbids adding details, and
  the template fallback is purely mechanical.
- **Two-source rule** — news/transfer stories need ≥2 independent outlets
  (`NEWS_MIN_SOURCES`); match results are cross-checked between
  football-data.org and TheSportsDB. Conflicting results are scored 0.4
  and never posted.
- **Low confidence → no post** — anything under `MIN_CONFIDENCE` (0.8) is
  parked as `skipped_low_confidence` and revisited when more sources appear.
- **Copyright-safe by construction** — no third-party images/video are
  ever downloaded or reposted; every visual is rendered from our own
  template. News text is used as short facts with source attribution.
- **Rate-limited** — max posts per run/day, minimum gap between posts,
  duplicate detection via content hashing, API backoff with Retry-After.
- **Full audit trail** — every source item, claim, confidence score, API
  call, publish response and error is in SQLite and on the dashboard.

## Production

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**. Short version: this repo
*is* the deployment — the three workflows in `.github/workflows/` run on
GitHub's cron the moment they're on the default branch, and repo
secrets/variables control keys, `DRY_RUN` and the publisher.
