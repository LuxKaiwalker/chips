#!/usr/bin/env bash
# Runs the backend for the public-deployment mode -- see DEPLOYMENT.md.
#
# Differs from run.sh in exactly two ways, both deliberate:
#   - binds 127.0.0.1 only, never 0.0.0.0: this process is never meant to
#     have a direct public-facing socket. nginx + Cloudflare Tunnel are
#     what's actually reachable from the internet (see DEPLOYMENT.md) --
#     this script assumes that's already set up and running.
#   - no --reload, single worker: game state (rooms, hands, pots) lives in
#     this process's memory (see README.md's "in-memory only" limitation).
#     --reload's file-watcher would restart the process -- and wipe every
#     room -- on an incidental file change; more than one worker would
#     split rooms across processes that don't share state at all.
#
# In this mode the frontend is published separately to GitHub Pages, not
# served by this process -- any backend/app/static left over from a LAN-mode
# build is simply unused here. For the plain LAN mode where this process
# serves everything itself from one origin, use ../run.sh instead.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${CHIPS_PASSPHRASE:-}" ]; then
  echo "ERROR: CHIPS_PASSPHRASE must be set before running in public-deployment mode." >&2
  echo "The default passphrase is not acceptable once this is reachable from the internet." >&2
  exit 1
fi

if [ ! -d backend/.venv ]; then
  echo "Creating backend virtualenv..."
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install --quiet -r backend/requirements.txt
fi

cd backend
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --log-level info
