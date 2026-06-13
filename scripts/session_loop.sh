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

  # only sync when the tree is clean — never clobber in-progress edits made
  # by an interactive session sharing this worktree
  if [ -z "$(git status --porcelain)" ]; then
    git fetch origin >/dev/null 2>&1 && git reset --hard "origin/$BRANCH" >/dev/null 2>&1
  fi

  python -m tffw.main live >/dev/null 2>&1 || echo "TFFW ERROR: live mode crashed (cycle $i)"
  # during a live match, skip news on most cycles to keep latency minimal
  if [ ! -f data/LIVE_MATCH ] || [ $((i % 5)) -eq 0 ]; then
    python -m tffw.main news >/dev/null 2>&1 || echo "TFFW ERROR: news mode crashed (cycle $i)"
  fi

  # daily digest once per UTC day, in the 06:xx window
  if [ "$(date -u +%H)" = "06" ] && [ ! -f "/tmp/tffw_digest_$(date -u +%F)" ]; then
    python -m tffw.main digest >/dev/null 2>&1 && touch "/tmp/tffw_digest_$(date -u +%F)"
  fi

  git add data output dashboard >/dev/null 2>&1
  if ! git diff --cached --quiet; then
    git -c user.name="Claude" -c user.email="noreply@anthropic.com" \
      commit -q -m "agent: session run $(date -u +%FT%TZ)"
    git push >/dev/null 2>&1 || {
      git fetch origin >/dev/null 2>&1 && git reset --hard "origin/$BRANCH" >/dev/null 2>&1
      echo "TFFW WARN: push conflict, state reset to origin (cycle $i)"
    }
  fi

  # publish autonomously via the Buffer token (.env); media is already pushed
  python -m tffw.main publish >/dev/null 2>&1 || echo "TFFW ERROR: publish crashed (cycle $i)"
  git add data output dashboard >/dev/null 2>&1
  if ! git diff --cached --quiet; then
    git -c user.name="Claude" -c user.email="noreply@anthropic.com" \
      commit -q -m "agent: session publish $(date -u +%FT%TZ)"
    git push >/dev/null 2>&1 || { git fetch origin >/dev/null 2>&1 && git reset --hard "origin/$BRANCH" >/dev/null 2>&1; }
  fi

  # weekly fixtures carousel: regenerate every Friday (once)
  if [ "$(date -u +%u)" = "5" ] && [ ! -f "/tmp/tffw_carousel_$(date -u +%F)" ]; then
    if python scripts/wc_week_carousel.py >/dev/null 2>&1; then
      touch "/tmp/tffw_carousel_$(date -u +%F)"
      echo "TFFW: weekly World Cup fixtures carousel regenerated — publish it via the Buffer connector (slides wc_week_0..N in output/media, push first)"
    fi
  fi

  # periodic heartbeat (wall-clock gated, not cycle-gated, so re-arming the
  # loop does not re-trigger it). Emit at most once every ~6h.
  hb=/tmp/tffw_heartbeat
  now=$(date -u +%s)
  last=$(cat "$hb" 2>/dev/null || echo 0)
  if [ $((now - last)) -ge 21600 ]; then
    echo "$now" > "$hb"
    echo "TFFW heartbeat — check GitHub Actions runs for agent-live/news/digest are green"
  fi

  # fast mode while a match is live: 20s polling instead of 2 minutes
  if [ -f data/LIVE_MATCH ]; then
    sleep 20
  else
    sleep 120
  fi
done
