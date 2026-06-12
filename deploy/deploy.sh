#!/usr/bin/env bash
# Safe deploy for the ReDrive Droplet.
#
# Pulls main and restarts the service ONLY when server-side Python changed.
# Static assets (JS/CSS/HTML/manuals) are served from disk, so a pull alone
# makes them live — and skipping the restart means active sessions survive.
#
# Usage (on the Droplet):  bash /opt/redrive/deploy/deploy.sh

set -e
cd /opt/redrive

BEFORE=$(git rev-parse HEAD)
git pull origin main
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" = "$AFTER" ]; then
    echo "Already on $(git log --oneline -1) — nothing pulled."
    echo "(If you expected new code, it may have been pulled on a previous run.)"
    exit 0
fi

echo "Updated: $BEFORE -> $(git log --oneline -1)"

if git diff --name-only "$BEFORE" "$AFTER" | grep -qE '\.py$'; then
    # Python changed — a restart is required, but it kills every active room.
    ROOMS=$(curl -s --max-time 2 http://localhost:8765/api/rooms \
            | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))' \
            2>/dev/null || echo "unknown")
    echo
    echo "Server code changed — restart required to take effect."
    echo "Active public rooms right now: $ROOMS"
    echo "RESTARTING WILL DROP EVERY ACTIVE SESSION."
    read -r -p "Restart redrive now? [y/N] " ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
        systemctl restart redrive
        echo "Restarted. $(systemctl is-active redrive)."
    else
        echo "Skipped. New server code is on disk but NOT running."
        echo "Restart later with:  systemctl restart redrive"
    fi
else
    echo "Static/JS-only change — already live. No restart needed; sessions untouched."
fi
