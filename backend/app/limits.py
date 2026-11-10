"""The app's rate limiter instances, in one place.

Why a separate module rather than module-level globals in each router: the
`lookup` limiter has to be *shared* between rest_router (POST
/rooms/{code}/rejoin) and ws_router (the WebSocket handshake). Both are
room-code enumeration oracles, so if each kept its own limiter an attacker
would simply split their probe budget across the two and double their rate.

Sizing note that applies to every per-IP limiter below: in the public
deployment the whole table is behind one NAT/CGNAT address, so
CF-Connecting-IP collapses all 10+ players into a single key. These numbers
are sized for 10-15 players plus reload churn sharing one key, not for one
player per key. In LAN mode each phone has its own IP, so the same numbers
are simply very generous.
"""

from app.config import settings
from app.rate_limit import KeyedLimiter

# Backstop across every /api route, wired as a router-level dependency so a
# newly added endpoint is covered by default rather than by remembering. A
# 10-phone table's full boot is ~30-40 API calls; static assets are served by
# the StaticFiles mount and never reach this.
rest_global = KeyedLimiter(settings.rl_rest_global_max, 60, name="rest_global")

# A host creates one room per game night; 5 per 10 minutes covers retries and
# makes room-creation flooding from one IP impossible without tracking room
# ownership per IP.
create_room = KeyedLimiter(settings.rl_create_max, 600, name="create_room")

# 30/min lets an entire NAT'd table join inside a minute. With the +5 failure
# penalty a wrong code costs 6 slots, so ~5 probes/min/IP -- about 139 days to
# walk the 10^6 room-code space.
join = KeyedLimiter(settings.rl_join_max, 60, name="join")

# Shared by REST /rejoin and the WS handshake. The frontend calls rejoinRoom
# twice per room entry (App.tsx boot + onEnterRoom) and once per reconnect, so
# 10 phones booting against a dead room already costs 60. With the penalty,
# ~15 probes/min/IP -- about 46 days to walk the code space.
lookup = KeyedLimiter(settings.rl_lookup_max, 60, name="lookup")

# Unchanged from the original: tolerates a whole table reloading at once.
# Concurrent socket count is capped separately by
# settings.max_ws_connections_per_ip.
ws_connect = KeyedLimiter(settings.rl_ws_connect_max, 10, name="ws_connect")

# In-game message limits, keyed "room:seat" rather than per connection.
# ConnectionManager keys its socket table by seat_id, so N sockets sharing one
# player_token collapse to a single entry -- broadcast fan-out is bounded by
# distinct seats, not sockets. A per-connection limiter would let one token
# multiply its budget by opening 20 sockets, which is exactly the abuse case.
# 15/5s is ~3 messages/second sustained with a 15-message burst; human poker
# tempo is well under 1/s and the 25s heartbeat is noise at this scale.
ws_message = KeyedLimiter(settings.rl_ws_message_max, 5, name="ws_message")
# Ceiling for a client that ignores the soft limit's dropped-message errors.
ws_message_hard = KeyedLimiter(settings.rl_ws_message_hard_max, 10, name="ws_message_hard")


def message_key(room_code: str, seat_id: int) -> str:
    return f"{room_code}:{seat_id}"
