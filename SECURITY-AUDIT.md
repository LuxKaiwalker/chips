# Security audit — Chips

Date: 2026-11-10. Reviewed at commit `a06050e` (the branch that removes the
passphrase gate), covering `backend/`, `frontend/`, `deploy/`, `scripts/`,
`.github/workflows/` and both deployment modes.

Method: manual review of every request path and authorization check, plus
`pip-audit` against the pinned `requirements.txt` and `npm audit` against
`package-lock.json`. Every finding below was reproduced locally before being
written down; the fixed ones have regression tests named inline.

**Dependency scan: clean.** `pip-audit`: no known vulnerabilities across the
28 pinned backend packages. `npm audit` (with and without dev
dependencies): 0 vulnerabilities.

| ID | Severity | Finding | Status |
| --- | --- | --- | --- |
| C1 | Critical | `NaN`/non-integer bet amount bypasses bounds and bricks the room | **Fixed** |
| H1 | High | Player tokens written to the production log in cleartext | **Fixed** |
| H2 | High | Room-code enumeration oracle | **Fixed** |
| H3 | High | Unauthenticated uncapped room creation; unbounded limiter state; unlimited WS messages | **Fixed** |
| H4 | High | No access control at all | **Accepted risk** (deliberate) |
| M1 | Medium | Unvalidated room config mints chips | **Fixed** |
| M2 | Medium | Raw dict bodies produce unhandled 500s | **Fixed** |
| M3 | Medium | `AttributeError` escapes the WS handler and kills the connection | **Fixed** |
| M4 | Medium | Oversized WS frames force a 16 MiB JSON parse | **Fixed** |
| M5 | Medium | Spectators can advance the street | Open |
| M6 | Medium | Self-service rebuy is uncapped | Open |
| M7 | Medium | No security headers | Open |
| M8 | Medium | Raw exception text echoed to clients | Open |
| L1–L8 | Low | See below | Open |

---

## Critical

### C1. A `NaN` bet amount bypassed all bounds validation and permanently broke the room — *fixed*

`ws_router` passed `msg.get("amount")` into the engine with no coercion
(unlike `rebuy`, which did `int(...)`). Starlette's `receive_json` uses plain
`json.loads`, which accepts the JSON literals `NaN`, `Infinity` and
`-Infinity`. The bound check in `state_machine.apply_action` is two
comparisons:

```python
to_amount = min(amount, max_to)      # min(nan, 100) -> nan
if to_amount < min_to:               # nan < 10      -> False
    raise EngineError("INVALID_AMOUNT", ...)
```

so a `NaN` passed validation untouched. It then flowed into `player.stack`,
`contrib_street`, `contrib_hand` and every pot sum (`engine/pots.py`), and
the resulting broadcast serialized as bare `NaN` — which `JSON.parse`
rejects. The exception was thrown from an unguarded `ws.onmessage` handler,
so **one message from one seated player permanently broke every connected
client in the room**, with no recovery path because the state lives only in
memory.

Reproduced: `json.loads('{"amount": NaN}')` succeeds, `min(nan, 100)` is
`nan`, `nan < 10` is `False`, `json.dumps` emits bare `NaN`.

Fixed by `_coerce_chip_amount` in `backend/app/engine/state_machine.py`,
which rejects `bool`, non-numerics, `NaN`/`Infinity` and fractional values
(integral floats like `10.0` are narrowed rather than refused), applied to
both `apply_action` and `rebuy`; plus a `try/catch` around `JSON.parse` in
`frontend/src/api/ws.ts` so no malformed frame can take a client down again.
Verified end-to-end in a live two-player hand: `NaN`, `Infinity`, `10.5` and
`true` all return `INVALID_AMOUNT`, a legitimate raise still works, and the
broadcast state round-trips through `json.dumps(..., allow_nan=False)`.
Tests: `backend/tests/test_input_validation.py`.

## High

### H1. Player tokens were written to the production log in cleartext — *fixed*

The frontend put credentials in the WebSocket URL query string, and uvicorn
logs the full request path *including* the query string on every connect,
rejection and close (`websockets_sansio_impl.py` via
`get_path_with_query_string`), with `scripts/run-prod.sh` running at
`--log-level info`. Every player token therefore landed in journald. A
`player_token` is the complete credential for a seat, never expires, and has
no server-side revocation, so anyone able to read the journal could take over
any seat in any room.

Fixed by moving the token out of the URL into a mandatory first WebSocket
message (`{"type":"auth","player_token":"…"}`). The socket is accepted, then
authenticated; a missing, malformed or late frame closes 4401 and an
unrecognized token closes 4404. The unauthenticated window is bounded by a
10-second timeout, and such a socket still occupies a per-IP connection slot
so it cannot be used to idle the budget away.

Verified against a real uvicorn subprocess at `--log-level info`: the
WebSocket lines are still logged, and now read `"WebSocket /ws/771669"
[accepted]` with no token and no query string at all.

### H2. Room-code enumeration oracle — *fixed*

With the passphrase gone, the 6-character room code is the only secret. Two
cheap oracles existed:

- `join` returned 404 for `ROOM_NOT_FOUND` but 400 for `ROOM_FULL` /
  `NAME_TAKEN`, so a live code was distinguishable, and a successful probe
  *seated the attacker*, letting one actor consume all 10 seats and lock the
  real table out.
- `rejoin` was cheaper still: it needs no display name and distinguished a
  missing room from a wrong token, making it one request per code with no
  side effects. The WebSocket handshake had the same shape.

Fixed by collapsing `rejoin_room` to report `PLAYER_NOT_FOUND` for a missing
room as well as a wrong token; validating the code's shape before the dict
lookup so malformed input isn't a cheaper probe; and charging a failed lookup
`FAILED_LOOKUP_PENALTY` (5) extra slots against a limiter shared between the
REST and WebSocket paths — otherwise an attacker alternates between the two
and halves their cost.

Measured on a live server: a flood of joins against a nonexistent code gets
**five** probes before `429`, i.e. ~5/min/IP. Against the ~10^9 (32^6)
code space that is centuries per IP to walk; even against the old 10^6
space it was ~139 days. Tests: `test_rate_limit.py`, `test_ws_limits.py`.

### H3. Uncapped room creation, unbounded limiter state, unlimited WS messages — *fixed*

All rate-limiting gaps; see the "Harden API rate limiting" commit and the
rate-limiting table in `README.md`. In brief: room creation had no ceiling
and is now unauthenticated (`MAX_ROOMS`, default 200, returning 503 +
`Retry-After`); limiter keys were never reclaimed, which an IPv6 /64 turns
into unbounded memory growth (eviction sweep + hard `max_keys` cap with LRU
eviction); and in-game WebSocket messages were deliberately unlimited even
though each one broadcasts to every socket in the room, giving one socket
N-fold outbound amplification (two-tier limiter keyed `room:seat`).

Measured: room creation allows 5 then returns `429` with `Retry-After: 600`.

### H4. The app has no access control — *accepted risk, by decision*

This is the deliberate outcome of removing the passphrase gate, not a defect
awaiting a fix. Stated plainly so it is not mistaken for an oversight:

- Anyone who can reach the URL can create rooms.
- Anyone who learns or guesses a room's 6-character code can take a seat, act on
  its turns, rebuy arbitrary chips, and — if they take seat 1 — hold host
  powers.
- There is no credential to get wrong, no audit trail, and no way to evict a
  connected player (`remove_stale_seat` requires the target to have been
  disconnected 5+ minutes).

What actually protects a game is the ~10^9 code space, the 10-minute sweep of
empty rooms, and the layered rate limiting with its failed-lookup penalty.
**None of that helps against a botnet**, which defeats per-IP limiting at
every layer. For a LAN game night this is a reasonable trust model — the same
one as leaving a chip rack on the table. For the public deployment it means
the game is open to anyone who finds it; if that isn't wanted, real access
control belongs at the nginx layer (Cloudflare Access, mTLS, `auth_request`),
as `DEPLOYMENT.md` now says.

One thing the removal *improved*: it deleted the committed default passphrase
`"pokernight"`, which was the app's single shared credential and was reachable
in LAN mode whenever `CHIPS_PASSPHRASE` was unset.

## Medium

### M1. Unvalidated room config minted chips — *fixed*

`small_blind`, `big_blind` and `starting_stack` were accepted unbounded,
including negative. `_post_blind` does `actual = min(amount, player.stack);
player.stack -= actual`, so a **negative blind increased** the poster's
stack. A non-positive big blind also seeds `last_full_raise_increment`,
corrupting every min-raise computation for the rest of the hand, and
`raise_presets` was an arbitrary list echoed to every client and multiplied
into bet sizes client-side, so one bad entry broke everyone's action panel.

Fixed by `_validate_config` in `backend/app/rooms.py`, applied on both the
REST create path and the WebSocket `update_room_config` path: positive
whole numbers with a sane ceiling, `big_blind >= small_blind`,
`starting_stack >= big_blind`, and 1–8 numeric presets in `(0, 10]`.
Tests: `test_input_validation.py`.

### M2. Raw dict bodies produced unhandled 500s — *fixed*

No pydantic models anywhere despite the dependency being installed. A missing
`display_name` was a `KeyError`, a non-string one an `AttributeError` on
`.strip()`, and a non-numeric blind a `ValueError` — all unhandled, so a
client mistake became an HTTP 500 with a traceback in the log. A non-ASCII
`player_token` was worse: `secrets.compare_digest` raises `TypeError` on
non-ASCII `str`, so it 500'd instead of returning not-found.

Fixed with typed request models (`CreateRoomBody`, `JoinRoomBody`,
`RejoinRoomBody`) so the same input is a 422, and by comparing tokens as
bytes. The engine-level checks in `rooms.py` remain authoritative, since the
WebSocket path has no pydantic in front of it.

### M3. `AttributeError` escaped the WS handler — *fixed*

`_handle_message` caught `(KeyError, ValueError, TypeError)` but not
`AttributeError`, so e.g. `declare_winners` with a dict `assignments` escaped
the handler and tore down the sender's connection. Added to the catch list.
Test: `test_ws_limits.py::test_unknown_message_type_is_an_error_not_a_disconnect`.

### M4. Oversized WS frames forced a 16 MiB JSON parse — *fixed*

uvicorn's `ws_max_size` defaults to `16 * 1024 * 1024` and nginx's
`client_max_body_size 1m` does **not** apply to WebSocket frames, so a single
message could force a 16 MiB parse and allocation — a cheap CPU DoS that no
count-based limiter catches. Capped at both levels: `--ws-max-size 65536` on
both entry points, plus `WS_MAX_MESSAGE_BYTES` (8192) checked on the raw text
before parsing. The same restructure fixed an unhandled `JSONDecodeError`
that let a non-JSON text frame tear the connection down.

### M5. Spectators can advance the street — *open*

`advance_runout` only excludes `FOLDED`, so a `SITTING_OUT` or `BUSTED` seat
can advance the street for everyone. Notably weaker than its siblings:
`declare_winners` was deliberately tightened to a single arbiter.
Suggested fix: require the seat to be in `hand.dealt_in_seats`.

### M6. Self-service rebuy is uncapped — *open*

`rebuy` accepts any positive amount for a busted player, so anyone at the
table can mint an arbitrary stack. The README calls this trust-based by
design, which is defensible at a real table but less so now that the table is
open to anyone with the code. Suggested fix: cap at some multiple of
`starting_stack`.

### M7. No security headers — *open*

Nothing sets `Content-Security-Policy`, `Strict-Transport-Security`,
`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` or
`Permissions-Policy`. The SPA is freely framable, and with the player token in
`localStorage` any future XSS is full token theft. Cheap to add in
`deploy/nginx-chips.conf` and `deploy/chips.nix`; left out of this change only
because it is untestable without a live nginx (which isn't installed here, so
`nginx -t` has not been run against the modified config either).

### M8. Raw exception text echoed to clients — *open*

`_handle_message` sends `str(e)` to the client as `BAD_REQUEST`, which can
surface Python internals. Low impact given there is nothing secret in the
process, but it is free to replace with a fixed string.

## Low / informational — all open

- **L1.** `DEPLOYMENT.md` commits the real Cloudflare tunnel UUID
  (`815ad8c7-…`) in a tracked file, twice. Not a credential — the JSON
  credentials file is — but it fingerprints the host and a sibling
  deployment, and the rest of `deploy/` is carefully templated with
  placeholders. Replace with `<TUNNEL_ID>` for consistency.
- **L2.** `.github/workflows/pages.yml` pins actions to mutable major tags
  (`actions/checkout@v4`) rather than commit SHAs.
- **L3.** No `Origin` check on the WebSocket endpoint. CORS does not apply to
  WebSockets, so any page can open one; exploitation needs a valid
  `player_token`, which lives in `localStorage` and is not cross-origin
  readable, so impact is limited.
- **L4.** `pytest` and `httpx` are installed into the production venv by
  `scripts/run-prod.sh`.
- **L5.** Player tokens are never revocable; "Leave room" only clears
  `localStorage`, so a leaked token retains seat control until the room is
  swept.
- **L6.** Host identity is positional and permanent (`host_seat_id = 1`,
  never transferred). If seat 1 leaves with `rotate_dealer` off, nobody can
  start another hand. Now documented in the README.
- **L7.** LAN mode serves plain HTTP on `0.0.0.0` with no TLS, so tokens
  cross the WiFi in cleartext.
- **L8.** No dependency-audit step in CI and no hash pinning
  (`--require-hashes`). Both audits are clean today, but nothing keeps them
  that way.

## Reviewed and clean

No SQL, no ORM, no `eval`/`exec`/`pickle`/`os.system`, no `shell=True`, no
templating engine, no `dangerouslySetInnerHTML`. The only `subprocess` use is
a static argv list in `tests/test_ws_close_codes.py`.

All randomness uses `secrets`: room codes via `secrets.choice`, player tokens
via `secrets.token_urlsafe(16)` (128 bits). Token comparison is constant-time.
`player_token` is `repr=False` on the dataclass and correctly omitted from the
broadcast serializer.

Authorization is sound in shape: the WebSocket resolves `seat_id` from the
authenticated token and passes that server-derived value into every handler,
so a client cannot spoof which seat it acts as. Each action is then checked —
own-turn-only for `player_action`, dealer-only for `start_hand` and
`declare_winners`, host-only for `update_config` and `remove_stale_seat`,
self-only for `rebuy` and `toggle_sit_out`, and pot-eligibility for winner
assignments. Bet bounds are computed server-side and clamped.

Player names are length-limited and rendered as JSX text, so React escapes
them — no XSS. (Names are interpolated into the broadcast action log, so a
name like `"Bob folds"` can spoof a log line; cosmetic.)

Deployment posture is good: the backend binds loopback only, nginx listens on
loopback only, and cloudflared makes an outbound connection, so there is no
public listening socket on the host. `deploy/local/` holds the real
hostnames and is gitignored; no secrets are committed anywhere, and the Pages
workflow references a repository *variable*, not a secret, with scoped
permissions.
