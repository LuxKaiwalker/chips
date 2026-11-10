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


@router.websocket("/ws/{room_code}")
async def room_socket(ws: WebSocket, room_code: str, player_token: str = ""):
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

    try:
        room, player = room_manager.rejoin_room(room_code, player_token)
    except EngineError:
        limits.lookup.penalize(ip, settings.failed_lookup_penalty)
        await ws.accept()
        await ws.close(code=4404)
        return

    await ws.accept()
    _ws_conns_by_ip[ip] = _ws_conns_by_ip.get(ip, 0) + 1
    player.connected = True
    player.disconnected_at = None
    connection_manager.connect(room.code, player.seat_id, ws)
    await connection_manager.broadcast_state(room)

    # Keyed by seat, not by connection: ConnectionManager keys its socket
    # table by seat_id, so several sockets bearing the same player_token
    # collapse to one entry and the broadcast fan-out is bounded by distinct
    # seats. A per-connection limiter would let one token multiply its budget
    # by opening many sockets, which is the abuse this is here to stop.
    msg_key = limits.message_key(room.code, player.seat_id)

    try:
        while True:
            # receive_text() rather than receive_json() so the cheap checks
            # below run *before* paying for a parse, and so a non-JSON frame
            # is an error message rather than an unhandled JSONDecodeError
            # that tears the connection down.
            raw = await ws.receive_text()

            if not limits.ws_message_hard.allow(msg_key):
                await ws.close(code=4429, reason=str(limits.ws_message_hard.retry_after(msg_key)))
                break

            if len(raw) > settings.ws_max_message_bytes:
                await connection_manager.send_error(
                    room.code, player.seat_id, "MESSAGE_TOO_LARGE", "That message was too large"
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
                    room.code, player.seat_id, "RATE_LIMITED", "Slow down — too many actions at once"
                )
                continue

            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                await connection_manager.send_error(
                    room.code, player.seat_id, "BAD_REQUEST", "Malformed message"
                )
                continue
            if not isinstance(msg, dict):
                await connection_manager.send_error(
                    room.code, player.seat_id, "BAD_REQUEST", "Malformed message"
                )
                continue

            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
                continue
            await _handle_message(room, player.seat_id, msg)
    except WebSocketDisconnect:
        pass
    finally:
        remaining = _ws_conns_by_ip.get(ip, 1) - 1
        if remaining > 0:
            _ws_conns_by_ip[ip] = remaining
        else:
            _ws_conns_by_ip.pop(ip, None)
        player.connected = False
        player.disconnected_at = time.time()
        connection_manager.disconnect(room.code, player.seat_id)
        await connection_manager.broadcast_state(room)


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
        else:
            raise EngineError("UNKNOWN_MESSAGE", f"Unknown message type {msg_type!r}")
    except EngineError as e:
        await connection_manager.send_error(room.code, seat_id, e.code, e.message)
        return
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        await connection_manager.send_error(room.code, seat_id, "BAD_REQUEST", str(e))
        return

    await connection_manager.broadcast_state(room)
