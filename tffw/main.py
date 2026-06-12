"""CLI entrypoint.

    python -m tffw.main live       # match monitoring
    python -m tffw.main news       # RSS ingestion + verification
    python -m tffw.main digest     # daily table/fixtures content
    python -m tffw.main publish    # flush due queue items
    python -m tffw.main dashboard  # rebuild dashboard/index.html
    python -m tffw.main all        # live + news + publish + dashboard

Every mode is wrapped so a failure is logged to the errors table and the
process still exits 0 — one bad API response must never kill the cron run.
"""

import argparse
import sys
import traceback

from . import config, db, dashboard, pipeline
from .logger import get_logger

log = get_logger("main")

MODES = {
    "live": pipeline.run_live,
    "news": pipeline.run_news,
    "digest": pipeline.run_digest,
    "publish": pipeline.run_publish,
    "dashboard": dashboard.build,
}


def _safe(name: str) -> None:
    try:
        MODES[name]()
    except Exception:
        tb = traceback.format_exc()
        log.error("mode %s crashed:\n%s", name, tb)
        try:
            db.log_error(f"mode:{name}", tb)
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(prog="tffw")
    parser.add_argument("mode", choices=[*MODES, "all"])
    args = parser.parse_args()

    db.init_db()
    log.info(
        "TFFW agent — mode=%s dry_run=%s publisher=%s competitions=%s",
        args.mode, config.DRY_RUN, config.PUBLISHER, ",".join(config.COMPETITIONS),
    )

    if args.mode == "all":
        for name in ("live", "news", "publish", "dashboard"):
            _safe(name)
    else:
        _safe(args.mode)
        if args.mode != "dashboard":
            _safe("dashboard")
    return 0


if __name__ == "__main__":
    sys.exit(main())
