"""Tiny in-memory rate limiter (flood guard) for payment attempts.

A client (identified by IP address) may send RATE_LIMIT_ATTEMPTS payment requests inside
RATE_LIMIT_WINDOW_SECONDS. The next one locks that client out for RATE_LIMIT_LOCK_SECONDS and
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
GLOBAL_KEY = "\x00all-clients"  # the shop-wide bucket; the \x00 keeps it out of any real client key


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

    def _prune(self, now: float):
        """Drop expired locks and idle clients so the dictionaries cannot grow without bound."""
        if len(self.locked_until) > 1000:
            self.locked_until = {k: v for k, v in self.locked_until.items() if v > now}
        if len(self.hits) > 1000:
            for k in [k for k, q in self.hits.items() if not q or now - q[-1] >= settings.rate_limit_window_seconds]:
                del self.hits[k]

    def _buckets(self, key: str):
        buckets = [(key, settings.rate_limit_attempts)]
        if settings.rate_limit_global_attempts > 0:
            buckets.append((GLOBAL_KEY, settings.rate_limit_global_attempts))
        return buckets

    def hit(self, key: str):
        """Count one attempt against this client and the shop-wide ceiling.

        Returns (allowed, retry_after_seconds, remaining); remaining is -1 when the limiter is off.
        """
        if not self.enabled():
            return True, 0, -1
        now = monotonic()
        self._prune(now)
        buckets = self._buckets(key)
        for bucket, _limit in buckets:
            until = self.locked_until.get(bucket, 0.0)
            if now < until:
                return False, max(1, math.ceil(until - now)), 0
            self.locked_until.pop(bucket, None)
        over = [bucket for bucket, limit in buckets if self._recent(bucket, now) >= limit]
        if over:
            for bucket in over:
                self.locked_until[bucket] = now + settings.rate_limit_lock_seconds
                self.hits.pop(bucket, None)
            return False, settings.rate_limit_lock_seconds, 0
        for bucket, _limit in buckets:
            self.hits[bucket].append(now)
        return True, 0, settings.rate_limit_attempts - len(self.hits[key])

    def status(self, key: str) -> dict:
        now = monotonic()
        until = max(self.locked_until.get(key, 0.0), self.locked_until.get(GLOBAL_KEY, 0.0))
        locked = self.enabled() and now < until
        return {
            "enabled": self.enabled(),
            "limit": settings.rate_limit_attempts,
            "window_seconds": settings.rate_limit_window_seconds,
            "lock_seconds": settings.rate_limit_lock_seconds,
            "recent": self._recent(key, now) if self.enabled() else 0,
            "locked": locked,
            "shop_wide": self.enabled() and now < self.locked_until.get(GLOBAL_KEY, 0.0),
            "retry_after": max(1, math.ceil(until - now)) if locked else 0,
        }


limiter = RateLimiter()


def client_key(request) -> str:
    """Which client an attempt is charged to.

    Forwarded headers are only honoured when TRUST_PROXY_HEADERS is set, because anyone can send one; then the
    address your proxy appended (the last one) is used, never one the client wrote itself.
    Note that uvicorn rewrites request.client itself when its own --proxy-headers is active (it is by
    default, for peers in --forwarded-allow-ips), so run it with --no-proxy-headers unless a proxy you
    control sits in front. The shop-wide ceiling limits the damage either way.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # The LAST address is the one your proxy added. Earlier ones were sent by the client and can be anything,
            # so reading the first one let a client pick a fresh rate-limit identity per request.
            return forwarded.split(",")[-1].strip()[:64] or "unknown"
    return request.client.host if request.client else "unknown"
