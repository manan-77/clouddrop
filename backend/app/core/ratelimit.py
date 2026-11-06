"""Fixed-window rate limiting on Redis.

Keys hold counters only. Subjects (IPs, emails) are hashed, so no address or email is stored in
Redis or logged. If Redis is unreachable the limiter fails open and logs a warning: an outage
must not lock every user out, and the login hash cost already bounds a single guesser.
"""

import hashlib
import ipaddress
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Protocol

import redis
from fastapi import Depends, Request

from app.core.config import get_settings
from app.core.errors import TooManyRequestsError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult: ...


# shortcut: fixed windows allow up to 2x the limit across a window edge; move to a sliding window
# if that matters.
class RedisRateLimiter:
    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        try:
            pipe = self.client.pipeline(transaction=True)
            pipe.set(key, 0, ex=window_seconds, nx=True)  # starts the window once
            pipe.incr(key)
            pipe.ttl(key)
            _, count, ttl = pipe.execute()
            if ttl < 0:  # a key without an expiry would block forever
                self.client.expire(key, window_seconds)
                ttl = window_seconds
        except redis.RedisError:
            logger.warning("Rate limiter unavailable; allowing the request")
            return RateLimitResult(True, 0)
        return RateLimitResult(count <= limit, ttl)


@lru_cache
def _redis_limiter() -> RedisRateLimiter:
    client = redis.Redis.from_url(
        get_settings().redis_url.get_secret_value(),
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    return RedisRateLimiter(client)


def get_rate_limiter() -> RateLimiter:
    return _redis_limiter()


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def client_ip(request: Request) -> str:
    # Behind a reverse proxy, run uvicorn with --proxy-headers and --forwarded-allow-ips set to
    # the proxy, so this is the real client and a spoofed X-Forwarded-For is ignored.
    return ip_bucket(request.client.host if request.client else "unknown")


def ip_bucket(host: str) -> str:
    """IPv6 clients rotate freely inside a /64, so they share one budget per /64."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if address.version == 6:
        return str(ipaddress.ip_network(f"{host}/64", strict=False))
    return host


def enforce(
    limiter: RateLimiter, scope: str, subject: str, limit: int, window_seconds: int
) -> None:
    digest = hashlib.sha256(subject.encode()).hexdigest()[:32]
    result = limiter.hit(f"rl:{scope}:{digest}", limit, window_seconds)
    if not result.allowed:
        raise TooManyRequestsError(result.retry_after_seconds)
