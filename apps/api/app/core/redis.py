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
        self._expires: dict[str, float] = {}

    async def get(self, key: str) -> Optional[str]:
        if self._expires.get(key, 0) and self._expires[key] <= asyncio.get_running_loop().time():
            self._data.pop(key, None)
            self._expires.pop(key, None)
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        self._data[key] = value
        if ex is not None:
            self._expires[key] = asyncio.get_running_loop().time() + ex
        return True

    async def increment_window(self, key: str, window_seconds: int) -> int:
        async with self._locks.setdefault(key, asyncio.Lock()):
            now = asyncio.get_running_loop().time()
            if self._expires.get(key, 0) <= now:
                self._data.pop(key, None)
                self._data[key] = "0"
                self._expires[key] = now + window_seconds
            self._data[key] = str(int(self._data[key]) + 1)
            return int(self._data[key])

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
            logger.warning("Redis connection failed; using development fallback.", extra={"error_type": type(e).__name__})
            self._use_fallback = True

    async def get(self, key: str) -> Optional[str]:
        if self._use_fallback or not self._client:
            if settings.is_production and not self._use_fallback:
                raise RuntimeError("Redis is unavailable in production")
            return await self._fallback.get(key)
        try:
            return await self._client.get(key)
        except Exception as exc:
            if settings.is_production:
                raise RuntimeError("Redis is unavailable in production") from exc
            return await self._fallback.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        if self._use_fallback or not self._client:
            return await self._fallback.set(key, value, ex=ex)
        try:
            return await self._client.set(key, value, ex=ex)
        except Exception as exc:
            if settings.is_production:
                raise RuntimeError("Redis is unavailable in production") from exc
            return await self._fallback.set(key, value, ex=ex)

    async def increment_window(self, key: str, window_seconds: int) -> int:
        if self._use_fallback or not self._client:
            if settings.is_production:
                raise RuntimeError("Redis is required for production rate limiting")
            return await self._fallback.increment_window(key, window_seconds)
        script = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]); end; return n"
        try:
            return int(await self._client.eval(script, 1, key, window_seconds))
        except Exception as exc:
            if settings.is_production:
                raise RuntimeError("Redis is unavailable in production") from exc
            return await self._fallback.increment_window(key, window_seconds)

    async def setnx(self, key: str, value: str) -> bool:
        if self._use_fallback or not self._client:
            return await self._fallback.setnx(key, value)
        try:
            return bool(await self._client.setnx(key, value))
        except Exception as exc:
            if settings.is_production:
                raise RuntimeError("Redis is unavailable in production") from exc
            return await self._fallback.setnx(key, value)

    async def delete(self, key: str) -> int:
        if self._use_fallback or not self._client:
            return await self._fallback.delete(key)
        try:
            return await self._client.delete(key)
        except Exception as exc:
            if settings.is_production:
                raise RuntimeError("Redis is unavailable in production") from exc
            return await self._fallback.delete(key)

    async def ping(self) -> bool:
        if self._use_fallback or not self._client:
            if settings.is_production:
                raise RuntimeError("Redis is required for production readiness")
            return await self._fallback.ping()
        try:
            return bool(await self._client.ping())
        except Exception as exc:
            if settings.is_production:
                raise RuntimeError("Redis is unavailable in production") from exc
            return await self._fallback.ping()

    async def close(self):
        if self._client and not self._use_fallback:
            await self._client.close()


redis_client = RedisClient()
