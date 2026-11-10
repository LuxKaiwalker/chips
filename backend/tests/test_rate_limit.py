import time

from fastapi.testclient import TestClient

from app import limits
from app.config import settings
from app.main import app
from app.rate_limit import KeyedLimiter


def _auth(client: TestClient) -> dict[str, str]:
    r = client.post("/api/auth/passphrase", json={"passphrase": settings.passphrase})
    assert r.status_code == 200
    return {"X-Session-Token": r.json()["session_token"]}


# --- the limiter primitive ---------------------------------------------------


def test_limiter_blocks_after_max_hits():
    limiter = KeyedLimiter(max_hits=3, window_seconds=60)
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is False


def test_limiter_keys_are_independent():
    limiter = KeyedLimiter(max_hits=1, window_seconds=60)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is False


def test_limiter_expires_old_hits():
    limiter = KeyedLimiter(max_hits=1, window_seconds=0.05)
    assert limiter.allow("x") is True
    assert limiter.allow("x") is False
    time.sleep(0.1)
    assert limiter.allow("x") is True


def test_zero_max_hits_denies_everything():
    # How the subprocess WS test forces a 4429 on the very first handshake.
    limiter = KeyedLimiter(max_hits=0, window_seconds=60)
    assert limiter.allow("x") is False
    assert limiter._hits == {}


def test_retry_after_is_zero_until_blocked_then_bounded():
    limiter = KeyedLimiter(max_hits=2, window_seconds=30)
    assert limiter.retry_after("x") == 0
    limiter.allow("x")
    assert limiter.retry_after("x") == 0
    limiter.allow("x")
    hint = limiter.retry_after("x")
    assert 1 <= hint <= 30


def test_retry_after_does_not_materialize_a_key():
    # A read must not leave an entry behind, or merely asking about keys
    # would be an unbounded-memory lever.
    limiter = KeyedLimiter(max_hits=1, window_seconds=60)
    limiter.retry_after("never-seen")
    assert limiter._hits == {}


def test_penalize_consumes_several_slots_and_stays_bounded():
    limiter = KeyedLimiter(max_hits=5, window_seconds=60)
    limiter.penalize("x", 4)
    assert limiter.allow("x") is True
    assert limiter.allow("x") is False
    # An oversized penalty must not grow the deque past max_hits.
    limiter.penalize("y", 500)
    assert len(limiter._hits["y"]) == 5


def test_sweep_drops_idle_keys_only():
    limiter = KeyedLimiter(max_hits=5, window_seconds=0.05)
    limiter.allow("stale")
    time.sleep(0.1)
    limiter.allow("fresh")
    limiter.sweep()
    assert "stale" not in limiter._hits
    assert "fresh" in limiter._hits


def test_max_keys_cap_evicts_least_recently_used():
    limiter = KeyedLimiter(max_hits=5, window_seconds=60, max_keys=3)
    for key in ("a", "b", "c"):
        limiter.allow(key)
    limiter.allow("a")  # refresh a's recency
    limiter.allow("d")  # forces an eviction
    assert len(limiter._hits) <= 3
    assert "b" not in limiter._hits  # oldest untouched key went first
    assert "a" in limiter._hits and "d" in limiter._hits


# --- the endpoints -----------------------------------------------------------


def test_create_room_rate_limited_with_retry_after(monkeypatch):
    monkeypatch.setattr(limits.create_room, "max_hits", 2)
    client = TestClient(app)
    headers = _auth(client)
    body = {"display_name": "Ada"}
    for _ in range(2):
        assert client.post("/api/rooms", json=body, headers=headers).status_code == 200
    r = client.post("/api/rooms", json=body, headers=headers)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


def test_failed_join_costs_more_than_a_successful_one(monkeypatch):
    # The asymmetry is the whole point: it is what turns a 30/min allowance
    # into ~5 room-code probes/min without throttling a real table.
    monkeypatch.setattr(limits.join, "max_hits", 12)
    monkeypatch.setattr(settings, "failed_lookup_penalty", 5)
    client = TestClient(app)
    headers = _auth(client)

    created = client.post("/api/rooms", json={"display_name": "Host"}, headers=headers).json()
    code = created["room_code"]

    # Five successful joins cost 5 of 12.
    for i in range(5):
        r = client.post(f"/api/rooms/{code}/join", json={"display_name": f"P{i}"}, headers=headers)
        assert r.status_code == 200
    # One miss costs 1 + 5 = 6, taking the total to 11.
    assert client.post("/api/rooms/000000/join", json={"display_name": "x"}, headers=headers).status_code == 404
    # The next request is the 12th and still allowed; the one after is not.
    assert client.post(f"/api/rooms/{code}/join", json={"display_name": "P9"}, headers=headers).status_code == 200
    assert client.post(f"/api/rooms/{code}/join", json={"display_name": "P10"}, headers=headers).status_code == 429


def test_room_cap_returns_503_with_retry_after(monkeypatch):
    monkeypatch.setattr(settings, "max_rooms", 1)
    monkeypatch.setattr(limits.create_room, "max_hits", 10)
    client = TestClient(app)
    headers = _auth(client)
    assert client.post("/api/rooms", json={"display_name": "Ada"}, headers=headers).status_code == 200
    r = client.post("/api/rooms", json={"display_name": "Bob"}, headers=headers)
    assert r.status_code == 503
    assert r.json()["code"] == "SERVER_AT_CAPACITY"
    assert int(r.headers["Retry-After"]) >= 1


def test_health_is_covered_by_the_router_backstop(monkeypatch):
    # /health had no limit of its own; the router-level dependency is what
    # covers it (and anything added later).
    monkeypatch.setattr(limits.rest_global, "max_hits", 3)
    client = TestClient(app)
    for _ in range(3):
        assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").status_code == 429


def test_rejoin_does_not_reveal_whether_a_room_exists(monkeypatch):
    monkeypatch.setattr(limits.lookup, "max_hits", 50)
    client = TestClient(app)
    headers = _auth(client)
    code = client.post("/api/rooms", json={"display_name": "Host"}, headers=headers).json()["room_code"]

    unknown_room = client.post("/api/rooms/000000/rejoin", json={"player_token": "nope"}, headers=headers)
    bad_token = client.post(f"/api/rooms/{code}/rejoin", json={"player_token": "nope"}, headers=headers)

    assert unknown_room.status_code == bad_token.status_code == 404
    assert unknown_room.json() == bad_token.json()


def test_malformed_room_code_is_not_a_cheaper_probe(monkeypatch):
    monkeypatch.setattr(limits.join, "max_hits", 50)
    client = TestClient(app)
    headers = _auth(client)
    r = client.post("/api/rooms/not-a-code/join", json={"display_name": "x"}, headers=headers)
    assert r.status_code == 404
    assert r.json()["code"] == "ROOM_NOT_FOUND"
