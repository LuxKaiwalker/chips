import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import websockets

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    """A real uvicorn subprocess -- not FastAPI's TestClient. This matters:
    TestClient's WebSocket simulation doesn't go through uvicorn's actual
    ASGI protocol implementation, so it can't catch uvicorn's specific
    close-before-accept behavior (ws.close() before ws.accept() is
    hardcoded to a plain HTTP 403 with the custom code discarded -- see
    ws_router.py's comment). Only a real server reproduces that.
    """
    import os

    port = _free_port()
    env = {**os.environ, "CHIPS_PASSPHRASE": "testpass"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("server never started")
    yield port
    proc.kill()
    proc.wait(timeout=5)


def test_invalid_session_token_delivers_4401(live_server):
    async def connect():
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{live_server}/ws/NOPE?session_token=invalid&player_token=invalid"
            ) as ws:
                await ws.recv()
        except websockets.exceptions.ConnectionClosed as e:
            return e.code
        return None

    code = asyncio.run(connect())
    assert code == 4401


def test_unknown_room_delivers_4404(live_server):
    import httpx

    r = httpx.post(f"http://127.0.0.1:{live_server}/api/auth/passphrase", json={"passphrase": "testpass"})
    session_token = r.json()["session_token"]

    async def connect():
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{live_server}/ws/NOPE?session_token={session_token}&player_token=nope"
            ) as ws:
                await ws.recv()
        except websockets.exceptions.ConnectionClosed as e:
            return e.code
        return None

    code = asyncio.run(connect())
    assert code == 4404
