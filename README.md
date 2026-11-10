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

**There is no access control.** Anyone who can reach the server can create
a room, and anyone who knows (or guesses) a room's 6-character code can take a
seat in it and act on their turn. On your own WiFi that's the same trust
model as leaving a chip rack on the table — everyone in reach is someone you
invited. Don't expose this to the internet without putting real access
control in front of it; see [`DEPLOYMENT.md`](DEPLOYMENT.md).

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
removal gating, the stale-room cleanup sweep, and the rate limiters.

### Rate limiting

The app rate-limits itself (`backend/app/rate_limit.py`, instances in
`backend/app/limits.py`) in every deployment mode, independently of the
extra limits the public-deployment mode's nginx config adds on top:

| Scope | Limit | Why |
| --- | --- | --- |
| every `/api` route | 120/min per IP | flood backstop, applied router-wide so new endpoints are covered by default |
| `POST /api/rooms` | 5/10min per IP | one room per game night; bounds room-creation floods |
| `join` | 30/min per IP, +5 per failure | the room code is the only secret, so the failure penalty is what makes enumeration expensive |
| `rejoin` + WS handshake | 90/min per IP, +5 per failure | one shared budget, or an attacker alternates between the two oracles |
| WS connect | 30/10s per IP, 20 concurrent | a whole table reloading at once must still work |
| WS messages | 15/5s then 60/10s per seat | every message broadcasts to the whole room, so one socket can amplify N-fold |

Every per-IP number is sized for the *public* deployment, where the entire
table shares one NAT address and so counts as a single key — not for one
player per key. Resident rooms are capped by `MAX_ROOMS` (default 200). All
of these are overridable by environment variable; see
`backend/app/config.py`.

Per-IP limiting is defeated by a botnet at every layer. What actually
protects a game is the combination of the failed-lookup penalty, the short
room lifetime (`cleanup.py` sweeps empty rooms after 10 minutes) and the
~10^9 room-code space — not the rate limits alone.

## How a game works

1. One person creates a room (sets blinds + starting stack) and shares the
   6-character room code. Everyone else joins with that code and a name.
2. The dealer hits **Start Hand** once there are 2+ players. The app
   tracks the dealer button, blinds, and whose turn it is to act. "Dealer"
   is the host by default, or the current button holder when the room's
   `rotate_dealer` option is on.
3. The app never shows card values — it shows a status like "Dealing the
   Flop — 3 community cards" so the table stays in sync with whoever is
   physically dealing the real deck.
4. Check / call / fold are always one tap. Bet/raise offers pot-fraction
   presets and a slider, clamped to the legal min-raise/all-in range by the
   server.
5. If everyone folds but one player, they win automatically — no further
   input needed. If 2+ players reach showdown, the dealer marks who won
   each pot (main pot and any side pots are tracked separately, with
   correct eligible-winner sets for all-in situations). One designated
   arbiter rather than any player, the same way a real dealer pushes the
   chips — including when they folded their own hand.
6. A player who busts to 0 chips can rebuy between hands, self-declared,
   same as buying more chips from the rack in a real game.

The host (seat 1, whoever created the room) can edit blinds/stack before
the first hand, and remove a seat that's been disconnected for 5+ minutes
(only between hands). The host is also the default dealer, so unless
`rotate_dealer` is on they're the one who starts hands and declares
showdown winners. Acting on your own turn, rebuying and sitting out are
identical for every player.

Note that the host role is positional and permanent: it never transfers. If
seat 1 leaves a room with `rotate_dealer` off, nobody can start another
hand.

## Roadmap (explicitly out of scope for now)

Tournament mode / increasing blinds is not implemented. `RoomConfig` has a
`blind_schedule` field reserved for it.
