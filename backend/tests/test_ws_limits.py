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
    """A client, a room with one seated player, and that player's token."""
    client = TestClient(app)
    created = client.post("/api/rooms", json={"display_name": "Ada"}).json()
    return client, f"/ws/{created['room_code']}", created["player_token"]


def _authenticate(ws, token: str) -> None:
    """Send the auth frame, then drain the state_sync the server broadcasts.

    The token travels in the first message rather than the URL so it stays
    out of uvicorn's access log -- see ws_router.room_socket.
    """
    ws.send_text(json.dumps({"type": "auth", "player_token": token}))
    assert ws.receive_json()["type"] == "state_sync"


def test_soft_limit_drops_the_message_but_keeps_the_socket(seated, monkeypatch):
    client, url, token = seated
    monkeypatch.setattr(limits.ws_message, "max_hits", 2)
    monkeypatch.setattr(limits.ws_message_hard, "max_hits", 100)
    with client.websocket_connect(url) as ws:
        _authenticate(ws, token)
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
    client, url, token = seated
    monkeypatch.setattr(limits.ws_message, "max_hits", 1)
    monkeypatch.setattr(limits.ws_message_hard, "max_hits", 100)
    with client.websocket_connect(url) as ws:
        _authenticate(ws, token)
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["code"] == "RATE_LIMITED"


def test_hard_limit_closes_with_4429(seated, monkeypatch):
    client, url, token = seated
    monkeypatch.setattr(limits.ws_message, "max_hits", 100)
    monkeypatch.setattr(limits.ws_message_hard, "max_hits", 2)
    with client.websocket_connect(url) as ws:
        _authenticate(ws, token)
        for _ in range(2):
            ws.send_text(json.dumps({"type": "ping"}))
            assert ws.receive_json()["type"] == "pong"
        ws.send_text(json.dumps({"type": "ping"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4429


def test_oversized_frame_is_rejected_without_closing(seated, monkeypatch):
    client, url, token = seated
    monkeypatch.setattr(settings, "ws_max_message_bytes", 64)
    with client.websocket_connect(url) as ws:
        _authenticate(ws, token)
        ws.send_text(json.dumps({"type": "ping", "pad": "x" * 500}))
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "MESSAGE_TOO_LARGE"
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"


def test_non_json_frame_does_not_kill_the_connection(seated):
    # Regression: receive_json() used to raise an unhandled JSONDecodeError
    # from inside the receive loop, tearing the connection down.
    client, url, token = seated
    with client.websocket_connect(url) as ws:
        _authenticate(ws, token)
        ws.send_text("this is not json")
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "BAD_REQUEST"
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"


def test_non_object_json_frame_is_rejected(seated):
    client, url, token = seated
    with client.websocket_connect(url) as ws:
        _authenticate(ws, token)
        ws.send_text("[1, 2, 3]")
        assert ws.receive_json()["code"] == "BAD_REQUEST"


def test_per_ip_connection_cap_keeps_the_first_socket(seated, monkeypatch):
    client, url, token = seated
    monkeypatch.setattr(settings, "max_ws_connections_per_ip", 1)
    with client.websocket_connect(url) as first:
        _authenticate(first, token)
        with client.websocket_connect(url) as second:
            with pytest.raises(WebSocketDisconnect) as exc:
                second.receive_json()
            assert exc.value.code == 4429  # rejected before it can authenticate
        # The incumbent is unaffected by the rejection.
        first.send_text(json.dumps({"type": "ping"}))
        assert first.receive_json()["type"] == "pong"


def test_unknown_message_type_is_an_error_not_a_disconnect(seated):
    client, url, token = seated
    with client.websocket_connect(url) as ws:
        _authenticate(ws, token)
        ws.send_text(json.dumps({"type": "declare_winners", "assignments": {"a": 1}}))
        # AttributeError used to escape _handle_message and kill the socket.
        assert ws.receive_json()["type"] == "error"
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"


def test_missing_auth_frame_closes_4401(seated):
    client, url, token = seated
    with client.websocket_connect(url) as ws:
        ws.send_text(json.dumps({"type": "ping"}))  # not an auth frame
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_bad_token_closes_4404_and_costs_lookup_budget(seated, monkeypatch):
    client, url, token = seated
    monkeypatch.setattr(settings, "failed_lookup_penalty", 5)
    before = len(limits.lookup._hits.get("testclient", []))
    with client.websocket_connect(url) as ws:
        ws.send_text(json.dumps({"type": "auth", "player_token": "wrong"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4404
    # The handshake itself cost 1, the failure another 5.
    assert len(limits.lookup._hits.get("testclient", [])) >= before + 5


def test_binary_frame_is_a_clean_error_not_a_disconnect(seated):
    # Regression: receive_text() raises on a binary frame, and that used to
    # escape the loop and drop the socket with a bare 1006.
    client, url, token = seated
    with client.websocket_connect(url) as ws:
        _authenticate(ws, token)
        ws.send_bytes(b'{"type":"ping"}')
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "BAD_REQUEST"
        # Socket survives and still works.
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"


def test_host_kicks_a_player_and_their_socket_is_closed_4403():
    # End-to-end: host, a second player joins and opens a socket; the host
    # kicks them; the kicked socket closes 4403 and the seat is gone.
    client = TestClient(app)
    room = client.post("/api/rooms", json={"display_name": "Host"}).json()
    code = room["room_code"]
    guest = client.post(f"/api/rooms/{code}/join", json={"display_name": "Guest"}).json()

    with client.websocket_connect(f"/ws/{code}") as host_ws:
        _authenticate(host_ws, room["player_token"])
        with client.websocket_connect(f"/ws/{code}") as guest_ws:
            _authenticate(guest_ws, guest["player_token"])
            # host sees the guest join broadcast
            host_ws.receive_json()
            host_ws.send_text(json.dumps({"type": "kick", "seat_id": guest["seat_id"]}))
            with pytest.raises(WebSocketDisconnect) as exc:
                while True:
                    guest_ws.receive_json()
            assert exc.value.code == 4403

    # The seat is really gone, and the guest's token no longer resolves.
    r = client.post(f"/api/rooms/{code}/rejoin", json={"player_token": guest["player_token"]})
    assert r.status_code == 404


def test_non_host_cannot_kick():
    client = TestClient(app)
    room = client.post("/api/rooms", json={"display_name": "Host"}).json()
    code = room["room_code"]
    guest = client.post(f"/api/rooms/{code}/join", json={"display_name": "Guest"}).json()
    other = client.post(f"/api/rooms/{code}/join", json={"display_name": "Other"}).json()
    with client.websocket_connect(f"/ws/{code}") as gws:
        _authenticate(gws, guest["player_token"])
        gws.send_text(json.dumps({"type": "kick", "seat_id": other["seat_id"]}))
        msg = gws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "NOT_HOST"
