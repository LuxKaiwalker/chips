import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import is_valid_session_token
from app.engine import EngineError
from app.engine.state_machine import advance_runout, apply_action, declare_winners, rebuy, start_new_hand
from app.models import PlayerStatus
from app.rooms import room_manager
from app.ws_manager import connection_manager

router = APIRouter()


@router.websocket("/ws/{room_code}")
async def room_socket(ws: WebSocket, room_code: str, session_token: str = "", player_token: str = ""):
    if not is_valid_session_token(session_token):
        await ws.close(code=4401)
        return

    try:
        room, player = room_manager.rejoin_room(room_code, player_token)
    except EngineError:
        await ws.close(code=4404)
        return

    await ws.accept()
    player.connected = True
    player.disconnected_at = None
    connection_manager.connect(room.code, player.seat_id, ws)
    await connection_manager.broadcast_state(room)

    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
                continue
            await _handle_message(room, player.seat_id, msg)
    except WebSocketDisconnect:
        pass
    finally:
        player.connected = False
        player.disconnected_at = time.time()
        connection_manager.disconnect(room.code, player.seat_id)
        await connection_manager.broadcast_state(room)


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
            )
        elif msg_type == "start_hand":
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
        elif msg_type == "remove_stale_seat":
            room_manager.remove_stale_seat(room, seat_id, int(msg["seat_id"]))
        else:
            raise EngineError("UNKNOWN_MESSAGE", f"Unknown message type {msg_type!r}")
    except EngineError as e:
        await connection_manager.send_error(room.code, seat_id, e.code, e.message)
        return
    except (KeyError, ValueError, TypeError) as e:
        await connection_manager.send_error(room.code, seat_id, "BAD_REQUEST", str(e))
        return

    await connection_manager.broadcast_state(room)
