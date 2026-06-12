# Deployment — production runbook

The repository **is** the deployment. The three workflows in
`.github/workflows/` run on GitHub Actions' free cron as soon as they are
on the repository's **default branch**:

| Workflow | Schedule | Job |
|---|---|---|
| `agent-live` | every 10 min | match monitoring → queue → publish |
| `agent-news` | :07 and :37 | RSS ingestion → verification → queue → publish |
| `agent-digest` | 07:00 UTC daily | league table + fixtures preview |

Each run commits the SQLite state, generated media and the refreshed
dashboard back to the branch. **The repo must stay public** — that keeps
Actions minutes unlimited *and* lets Buffer/Instagram fetch the generated
images from `raw.githubusercontent.com` for free.

## Configuration (repo → Settings → Secrets and variables → Actions)

### Secrets
| Secret | Required for | Where to get it |
|---|---|---|
| `BUFFER_ACCESS_TOKEN` | autonomous publishing via Buffer | https://publish.buffer.com/settings/api → "Create access token" |
| `FOOTBALL_DATA_TOKEN` | minute-level live scores + tables | https://www.football-data.org/client/register (free) |
| `ANTHROPIC_API_KEY` | Claude-written captions | https://platform.claude.com (optional — template captions otherwise) |
| `IG_ACCESS_TOKEN` | only if `PUBLISHER=instagram` | Meta app (see below) |

### Variables (Settings → ... → Variables)
| Variable | Default | Notes |
|---|---|---|
| `BUFFER_CHANNEL_ID` | — | from Buffer; the connected Instagram channel id |
| `PUBLISHER` | `buffer` | `buffer` / `instagram` / `none` |
| `DRY_RUN` | `false` | set `true` to pause real publishing instantly |
| `COMPETITIONS` | `PL,CL,WC` | football-data.org codes |

Without `BUFFER_ACCESS_TOKEN`, the agent still runs every cycle and
builds the verified queue — posts simply remain `queued` until a
publisher is configured (or are published by a Claude session via the
Buffer connector, which is how this page was bootstrapped).

## Behaviour without any secrets

Fully functional in keyless mode: TheSportsDB results + RSS news,
template captions, rendered graphics, dashboard. This is the guaranteed
floor — adding keys only upgrades data freshness, caption quality and
publishing autonomy.

## Kill switch

Set the repo variable `DRY_RUN=true` (instant, no code change), or
disable the three workflows under the Actions tab.

## Dashboard

`dashboard/index.html` is regenerated on every run. View it raw via
`https://htmlpreview.github.io/?https://github.com/<owner>/<repo>/blob/<branch>/dashboard/index.html`
or enable GitHub Pages (Settings → Pages → deploy from branch) and visit
`/dashboard/`.

## Direct Instagram Graph API (alternative to Buffer)

1. Convert the Instagram account to Business/Creator and link it to a
   Facebook Page.
2. Create a Meta app (developers.facebook.com) → add *Instagram Graph API*.
3. Generate a long-lived Page access token with
   `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`.
4. Get the IG user id: `GET /me/accounts` → page id → `GET /{page-id}?fields=instagram_business_account`.
5. Set `IG_USER_ID` (variable) + `IG_ACCESS_TOKEN` (secret), `PUBLISHER=instagram`.

Note: long-lived tokens expire after ~60 days — refresh them or stay on
Buffer, which manages the Instagram connection for you.

## Costs

| Component | Cost |
|---|---|
| GitHub Actions (public repo) | £0 |
| football-data.org free tier | £0 |
| TheSportsDB community key | £0 |
| RSS feeds | £0 |
| Pillow rendering + repo media hosting | £0 |
| Buffer free plan (1–3 channels) | £0 |
| Claude captions (optional) | ~£0.01–0.05/post, only if key set |

## Troubleshooting

- **Nothing publishing** → check dashboard "API log" + "Errors"; check
  `DRY_RUN` variable; check Buffer token validity.
- **Buffer free plan limit** — 10 scheduled posts per channel; the agent's
  `MAX_POSTS_PER_RUN`/`MIN_MINUTES_BETWEEN_POSTS` pacing keeps the queue
  under this, but a burst day may hit it (logged as LimitReachedError).
- **Workflow push conflicts** — runs serialize via the `tffw-state`
  concurrency group; a rare conflicting push is dropped safely (the next
  cycle regenerates anything lost; duplicate posts are prevented by
  content hashing).
- **Images 404 on Instagram/Buffer** — repo must be public and the media
  committed before publish (the workflows do this in-order).
