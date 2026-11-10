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
#
# CHIPS_PORT (default 8000): override if something else on this machine
# already owns 8000 -- e.g. this repo's own DEPLOYMENT.md example reuses an
# existing nginx+Cloudflare Tunnel setup alongside another app, which needs
# its own port. Whatever you pick here must match the proxyPass/ingress
# target in your nginx/cloudflared config.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d backend/.venv ]; then
  echo "Creating backend virtualenv..."
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install --quiet -r backend/requirements.txt
fi

cd backend
# Proxy headers are set explicitly rather than relying on uvicorn's
# defaults: nginx is the only hop that may set them, and a uvicorn
# upgrade or a stray FORWARDED_ALLOW_IPS could otherwise move the
# trust boundary. Never use "*" here -- it makes the rate-limit key
# client-controlled. --ws-max-size caps frames nginx cannot (its
# client_max_body_size does not apply to WebSocket messages).
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${CHIPS_PORT:-8000}" \
  --workers 1 --log-level info \
  --proxy-headers --forwarded-allow-ips 127.0.0.1 --ws-max-size 65536
