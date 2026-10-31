import time

from app.cleanup import sweep_once
from app.config import settings
from app.rooms import room_manager


def test_sweep_deletes_long_empty_room(monkeypatch):
    monkeypatch.setattr(settings, "room_empty_grace_seconds", 1)
    monkeypatch.setattr(settings, "room_idle_timeout_seconds", 999999)
    room_manager.rooms.clear()
    room, _ = room_manager.create_room("Alice", 1, 2, 200, [0.5])
    sweep_once()
    assert room.code in room_manager.rooms  # not empty long enough yet
    room.empty_since = time.time() - 10
    sweep_once()
    assert room.code not in room_manager.rooms


def test_sweep_deletes_idle_room(monkeypatch):
    monkeypatch.setattr(settings, "room_empty_grace_seconds", 999999)
    monkeypatch.setattr(settings, "room_idle_timeout_seconds", 1)
    room_manager.rooms.clear()
    room, _ = room_manager.create_room("Alice", 1, 2, 200, [0.5])
    room.last_activity_at = time.time() - 10
    sweep_once()
    assert room.code not in room_manager.rooms


def test_sweep_keeps_active_room(monkeypatch):
    monkeypatch.setattr(settings, "room_empty_grace_seconds", 999999)
    monkeypatch.setattr(settings, "room_idle_timeout_seconds", 999999)
    room_manager.rooms.clear()
    room, _ = room_manager.create_room("Alice", 1, 2, 200, [0.5])
    sweep_once()
    assert room.code in room_manager.rooms
