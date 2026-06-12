"""Static admin dashboard generator.

Renders dashboard/index.html from the SQLite state after every run; the
Actions workflow commits it, so the latest dashboard is always viewable at
the repo (or via GitHub Pages — see docs/DEPLOYMENT.md).
"""

import html
import json

from . import config, db
from .logger import get_logger

log = get_logger("dashboard")

CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#F2F7F3;color:#1a1a1a}
header{background:linear-gradient(135deg,#064C24,#0B7A3B);color:#fff;padding:28px 40px}
header h1{margin:0;font-size:26px} header p{margin:6px 0 0;opacity:.85}
main{padding:24px 40px;max-width:1280px;margin:auto}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:28px}
.card{background:#fff;border-radius:12px;padding:18px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.card b{display:block;font-size:30px;color:#064C24}.card span{color:#5a6b5f;font-size:13px}
h2{color:#064C24;margin:30px 0 10px;font-size:18px}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08);font-size:13px}
th{background:#064C24;color:#fff;text-align:left;padding:9px 12px}
td{padding:8px 12px;border-top:1px solid #e7efe9;vertical-align:top}
tr:nth-child(even) td{background:#f7fbf8}
.tag{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11px;font-weight:700;color:#fff}
.published{background:#0B7A3B}.queued{background:#C98A00}.dry_run{background:#5A6B5F}
.failed{background:#B02E2E}.skipped{background:#888}.skipped_low_confidence{background:#888}.posted{background:#0B7A3B}
.ok{color:#0B7A3B;font-weight:700}.err{color:#B02E2E;font-weight:700}
footer{text-align:center;color:#5a6b5f;padding:24px;font-size:12px}
"""


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _tag(status: str) -> str:
    return f'<span class="tag {_esc(status)}">{_esc(status)}</span>'


def _sources(raw) -> str:
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
        return ", ".join(s.get("domain", "?") for s in items)
    except Exception:
        return ""


def build() -> None:
    d = db.dashboard_data()
    c = d["counts"]

    cards = "".join(
        f'<div class="card"><b>{c[k]}</b><span>{label}</span></div>'
        for k, label in [
            ("queued", "in queue"), ("published", "published"),
            ("dry_run", "dry-run posts"), ("claims_low_conf", "held: low confidence"),
            ("failed", "failed"), ("errors_24h", "errors (24h)"),
        ]
    )

    queue_rows = "".join(
        f"<tr><td>#{r['id']}</td><td>{_esc(r['format'])}</td><td>{_esc(r['headline'])}</td>"
        f"<td>{r['confidence']:.2f}</td><td>{_esc(r['scheduled_for'])}</td></tr>"
        for r in d["queue"]
    ) or '<tr><td colspan="5">Queue is empty</td></tr>'

    post_rows = "".join(
        f"<tr><td>#{r['id']}</td><td>{_esc(r['format'])}</td><td>{_esc(r['headline'])}</td>"
        f"<td>{_tag(r['status'])}</td><td>{r['confidence']:.2f}</td>"
        f"<td>{_sources(r['sources'])}</td><td>{_esc(r['published_at'])}</td></tr>"
        for r in d["recent_posts"]
    ) or '<tr><td colspan="7">No posts yet</td></tr>'

    claim_rows = "".join(
        f"<tr><td>{_esc(r['headline'])}</td><td>{r['confidence']:.2f}</td>"
        f"<td>{_tag(r['status'])}</td><td>{_sources(r['sources'])}</td>"
        f"<td>{_esc(r['first_seen'])}</td></tr>"
        for r in d["recent_claims"]
    ) or '<tr><td colspan="5">No claims tracked yet</td></tr>'

    api_rows = "".join(
        f"<tr><td>{_esc(r['ts'])}</td><td>{_esc(r['service'])}</td>"
        f"<td>{_esc(r['endpoint'])[:90]}</td><td>{_esc(r['status'])}</td>"
        f"<td class=\"{'ok' if r['ok'] else 'err'}\">{'OK' if r['ok'] else 'FAIL'}</td></tr>"
        for r in d["api_log"]
    ) or '<tr><td colspan="5">No API calls logged yet</td></tr>'

    error_rows = "".join(
        f"<tr><td>{_esc(r['ts'])}</td><td>{_esc(r['context'])}</td><td>{_esc(r['message'])}</td></tr>"
        for r in d["errors"]
    ) or '<tr><td colspan="3">No errors 🎉</td></tr>'

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{config.BRAND_NAME} — Agent Dashboard</title><style>{CSS}</style></head><body>
<header><h1>⚽ {config.BRAND_NAME} — Agent Dashboard</h1>
<p>Generated {d['generated_at']} UTC · mode: {"DRY RUN" if config.DRY_RUN else f"LIVE via {config.PUBLISHER}"} · min confidence {config.MIN_CONFIDENCE}</p></header>
<main>
<div class="cards">{cards}</div>
<h2>Live queue</h2><table><tr><th>ID</th><th>Format</th><th>Headline</th><th>Conf</th><th>Scheduled (UTC)</th></tr>{queue_rows}</table>
<h2>Recent posts</h2><table><tr><th>ID</th><th>Format</th><th>Headline</th><th>Status</th><th>Conf</th><th>Sources</th><th>Published</th></tr>{post_rows}</table>
<h2>Claims &amp; verification</h2><table><tr><th>Headline</th><th>Conf</th><th>Status</th><th>Sources</th><th>First seen</th></tr>{claim_rows}</table>
<h2>API log</h2><table><tr><th>Time</th><th>Service</th><th>Endpoint</th><th>HTTP</th><th>Result</th></tr>{api_rows}</table>
<h2>Errors</h2><table><tr><th>Time</th><th>Context</th><th>Message</th></tr>{error_rows}</table>
</main><footer>The Football Final Whistle agent · state stored in data/tffw.sqlite3</footer>
</body></html>"""

    out = config.DASHBOARD_DIR / "index.html"
    out.write_text(page, encoding="utf-8")
    log.info("dashboard written -> %s", out)
