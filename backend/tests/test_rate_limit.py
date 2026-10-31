import time

from app.rate_limit import FixedWindowLimiter
from fastapi.testclient import TestClient

from app import rest_router
from app.main import app


def test_fixed_window_limiter_blocks_after_max_hits():
    limiter = FixedWindowLimiter(max_hits=3, window_seconds=60)
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is False


def test_fixed_window_limiter_keys_are_independent():
    limiter = FixedWindowLimiter(max_hits=1, window_seconds=60)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is False


def test_fixed_window_limiter_expires_old_hits():
    limiter = FixedWindowLimiter(max_hits=1, window_seconds=0.05)
    assert limiter.allow("x") is True
    assert limiter.allow("x") is False
    time.sleep(0.1)
    assert limiter.allow("x") is True


def test_passphrase_endpoint_rate_limited(monkeypatch):
    monkeypatch.setattr(rest_router, "_passphrase_limiter", FixedWindowLimiter(max_hits=3, window_seconds=60))
    client = TestClient(app)
    for _ in range(3):
        r = client.post("/api/auth/passphrase", json={"passphrase": "wrong"})
        assert r.status_code == 401  # wrong passphrase, but not yet rate-limited
    r = client.post("/api/auth/passphrase", json={"passphrase": "wrong"})
    assert r.status_code == 429
