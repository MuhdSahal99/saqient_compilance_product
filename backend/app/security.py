from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import get_settings

_hasher = PasswordHasher()  # Argon2id with library-maintained defaults

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# A real hash to verify against when the user does not exist, so response time
# does not reveal whether an email is registered.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def burn_password_check(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


class RateLimiter:
    """Fixed-window limiter. Uses Redis when reachable, else per-process memory."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._memory: dict[str, list[float]] = defaultdict(list)
        self._redis: object | None = None
        self._redis_checked = False

    def _get_redis(self):  # type: ignore[no-untyped-def]
        if self._redis_checked:
            return self._redis
        self._redis_checked = True
        settings = get_settings()
        if settings.app_env == "test":
            return None
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.5)
            client.ping()
            self._redis = client
        except Exception:
            self._redis = None
        return self._redis

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record an attempt. Returns False when the limit is exceeded."""
        client = self._get_redis()
        if client is not None:
            try:
                rkey = f"ratelimit:{hash_token(key)}"
                count = client.incr(rkey)
                if count == 1:
                    client.expire(rkey, window_seconds)
                return int(count) <= limit
            except Exception:  # noqa: S110 - fall back to memory if redis goes away
                pass
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._memory[key] if now - t < window_seconds]
            hits.append(now)
            self._memory[key] = hits
            return len(hits) <= limit

    def reset(self) -> None:
        with self._lock:
            self._memory.clear()


login_limiter = RateLimiter()
