# Chips

A digital replacement for poker chips — not for cards, not for dealing, not
for poker itself. Play Texas Hold'em in person with a real deck of cards;
everyone's phone (on the same WiFi as the host's computer) runs this app to
track stacks, bets, pots and side pots, exactly like a rack of chips would.

The app never knows a single card's value. It only tracks what you need to
track with chips: who owes what, whose turn it is, how big the pot(s) are,
and — because it can't see hands — it leans on the table to declare who won
at showdown, the same way real players push chips across felt.

## Quick start (game night)

```
./run.sh
```

This builds the frontend, creates a Python virtualenv on first run, and
starts a single server on port 8000. Find your machine's LAN IP address
(`ip addr show` on Linux, `ipconfig getifaddr en0` on a Mac) and have every
player open `http://<that-ip>:8000` in their phone's browser. Everyone needs
to be on the same WiFi network as the host machine.

Set a real passphrase before playing for real (anyone who doesn't know it
can't create or join a room):

```
export CHIPS_PASSPHRASE=yourpassword
./run.sh
```

If you don't set one, the app falls back to `pokernight` and prints a loud
warning on startup.

**Important limitation**: everything lives in memory. If the server process
restarts (crash, `Ctrl-C`, machine reboot), every room and every stack is
gone. This is a deliberate simplicity trade-off for a local party app, not
something to work around — just don't restart the server mid-game.

## Public deployment (optional)

The quick start above is everything you need for a normal game night. If
you specifically want the app reachable by a stable public URL instead of
a LAN IP (useful when a guest WiFi's client isolation blocks phones from
reaching each other directly), see [`DEPLOYMENT.md`](DEPLOYMENT.md) for the
nginx + Cloudflare Tunnel + GitHub Pages setup. Players are still expected
to be physically at the table with a real deck either way.

## Development

Two terminals, with hot reload on both sides:

```
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

```
cd frontend
npm install
npm run dev
```

Vite (on :5173) proxies `/api` and `/ws` through to the backend on :8000, so
open `http://localhost:5173` while developing.

### Running the backend tests

```
cd backend
.venv/bin/python -m pytest
```

Covers button/blind rotation (including heads-up rules), legal-action and
min-raise validation (including the short-all-in-doesn't-reopen-betting
rule), the main/side-pot split algorithm, fold-out auto-award, split-pot
odd-chip distribution, room creation/join/rejoin, host-only config/seat-
removal gating, the stale-room cleanup sweep, and the rate limiter.

The app also rate-limits itself (`backend/app/rate_limit.py`) regardless
of deployment mode: the passphrase endpoint specifically (the one
brute-forceable secret in this app), plus a coarser general limit on room
create/join/rejoin and new WebSocket connection attempts against simple
request-flood abuse. This is independent of the extra, tighter rate
limiting the public-deployment mode's nginx config adds on top — see
[`DEPLOYMENT.md`](DEPLOYMENT.md).

## How a game works

1. One person creates a room (sets blinds + starting stack) and shares the
   6-digit room code. Everyone else joins with that code and a name.
2. Any player can hit **Start Hand** once there are 2+ players. The app
   tracks the dealer button, blinds, and whose turn it is to act.
3. The app never shows card values — it shows a status like "Dealing the
   Flop — 3 community cards" so the table stays in sync with whoever is
   physically dealing the real deck.
4. Check / call / fold are always one tap. Bet/raise offers pot-fraction
   presets and a slider, clamped to the legal min-raise/all-in range by the
   server.
5. If everyone folds but one player, they win automatically — no further
   input needed. If 2+ players reach showdown, anyone still in the hand can
   mark who won each pot (main pot and any side pots are tracked
   separately, with correct eligible-winner sets for all-in situations).
6. A player who busts to 0 chips can rebuy between hands, self-declared,
   same as buying more chips from the rack in a real game.

The host only has two narrow powers: editing blinds/stack before the first
hand, and removing a seat that's been disconnected for 5+ minutes (and only
between hands). Everything else — starting hands, acting, declaring
winners — is identical for every player, including the host.

## Roadmap (explicitly out of scope for now)

Tournament mode / increasing blinds is not implemented. `RoomConfig` has a
`blind_schedule` field reserved for it.
