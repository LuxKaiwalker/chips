import pytest

from app import rate_limit
from app.rooms import room_manager
from app.ws_manager import connection_manager


@pytest.fixture(autouse=True)
def _isolate_global_state():
    """Reset every piece of process-global state between tests.

    The limiters, the room table and the connection table are all module
    globals (deliberately -- this app is single-process by design), so
    without this a test that fills a limiter or leaves a room behind changes
    the outcome of whatever runs next. Resetting via the limiter registry
    means new limiters are covered automatically.
    """
    rate_limit.reset_all()
    room_manager.rooms.clear()
    connection_manager._connections.clear()
    yield
    rate_limit.reset_all()
    room_manager.rooms.clear()
    connection_manager._connections.clear()
