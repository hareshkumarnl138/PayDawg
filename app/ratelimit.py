"""Tiny in-memory rate limiter: too many payment attempts tire the Dawg out.

A client (identified by IP address) may send RATE_LIMIT_ATTEMPTS payment requests inside
RATE_LIMIT_WINDOW_SECONDS. The next one puts the Dawg to sleep for RATE_LIMIT_LOCK_SECONDS and
every request in that time gets HTTP 429 with a Retry-After header. Real gateways do the same to
slow down card-testing bots and runaway clients. Set RATE_LIMIT_ATTEMPTS=0 to switch it off.

MVP limits: state lives in this process only (it resets on restart and is not shared between
workers), and behind a reverse proxy every client would share the proxy's IP.
"""
import math
import time
from collections import defaultdict, deque

from app.config import settings

monotonic = time.monotonic  # replaced in tests


class RateLimiter:
    def __init__(self):
        self.hits = defaultdict(deque)
        self.locked_until = {}

    def reset(self):
        self.hits.clear()
        self.locked_until.clear()

    @staticmethod
    def enabled() -> bool:
        return settings.rate_limit_attempts > 0

    def _recent(self, key: str, now: float) -> int:
        q = self.hits[key]
        while q and now - q[0] >= settings.rate_limit_window_seconds:
            q.popleft()
        if not q:
            self.hits.pop(key, None)
        return len(q)

    def hit(self, key: str):
        """Count one attempt. Returns (allowed, retry_after_seconds, remaining); remaining is -1 when disabled."""
        if not self.enabled():
            return True, 0, -1
        now = monotonic()
        until = self.locked_until.get(key, 0.0)
        if now < until:
            return False, max(1, math.ceil(until - now)), 0
        self.locked_until.pop(key, None)
        if self._recent(key, now) >= settings.rate_limit_attempts:
            self.locked_until[key] = now + settings.rate_limit_lock_seconds
            self.hits.pop(key, None)
            return False, settings.rate_limit_lock_seconds, 0
        self.hits[key].append(now)
        return True, 0, settings.rate_limit_attempts - len(self.hits[key])

    def status(self, key: str) -> dict:
        now = monotonic()
        until = self.locked_until.get(key, 0.0)
        locked = self.enabled() and now < until
        return {
            "enabled": self.enabled(),
            "limit": settings.rate_limit_attempts,
            "window_seconds": settings.rate_limit_window_seconds,
            "lock_seconds": settings.rate_limit_lock_seconds,
            "recent": self._recent(key, now) if self.enabled() else 0,
            "locked": locked,
            "retry_after": max(1, math.ceil(until - now)) if locked else 0,
        }


limiter = RateLimiter()


def client_key(request) -> str:
    return request.client.host if request.client else "unknown"
