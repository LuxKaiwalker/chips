import asyncio
import os
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


def _start_server(extra_env: dict[str, str] | None = None):
    """Boot a real uvicorn subprocess -- not FastAPI's TestClient.

    This matters: TestClient's WebSocket simulation doesn't go through
    uvicorn's actual ASGI protocol implementation, so it can't catch
    uvicorn's specific close-before-accept behavior (ws.close() before
    ws.accept() is hardcoded to a plain HTTP 403 with the custom code
    discarded -- see ws_router.py's comment). Only a real server reproduces
    that, which is why the handshake rejections are tested here rather than
    alongside the post-accept codes in test_ws_limits.py.
    """
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND_DIR,
        env={**os.environ, **(extra_env or {})},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return port, proc
        except OSError:
            time.sleep(0.1)
    proc.kill()
    pytest.fail("server never started")


@pytest.fixture(scope="module")
def live_server():
    port, proc = _start_server()
    yield port
    proc.kill()
    proc.wait(timeout=5)


@pytest.fixture(scope="module")
def throttled_server():
    """A server whose WS connect limit is zero, so it denies the very first
    handshake. Lets the 4429 path be tested without having to set up a room
    or race a real limit.
    """
    port, proc = _start_server({"RL_WS_CONNECT_MAX": "0"})
    yield port
    proc.kill()
    proc.wait(timeout=5)


def _close_code(port: int, query: str) -> int | None:
    async def connect():
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws/NOPE?{query}") as ws:
                await ws.recv()
        except websockets.exceptions.ConnectionClosed as e:
            return e.code
        return None

    return asyncio.run(connect())


def test_unknown_room_delivers_4404(live_server):
    assert _close_code(live_server, "player_token=nope") == 4404


def test_connect_flood_delivers_4429(throttled_server):
    # The accept-before-close dance is what makes this reach the client at
    # all; without it uvicorn would send a bare HTTP 403 and the browser's
    # onclose would never see 4429.
    assert _close_code(throttled_server, "player_token=nope") == 4429
