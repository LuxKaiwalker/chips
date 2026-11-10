"""In-game WebSocket message limits.

These use plain TestClient rather than the uvicorn subprocess that
test_ws_close_codes.py needs: starlette's WebSocketTestSession raises
WebSocketDisconnect(code=...) from its receive methods, so close codes sent
*after* accept are observable here. Only close-before-accept (the handshake
rejections) needs a real server.
"""

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import limits
from app.config import settings
from app.main import app


@pytest.fixture
def seated():
    """A client plus a room with one seated player, ready to open a socket."""
    client = TestClient(app)
    created = client.post("/api/rooms", json={"display_name": "Ada"}).json()
    url = f"/ws/{created['room_code']}?player_token={created['player_token']}"
    return client, url


def _drain_state_sync(ws) -> None:
    # Connecting triggers a broadcast; skip it so tests read their own replies.
    assert ws.receive_json()["type"] == "state_sync"


def test_soft_limit_drops_the_message_but_keeps_the_socket(seated, monkeypatch):
    client, url = seated
    monkeypatch.setattr(limits.ws_message, "max_hits", 2)
    monkeypatch.setattr(limits.ws_message_hard, "max_hits", 100)
    with client.websocket_connect(url) as ws:
        _drain_state_sync(ws)
        for _ in range(2):
            ws.send_text(json.dumps({"type": "ping"}))
            assert ws.receive_json()["type"] == "pong"
        ws.send_text(json.dumps({"type": "ping"}))
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "RATE_LIMITED"
        # Still usable once the window clears -- the socket was not closed.
        limits.ws_message.reset()
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"


def test_ping_is_not_a_free_bypass(seated, monkeypatch):
    # The limiter check sits above the ping branch on purpose: an exempt
    # ping would still cost a parse and a send per message.
    client, url = seated
    monkeypatch.setattr(limits.ws_message, "max_hits", 1)
    monkeypatch.setattr(limits.ws_message_hard, "max_hits", 100)
    with client.websocket_connect(url) as ws:
        _drain_state_sync(ws)
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["code"] == "RATE_LIMITED"


def test_hard_limit_closes_with_4429(seated, monkeypatch):
    client, url = seated
    monkeypatch.setattr(limits.ws_message, "max_hits", 100)
    monkeypatch.setattr(limits.ws_message_hard, "max_hits", 2)
    with client.websocket_connect(url) as ws:
        _drain_state_sync(ws)
        for _ in range(2):
            ws.send_text(json.dumps({"type": "ping"}))
            assert ws.receive_json()["type"] == "pong"
        ws.send_text(json.dumps({"type": "ping"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4429


def test_oversized_frame_is_rejected_without_closing(seated, monkeypatch):
    client, url = seated
    monkeypatch.setattr(settings, "ws_max_message_bytes", 64)
    with client.websocket_connect(url) as ws:
        _drain_state_sync(ws)
        ws.send_text(json.dumps({"type": "ping", "pad": "x" * 500}))
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "MESSAGE_TOO_LARGE"
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"


def test_non_json_frame_does_not_kill_the_connection(seated):
    # Regression: receive_json() used to raise an unhandled JSONDecodeError
    # from inside the receive loop, tearing the connection down.
    client, url = seated
    with client.websocket_connect(url) as ws:
        _drain_state_sync(ws)
        ws.send_text("this is not json")
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "BAD_REQUEST"
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"


def test_non_object_json_frame_is_rejected(seated):
    client, url = seated
    with client.websocket_connect(url) as ws:
        _drain_state_sync(ws)
        ws.send_text("[1, 2, 3]")
        assert ws.receive_json()["code"] == "BAD_REQUEST"


def test_per_ip_connection_cap_keeps_the_first_socket(seated, monkeypatch):
    client, url = seated
    monkeypatch.setattr(settings, "max_ws_connections_per_ip", 1)
    with client.websocket_connect(url) as first:
        _drain_state_sync(first)
        with client.websocket_connect(url) as second:
            with pytest.raises(WebSocketDisconnect) as exc:
                second.receive_json()
            assert exc.value.code == 4429
        # The incumbent is unaffected by the rejection.
        first.send_text(json.dumps({"type": "ping"}))
        assert first.receive_json()["type"] == "pong"


def test_unknown_message_type_is_an_error_not_a_disconnect(seated):
    client, url = seated
    with client.websocket_connect(url) as ws:
        _drain_state_sync(ws)
        ws.send_text(json.dumps({"type": "declare_winners", "assignments": {"a": 1}}))
        # AttributeError used to escape _handle_message and kill the socket.
        assert ws.receive_json()["type"] == "error"
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"
