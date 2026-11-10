import logging
import math
import time
from collections import OrderedDict, deque

logger = logging.getLogger("chips.rate_limit")

# Every limiter registers itself here so cleanup.sweep_once() can evict stale
# keys across all of them in one pass, and so tests can reset every limiter
# without knowing which modules hold which instances.
_registry: list["KeyedLimiter"] = []


class KeyedLimiter:
    """Per-key sliding-window-log rate limiter, in process memory.

    Keeps a deque of hit timestamps per key and prunes anything older than
    `window_seconds` on access, so the limit is a true sliding window rather
    than a fixed bucket that resets on a clock boundary. (This class used to
    be called FixedWindowLimiter, which it never was.)

    State is intentionally per-process and lost on restart, matching
    everything else in this app -- see the README's "single worker, by
    design" note. With `--workers 1` there is exactly one of these per
    limiter, so no sharing is needed.
    """

    def __init__(self, max_hits: int, window_seconds: float, max_keys: int = 20_000, name: str = ""):
        self.max_hits = max_hits
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.name = name or f"limiter({max_hits}/{window_seconds}s)"
        # OrderedDict rather than defaultdict for two reasons: a read
        # (retry_after) must not materialize a permanent entry for whatever
        # key it was asked about, and insertion order gives us a free LRU
        # victim for the max_keys cap below.
        self._hits: "OrderedDict[str, deque[float]]" = OrderedDict()
        self._last_sweep = 0.0
        _registry.append(self)

    def allow(self, key: str) -> bool:
        now = time.time()
        hits = self._prune(key, now)
        # Checked before the insert branch so max_hits=0 denies everything
        # (the tests use a 0-limit server) without materializing a key.
        if (0 if hits is None else len(hits)) >= self.max_hits:
            return False
        if hits is None:
            hits = deque()
            self._hits[key] = hits
            self._enforce_key_cap()
        hits.append(now)
        self._hits.move_to_end(key)
        return True

    def penalize(self, key: str, extra_hits: int = 1) -> None:
        """Charge a key extra budget for an attempt that failed.

        Used so a wrong room code costs several slots while a correct one
        costs one -- that asymmetry is what makes enumeration expensive
        without throttling a real table.
        """
        now = time.time()
        hits = self._prune(key, now)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
            self._enforce_key_cap()
        for _ in range(extra_hits):
            hits.append(now)
        # Keep the deque bounded regardless of how large a penalty is applied.
        while len(hits) > self.max_hits:
            hits.popleft()
        self._hits.move_to_end(key)

    def retry_after(self, key: str) -> int:
        """Whole seconds until this key's oldest in-window hit expires.

        0 when the key is not currently blocked, otherwise >= 1 so the value
        is usable directly as a Retry-After header.
        """
        now = time.time()
        hits = self._hits.get(key)
        if not hits:
            return 0
        cutoff = now - self.window_seconds
        in_window = [h for h in hits if h >= cutoff]
        if len(in_window) < self.max_hits:
            return 0
        return max(1, math.ceil(in_window[0] + self.window_seconds - now))

    def sweep(self, now: float | None = None) -> None:
        """Drop keys whose most recent hit has aged out of the window."""
        now = time.time() if now is None else now
        cutoff = now - self.window_seconds
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] < cutoff]:
            del self._hits[key]
        self._last_sweep = now

    def reset(self) -> None:
        self._hits.clear()
        self._last_sweep = 0.0

    def _prune(self, key: str, now: float) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        cutoff = now - self.window_seconds
        while hits and hits[0] < cutoff:
            hits.popleft()
        return hits

    def _enforce_key_cap(self) -> None:
        # The periodic sweep alone is not enough: between two sweeps an
        # attacker with an IPv6 /64 can mint millions of keys. LRU eviction
        # here is safe because dropping a key can only *reset* a counter,
        # and a single-IP attacker cannot evict their own key -- their own
        # requests keep moving it to the end. Evicting someone else's key
        # requires a large IP pool, which already defeats per-IP limiting at
        # every layer, so this trades nothing real for a hard memory bound.
        if len(self._hits) <= self.max_keys:
            return
        while len(self._hits) > self.max_keys:
            self._hits.popitem(last=False)
        logger.warning(
            "%s hit its %d-key cap; evicting least-recently-used keys", self.name, self.max_keys
        )


def sweep_all(now: float | None = None) -> None:
    for limiter in _registry:
        limiter.sweep(now)


def reset_all() -> None:
    for limiter in _registry:
        limiter.reset()


_warned_missing_client = False


def client_ip(conn) -> str:
    """Best-effort client IP for a Request or WebSocket.

    Deliberately does NOT parse X-Forwarded-For. uvicorn's
    ProxyHeadersMiddleware already does it correctly and more safely than we
    could here: it walks X-Forwarded-For right-to-left and returns the first
    entry from an untrusted hop, and it only trusts the header at all from
    `--forwarded-allow-ips` (loopback). nginx sets `real_ip_header
    CF-Connecting-IP` and then appends the true client IP last via
    `$proxy_add_x_forwarded_for`, so `conn.client.host` is the real client in
    the public deployment -- for WebSocket scopes too. Parsing the header
    ourselves would re-introduce the spoofing we currently don't have.

    That guarantee depends on the uvicorn flags in run.sh and
    scripts/run-prod.sh (`--no-proxy-headers` in LAN mode, which has no proxy
    and must never trust the header; explicit `--forwarded-allow-ips
    127.0.0.1` in public mode). Don't pass `--forwarded-allow-ips "*"`: it
    flips uvicorn to taking X-Forwarded-For[0], which any client can set.
    """
    global _warned_missing_client
    if conn.client:
        return conn.client.host
    # Fail-closed: everything without a peer address shares one bucket, which
    # can only cause spurious 429s for those callers, never a bypass. Under
    # uvicorn scope["client"] is always set, so this is effectively
    # TestClient-only -- log once rather than per request.
    if not _warned_missing_client:
        _warned_missing_client = True
        logger.warning("connection with no client address; rate-limiting it under the shared 'unknown' key")
    return "unknown"
