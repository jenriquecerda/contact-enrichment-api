"""Small cache abstraction: Redis in production, in-memory for tests and local runs."""

import json
import time
from typing import Protocol


class Cache(Protocol):
    async def get(self, key: str) -> list | dict | None: ...

    async def set(self, key: str, value: list | dict, ttl_seconds: int) -> None: ...


class InMemoryCache:
    def __init__(self, clock=time.monotonic):
        self._items: dict[str, tuple[float, str]] = {}
        self._clock = clock

    async def get(self, key: str):
        item = self._items.get(key)
        if not item:
            return None
        expires_at, payload = item
        if self._clock() >= expires_at:
            del self._items[key]
            return None
        return json.loads(payload)

    async def set(self, key: str, value, ttl_seconds: int) -> None:
        self._items[key] = (self._clock() + ttl_seconds, json.dumps(value, default=str))


class RedisCache:
    def __init__(self, url: str, prefix: str = "enrich:"):
        from redis.asyncio import Redis  # imported lazily so tests need no Redis

        self._redis = Redis.from_url(url, decode_responses=True)
        self._prefix = prefix

    async def get(self, key: str):
        payload = await self._redis.get(self._prefix + key)
        return json.loads(payload) if payload else None

    async def set(self, key: str, value, ttl_seconds: int) -> None:
        await self._redis.set(self._prefix + key, json.dumps(value, default=str), ex=ttl_seconds)
