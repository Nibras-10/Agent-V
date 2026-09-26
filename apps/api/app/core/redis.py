import asyncio
from typing import Optional
import redis.asyncio as aioredis
from app.core.config import settings
from app.observability.logging import logger


class InMemoryCache:
    """In-memory fallback cache and lock store for testing/offline mode."""
    def __init__(self):
        self._data: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        self._data[key] = value
        # Optional: in-memory key expiry can be handled or left simple
        return True

    async def setnx(self, key: str, value: str) -> bool:
        if key in self._data:
            return False
        self._data[key] = value
        return True

    async def delete(self, key: str) -> int:
        return 1 if self._data.pop(key, None) is not None else 0

    async def ping(self) -> bool:
        return True

    async def close(self):
        pass


class RedisClient:
    def __init__(self):
        self._client = None
        self._use_fallback = False
        self._fallback = InMemoryCache()

    async def init(self):
        try:
            self._client = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
            )
            await self._client.ping()
            self._use_fallback = False
            logger.info("Connected to Redis server.")
        except Exception as e:
            if settings.is_production:
                raise RuntimeError("Redis is required in production") from e
            logger.warning(f"Could not connect to Redis ({e}), using in-memory fallback store.")
            self._use_fallback = True

    async def get(self, key: str) -> Optional[str]:
        if self._use_fallback or not self._client:
            return await self._fallback.get(key)
        try:
            return await self._client.get(key)
        except Exception:
            return await self._fallback.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        if self._use_fallback or not self._client:
            return await self._fallback.set(key, value, ex=ex)
        try:
            return await self._client.set(key, value, ex=ex)
        except Exception:
            return await self._fallback.set(key, value, ex=ex)

    async def setnx(self, key: str, value: str) -> bool:
        if self._use_fallback or not self._client:
            return await self._fallback.setnx(key, value)
        try:
            return bool(await self._client.setnx(key, value))
        except Exception:
            return await self._fallback.setnx(key, value)

    async def delete(self, key: str) -> int:
        if self._use_fallback or not self._client:
            return await self._fallback.delete(key)
        try:
            return await self._client.delete(key)
        except Exception:
            return await self._fallback.delete(key)

    async def close(self):
        if self._client and not self._use_fallback:
            await self._client.close()


redis_client = RedisClient()
