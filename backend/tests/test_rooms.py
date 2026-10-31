import time

import pytest

from app.engine import EngineError
from app.models import RoomPhase
from app.rooms import RoomManager


def test_create_join_rejoin():
    rm = RoomManager()
    room, host = rm.create_room("Alice", 1, 2, 200, [0.5, 1.0])
    assert host.seat_id == 1
    assert room.host_seat_id == 1

    room2, bob = rm.join_room(room.code, "Bob")
    assert room2.code == room.code
    assert bob.seat_id == 2

    with pytest.raises(EngineError) as exc:
        rm.join_room("ZZZZ", "Nobody")
    assert exc.value.code == "ROOM_NOT_FOUND"

    room3, rejoined = rm.rejoin_room(room.code, bob.player_token)
    assert rejoined.seat_id == 2

    with pytest.raises(EngineError) as exc:
        rm.rejoin_room(room.code, "not-a-real-token")
    assert exc.value.code == "PLAYER_NOT_FOUND"


def test_duplicate_display_name_rejected():
    rm = RoomManager()
    room, _host = rm.create_room("Alice", 1, 2, 200, [0.5, 1.0])
    rm.join_room(room.code, "Bob")

    with pytest.raises(EngineError) as exc:
        rm.join_room(room.code, "alice")  # case-insensitive match against the host's name
    assert exc.value.code == "NAME_TAKEN"

    with pytest.raises(EngineError) as exc:
        rm.join_room(room.code, "  Bob  ")  # whitespace-trimmed match
    assert exc.value.code == "NAME_TAKEN"

    # a genuinely different name still works
    rm.join_room(room.code, "Carol")


def test_name_validation():
    rm = RoomManager()
    with pytest.raises(EngineError) as exc:
        rm.create_room("   ", 1, 2, 200, [0.5, 1.0])
    assert exc.value.code == "INVALID_NAME"

    with pytest.raises(EngineError) as exc:
        rm.create_room("x" * 25, 1, 2, 200, [0.5, 1.0])
    assert exc.value.code == "INVALID_NAME"


def test_update_config_host_only_and_lobby_only():
    rm = RoomManager()
    room, host = rm.create_room("Alice", 1, 2, 200, [0.5, 1.0])
    _, bob = rm.join_room(room.code, "Bob")

    with pytest.raises(EngineError) as exc:
        rm.update_config(room, bob.seat_id, 2, 4, 400, [0.5])
    assert exc.value.code == "NOT_HOST"

    rm.update_config(room, host.seat_id, 2, 4, 400, [0.5])
    assert room.config.big_blind == 4
    assert room.players[1].stack == 400 and room.players[2].stack == 400

    room.phase = RoomPhase.IN_HAND
    with pytest.raises(EngineError) as exc:
        rm.update_config(room, host.seat_id, 2, 4, 400, [0.5])
    assert exc.value.code == "ILLEGAL_ACTION"


def test_remove_stale_seat_gating():
    rm = RoomManager()
    room, host = rm.create_room("Alice", 1, 2, 200, [0.5, 1.0])
    _, bob = rm.join_room(room.code, "Bob")

    with pytest.raises(EngineError) as exc:
        rm.remove_stale_seat(room, bob.seat_id, bob.seat_id)
    assert exc.value.code == "NOT_HOST"

    with pytest.raises(EngineError) as exc:
        rm.remove_stale_seat(room, host.seat_id, bob.seat_id)
    assert exc.value.code == "ILLEGAL_ACTION"  # still connected

    bob.connected = False
    bob.disconnected_at = time.time()
    with pytest.raises(EngineError) as exc:
        rm.remove_stale_seat(room, host.seat_id, bob.seat_id)
    assert exc.value.code == "ILLEGAL_ACTION"  # not disconnected long enough

    bob.disconnected_at = time.time() - 10_000
    rm.remove_stale_seat(room, host.seat_id, bob.seat_id)
    assert bob.seat_id not in room.players

    room.phase = RoomPhase.IN_HAND
    _, carol = rm.join_room(room.code, "Carol")
    carol.connected = False
    carol.disconnected_at = time.time() - 10_000
    with pytest.raises(EngineError) as exc:
        rm.remove_stale_seat(room, host.seat_id, carol.seat_id)
    assert exc.value.code == "ILLEGAL_ACTION"  # mid-hand
