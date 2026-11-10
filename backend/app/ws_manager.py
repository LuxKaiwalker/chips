from fastapi import WebSocket

from app.rooms import serialize_room


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, dict[int, WebSocket]] = {}

    def connect(self, room_code: str, seat_id: int, ws: WebSocket) -> None:
        self._connections.setdefault(room_code, {})[seat_id] = ws

    def disconnect(self, room_code: str, seat_id: int) -> None:
        self._connections.get(room_code, {}).pop(seat_id, None)
        if not self._connections.get(room_code):
            self._connections.pop(room_code, None)

    def connected_seat_count(self, room_code: str) -> int:
        return len(self._connections.get(room_code, {}))

    async def broadcast_state(self, room) -> None:
        payload = {"type": "state_sync", "room": serialize_room(room)}
        for ws in list(self._connections.get(room.code, {}).values()):
            try:
                await ws.send_json(payload)
            except Exception:
                pass

    async def close_seat(self, room_code: str, seat_id: int, code: int) -> None:
        """Close a specific seat's socket with a close code (e.g. a kick).

        The target's own room_socket coroutine, blocked on receive(), then
        sees the disconnect and runs its normal teardown; this just delivers
        the code so the client can tell a kick apart from an ordinary drop.
        """
        ws = self._connections.get(room_code, {}).get(seat_id)
        if ws is None:
            return
        try:
            await ws.close(code=code)
        except Exception:
            pass
        self._connections.get(room_code, {}).pop(seat_id, None)

    async def send_error(self, room_code: str, seat_id: int, code: str, message: str) -> None:
        ws = self._connections.get(room_code, {}).get(seat_id)
        if ws is None:
            return
        try:
            await ws.send_json({"type": "error", "code": code, "message": message})
        except Exception:
            pass


connection_manager = ConnectionManager()
