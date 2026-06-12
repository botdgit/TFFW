#!/usr/bin/env bash
# Recurring worker for the TFFW agent when driven from a Claude session.
# Every cycle: sync repo -> run pipelines -> push state/media -> report how
# many queued posts are due (the session publishes them via the Buffer
# connector). Emits one line only when action/attention is needed.

set -u
BRANCH="claude/football-whistle-instagram-agent-au8zqt"
cd /home/user/TFFW || exit 1
i=0

while true; do
  i=$((i + 1))

  git fetch origin >/dev/null 2>&1 && git reset --hard "origin/$BRANCH" >/dev/null 2>&1

  python -m tffw.main live >/dev/null 2>&1 || echo "TFFW ERROR: live mode crashed (cycle $i)"
  python -m tffw.main news >/dev/null 2>&1 || echo "TFFW ERROR: news mode crashed (cycle $i)"

  # daily digest once per UTC day, in the 06:xx window
  if [ "$(date -u +%H)" = "06" ] && [ ! -f "/tmp/tffw_digest_$(date -u +%F)" ]; then
    python -m tffw.main digest >/dev/null 2>&1 && touch "/tmp/tffw_digest_$(date -u +%F)"
  fi

  git add data output dashboard >/dev/null 2>&1
  if ! git diff --cached --quiet; then
    git -c user.name="tffw-agent" -c user.email="tffw-agent@users.noreply.github.com" \
      commit -q -m "agent: session run $(date -u +%FT%TZ)"
    git push >/dev/null 2>&1 || {
      git fetch origin >/dev/null 2>&1 && git reset --hard "origin/$BRANCH" >/dev/null 2>&1
      echo "TFFW WARN: push conflict, state reset to origin (cycle $i)"
    }
  fi

  n=$(python scripts/session_publish_queue.py 2>/dev/null \
      | python -c "import json,sys; print(len(json.load(sys.stdin).get('due',[])))" 2>/dev/null || echo 0)
  if [ "${n:-0}" -gt 0 ]; then
    echo "TFFW: $n queued post(s) due — publish them via the Buffer connector now (run scripts/session_publish_queue.py for details)"
  fi

  # periodic heartbeat so health checks happen even when nothing is due
  if [ $((i % 180)) -eq 1 ]; then
    echo "TFFW heartbeat: cycle $i — check GitHub Actions runs for agent-live/news/digest are green"
  fi

  sleep 120
done
