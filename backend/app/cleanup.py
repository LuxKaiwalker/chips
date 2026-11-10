import asyncio
import time

from app import rate_limit
from app.config import settings
from app.rooms import room_manager
from app.ws_manager import connection_manager


async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(settings.cleanup_sweep_interval_seconds)
        sweep_once()


def sweep_once() -> None:
    now = time.time()
    # Reclaim rate-limiter keys here rather than on the request path, so
    # eviction costs nothing per request. Riding the existing 60s loop also
    # releases the short-window message-limiter keys promptly.
    rate_limit.sweep_all(now)
    for code, room in list(room_manager.rooms.items()):
        connected = connection_manager.connected_seat_count(code)
        if connected == 0:
            if room.empty_since is None:
                room.empty_since = now
            elif now - room.empty_since > settings.room_empty_grace_seconds:
                room_manager.delete_room(code)
                continue
        else:
            room.empty_since = None

        if now - room.last_activity_at > settings.room_idle_timeout_seconds:
            room_manager.delete_room(code)
