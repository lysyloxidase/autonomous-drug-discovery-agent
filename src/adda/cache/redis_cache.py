"""Optional Redis cache adapter."""

from __future__ import annotations

import pickle
from typing import Any

from redis.asyncio import Redis


class RedisCacheBackend:
    """Async Redis cache backend using pickle for Python objects."""

    def __init__(self, url: str) -> None:
        self._redis: Redis = Redis.from_url(url)

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        return pickle.loads(raw)

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        payload = pickle.dumps(value)
        await self._redis.set(key, payload, ex=ttl_seconds)

    async def clear(self) -> None:
        await self._redis.flushdb()

    async def close(self) -> None:
        await self._redis.aclose()
