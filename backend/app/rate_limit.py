import time
from collections import defaultdict


class FixedWindowLimiter:
    """Simple in-process per-key rate limiter. Good enough for a
    single-worker, single-process app (see README's "single worker, by
    design" note) -- this state is intentionally not shared across
    processes/restarts, matching everything else in this app.
    """

    def __init__(self, max_hits: int, window_seconds: float):
        self.max_hits = max_hits
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        hits = self._hits[key]
        while hits and hits[0] < cutoff:
            hits.pop(0)
        if len(hits) >= self.max_hits:
            return False
        hits.append(now)
        return True


def client_ip(request) -> str:
    return request.client.host if request.client else "unknown"
