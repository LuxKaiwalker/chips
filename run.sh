#!/usr/bin/env bash
# Builds the frontend and serves everything from a single FastAPI process.
# Every phone at the table just needs to open http://<this-machine's-LAN-IP>:8000
set -euo pipefail
cd "$(dirname "$0")"

echo "Building frontend..."
(cd frontend && npm install --silent && npm run build --silent)

echo "Copying build into backend/app/static..."
rm -rf backend/app/static
cp -r frontend/dist backend/app/static

if [ ! -d backend/.venv ]; then
  echo "Creating backend virtualenv..."
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install --quiet -r backend/requirements.txt
fi

if [ -z "${CHIPS_PASSPHRASE:-}" ]; then
  echo "WARNING: CHIPS_PASSPHRASE is not set, using the default 'pokernight' passphrase."
  echo "Set it with: export CHIPS_PASSPHRASE=yourpassword"
fi

echo
echo "Starting server on port 8000..."
echo "Find your LAN IP with: ip addr show | grep 'inet ' (Linux) or ipconfig getifaddr en0 (Mac)"
echo "Players open: http://<your-lan-ip>:8000"
echo
cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
