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


def test_room_code_is_alphanumeric_and_case_insensitive():
    from app.config import settings

    rm = RoomManager()
    room, _ = rm.create_room("Alice", 1, 2, 200, [0.5, 1.0])
    assert len(room.code) == settings.room_code_length
    assert all(c in settings.room_code_alphabet for c in room.code)
    # Lookups canonicalise case, so a lowercased code still resolves.
    found, _ = rm.rejoin_room(room.code.lower(), rm.rooms[room.code].players[1].player_token)
    assert found.code == room.code
    # A malformed code (contains an excluded glyph) is a clean not-found.
    with pytest.raises(EngineError) as exc:
        rm.join_room("000000", "Bob")  # 0 is not in the alphabet
    assert exc.value.code == "ROOM_NOT_FOUND"


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


def test_kick_seat_gating():
    rm = RoomManager()
    room, host = rm.create_room("Alice", 1, 2, 200, [0.5, 1.0])
    _, bob = rm.join_room(room.code, "Bob")

    # non-host cannot kick
    with pytest.raises(EngineError) as exc:
        rm.kick_seat(room, bob.seat_id, host.seat_id)
    assert exc.value.code == "NOT_HOST"

    # host cannot kick themselves
    with pytest.raises(EngineError) as exc:
        rm.kick_seat(room, host.seat_id, host.seat_id)
    assert exc.value.code == "ILLEGAL_ACTION"

    # unknown seat
    with pytest.raises(EngineError) as exc:
        rm.kick_seat(room, host.seat_id, 999)
    assert exc.value.code == "PLAYER_NOT_FOUND"

    # unlike remove_stale_seat, a *connected* player can be kicked immediately
    assert bob.connected is False or bob.connected is True  # default state irrelevant
    bob.connected = True
    rm.kick_seat(room, host.seat_id, bob.seat_id)
    assert bob.seat_id not in room.players

    # not allowed mid-hand
    _, carol = rm.join_room(room.code, "Carol")
    room.phase = RoomPhase.IN_HAND
    with pytest.raises(EngineError) as exc:
        rm.kick_seat(room, host.seat_id, carol.seat_id)
    assert exc.value.code == "ILLEGAL_ACTION"


def test_kicking_button_holder_does_not_soft_lock_start():
    # With rotate_dealer on, current_dealer_seat points at the last hand's
    # button. If that seat is kicked between hands, the dealer must fall back
    # to the host so someone can still start the next hand.
    from app.models import HandState, Street, current_dealer_seat

    rm = RoomManager()
    room, host = rm.create_room("Alice", 1, 2, 200, [0.5, 1.0], rotate_dealer=True)
    _, bob = rm.join_room(room.code, "Bob")
    room.hand = HandState(hand_number=1, button_seat=bob.seat_id, street=Street.PREFLOP)
    room.phase = RoomPhase.BETWEEN_HANDS
    assert current_dealer_seat(room) == bob.seat_id

    rm.kick_seat(room, host.seat_id, bob.seat_id)
    assert current_dealer_seat(room) == host.seat_id  # fell back, not stranded
