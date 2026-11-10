import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import limits
from app.config import settings
from app.engine import EngineError
from app.engine.state_machine import (
    advance_runout,
    apply_action,
    declare_winners,
    rebuy,
    start_new_hand,
    toggle_sit_out,
)
from app.models import PlayerStatus, current_dealer_seat
from app.rate_limit import client_ip
from app.rooms import room_manager
from app.ws_manager import connection_manager

router = APIRouter()

# Concurrent open sockets per IP. Separate from the connect *rate* limit: a
# rate limit alone lets an attacker hold sockets open indefinitely by opening
# them slowly. Entries are deleted at zero so this can't become a second
# unbounded IP-keyed dict.
_ws_conns_by_ip: dict[str, int] = {}

# How long an accepted-but-unauthenticated socket may sit before being
# dropped. It already occupies a slot in _ws_conns_by_ip, so letting it idle
# forever would be a cheap way to exhaust the per-IP connection budget.
_AUTH_TIMEOUT_SECONDS = 10


class _AuthFrameError(Exception):
    """No usable auth frame arrived (missing, malformed, oversized, late)."""


@router.websocket("/ws/{room_code}")
async def room_socket(ws: WebSocket, room_code: str):
    # Uvicorn's websockets protocol implementation hardcodes a plain HTTP
    # 403 (discarding whatever custom `code` is passed) if the app calls
    # ws.close() *before* ws.accept() -- confirmed by reading
    # websockets_sansio_impl.py. A browser's native WebSocket never upgrades
    # in that case, so its onclose event never sees 4401/4404/4429 at all,
    # just a generic abnormal-closure code -- silently breaking every
    # close-code-based recovery path on the frontend. Accepting first means
    # a real WS close frame is sent afterward, which does carry the code.
    ip = client_ip(ws)

    if not limits.ws_connect.allow(ip):
        await _reject(ws, 4429, limits.ws_connect.retry_after(ip))
        return

    if _ws_conns_by_ip.get(ip, 0) >= settings.max_ws_connections_per_ip:
        await _reject(ws, 4429, 30)
        return

    # Shared with POST /rooms/{code}/rejoin: both resolve a room code, so
    # keeping one budget across both stops an attacker halving their cost by
    # alternating between them.
    if not limits.lookup.allow(ip):
        await _reject(ws, 4429, limits.lookup.retry_after(ip))
        return

    await ws.accept()
    _ws_conns_by_ip[ip] = _ws_conns_by_ip.get(ip, 0) + 1
    room = None
    player = None
    try:
        # The player token arrives in the first message, NOT the query
        # string. It used to be a query parameter, which meant uvicorn wrote
        # it to the access log in cleartext on every connect, rejection and
        # close (it logs the full path with query string, and prod runs at
        # --log-level info). That token is the entire credential for a seat,
        # never expires and cannot be revoked, so anyone who could read the
        # journal could take over any seat.
        try:
            token = await _read_auth_frame(ws)
        except _AuthFrameError:
            await ws.close(code=4401)
            return

        try:
            room, player = room_manager.rejoin_room(room_code, token)
        except EngineError:
            limits.lookup.penalize(ip, settings.failed_lookup_penalty)
            await ws.close(code=4404)
            return

        player.connected = True
        player.disconnected_at = None
        connection_manager.connect(room.code, player.seat_id, ws)
        await connection_manager.broadcast_state(room)
        await _receive_loop(ws, room, player.seat_id)
    except WebSocketDisconnect:
        pass
    finally:
        remaining = _ws_conns_by_ip.get(ip, 1) - 1
        if remaining > 0:
            _ws_conns_by_ip[ip] = remaining
        else:
            _ws_conns_by_ip.pop(ip, None)
        # Only if we got far enough to attach to a seat; an unauthenticated
        # socket has no player state to tear down.
        if room is not None and player is not None:
            player.connected = False
            player.disconnected_at = time.time()
            connection_manager.disconnect(room.code, player.seat_id)
            await connection_manager.broadcast_state(room)


async def _read_auth_frame(ws: WebSocket) -> str:
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=_AUTH_TIMEOUT_SECONDS)
    except (TimeoutError, asyncio.TimeoutError) as e:
        raise _AuthFrameError from e
    if len(raw) > settings.ws_max_message_bytes:
        raise _AuthFrameError
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise _AuthFrameError from e
    if not isinstance(msg, dict) or msg.get("type") != "auth":
        raise _AuthFrameError
    token = msg.get("player_token")
    if not isinstance(token, str):
        raise _AuthFrameError
    return token


async def _receive_loop(ws: WebSocket, room, seat_id: int) -> None:
    # Keyed by seat, not by connection: ConnectionManager keys its socket
    # table by seat_id, so several sockets bearing the same player_token
    # collapse to one entry and the broadcast fan-out is bounded by distinct
    # seats. A per-connection limiter would let one token multiply its budget
    # by opening many sockets, which is the abuse this is here to stop.
    msg_key = limits.message_key(room.code, seat_id)

    while True:
        # ws.receive() rather than ws.receive_text() so a *binary* frame is
        # handled gracefully: receive_text() raises on a bytes frame (it has
        # no "text" key), and that exception isn't a WebSocketDisconnect, so
        # it would escape this loop and drop the socket with a bare 1006.
        # Taking the raw ASGI message lets us rate-limit every frame and
        # answer a non-text one with BAD_REQUEST, mirroring the malformed-
        # JSON path below.
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))

        # Rate-limit every frame, text or binary, before doing any work.
        if not limits.ws_message_hard.allow(msg_key):
            await ws.close(code=4429, reason=str(limits.ws_message_hard.retry_after(msg_key)))
            return

        raw = message.get("text")
        if raw is None:
            # A binary frame (or an empty one). Charge it against the soft
            # limiter too so it can't be a cheaper flood than text, then
            # reject it.
            limits.ws_message.allow(msg_key)
            await connection_manager.send_error(room.code, seat_id, "BAD_REQUEST", "Text frames only")
            continue

        if len(raw) > settings.ws_max_message_bytes:
            await connection_manager.send_error(
                room.code, seat_id, "MESSAGE_TOO_LARGE", "That message was too large"
            )
            continue

        # Soft breach drops the message instead of closing: a player
        # double-tapping an action button must not lose their socket
        # mid-hand. The error reply is 1:1 with what was sent, so it
        # amplifies nothing, and the hard tier above handles a client
        # that ignores it. The ping branch sits *below* this check
        # deliberately -- exempting pings would hand over a free flood
        # that still costs a parse and a send.
        if not limits.ws_message.allow(msg_key):
            await connection_manager.send_error(
                room.code, seat_id, "RATE_LIMITED", "Slow down — too many actions at once"
            )
            continue

        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            await connection_manager.send_error(room.code, seat_id, "BAD_REQUEST", "Malformed message")
            continue
        if not isinstance(msg, dict):
            await connection_manager.send_error(room.code, seat_id, "BAD_REQUEST", "Malformed message")
            continue

        if msg.get("type") == "ping":
            await ws.send_json({"type": "pong"})
            continue
        await _handle_message(room, seat_id, msg)


async def _reject(ws: WebSocket, code: int, retry_after: int) -> None:
    """Accept-then-close so the custom code actually reaches the browser.

    The `reason` carries the retry delay in seconds: a WebSocket close has no
    headers, so this is the only way to give the client the equivalent of
    Retry-After (the frontend parses it in api/ws.ts).
    """
    await ws.accept()
    await ws.close(code=code, reason=str(retry_after))


async def _handle_message(room, seat_id: int, msg: dict) -> None:
    msg_type = msg.get("type")
    try:
        if msg_type == "update_room_config":
            room_manager.update_config(
                room,
                seat_id,
                small_blind=int(msg["small_blind"]),
                big_blind=int(msg["big_blind"]),
                starting_stack=int(msg["starting_stack"]),
                raise_presets=list(msg["raise_presets"]),
                rotate_dealer=bool(msg.get("rotate_dealer", room.config.rotate_dealer)),
            )
        elif msg_type == "start_hand":
            if seat_id != current_dealer_seat(room):
                raise EngineError("NOT_DEALER", "Only the current dealer can start a hand")
            if len(room.players) < 2:
                raise EngineError("NOT_ENOUGH_PLAYERS", "Need at least 2 players to start a hand")
            start_new_hand(room)
        elif msg_type == "player_action":
            apply_action(room, seat_id, msg["action"], msg.get("amount"))
        elif msg_type == "advance_runout":
            advance_runout(room, seat_id)
        elif msg_type == "declare_winners":
            declare_winners(room, seat_id, msg["assignments"])
        elif msg_type == "rebuy":
            rebuy(room, seat_id, int(msg["amount"]))
        elif msg_type == "toggle_sit_out":
            toggle_sit_out(room, seat_id)
        elif msg_type == "remove_stale_seat":
            room_manager.remove_stale_seat(room, seat_id, int(msg["seat_id"]))
        elif msg_type == "kick":
            target = int(msg["seat_id"])
            room_manager.kick_seat(room, seat_id, target)
            # 4403 tells the kicked client it was removed (not just dropped),
            # so it leaves instead of auto-rejoining. Close after the seat is
            # gone so the state everyone sees already reflects the removal.
            await connection_manager.close_seat(room.code, target, 4403)
        else:
            raise EngineError("UNKNOWN_MESSAGE", f"Unknown message type {msg_type!r}")
    except EngineError as e:
        await connection_manager.send_error(room.code, seat_id, e.code, e.message)
        return
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        await connection_manager.send_error(room.code, seat_id, "BAD_REQUEST", str(e))
        return

    await connection_manager.broadcast_state(room)
