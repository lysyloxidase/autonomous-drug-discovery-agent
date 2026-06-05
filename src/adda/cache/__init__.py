"""Cache helpers and decorator used by retrieval clients."""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import os
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, ParamSpec, TypeVar, overload

from pydantic import BaseModel

from adda.cache.disk_cache import DiskCacheBackend
from adda.cache.redis_cache import RedisCacheBackend

P = ParamSpec("P")
R = TypeVar("R")

CacheBackend = DiskCacheBackend | RedisCacheBackend
_cache_backend: CacheBackend | None = None


def get_cache_backend() -> CacheBackend:
    """Return the process-global cache backend."""

    global _cache_backend
    if _cache_backend is None:
        backend = os.getenv("ADDA_CACHE_BACKEND", "disk").lower()
        if backend == "redis":
            redis_url = os.getenv("REDIS_URL")
            if not redis_url:
                raise RuntimeError("ADDA_CACHE_BACKEND=redis requires REDIS_URL")
            _cache_backend = RedisCacheBackend(redis_url)
        else:
            cache_dir = os.getenv("ADDA_CACHE_DIR", ".cache/adda")
            _cache_backend = DiskCacheBackend(cache_dir)
    return _cache_backend


def set_cache_backend(backend: CacheBackend | None) -> None:
    """Override the process-global backend, primarily for tests."""

    global _cache_backend
    _cache_backend = backend


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def make_cache_key(namespace: str, *args: Any, **kwargs: Any) -> str:
    """Build a stable cache key from a namespace plus call arguments."""

    payload = {"args": _jsonable(args), "kwargs": _jsonable(kwargs)}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"{namespace}:{digest}"


def _strip_self(args: tuple[Any, ...]) -> tuple[Any, ...]:
    if (
        args
        and hasattr(args[0], "__class__")
        and not isinstance(
            args[0], (str, bytes, int, float, bool, list, tuple, dict, set)
        )
    ):
        return args[1:]
    return args


async def cache_get(key: str) -> Any | None:
    backend = get_cache_backend()
    result = backend.get(key)
    if inspect.isawaitable(result):
        return await result
    return result


async def cache_set(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    backend = get_cache_backend()
    result = backend.set(key, value, ttl_seconds)
    if inspect.isawaitable(result):
        await result


@overload
def cached(func: Callable[P, Awaitable[R]]) -> Callable[P, Coroutine[Any, Any, R]]: ...


@overload
def cached(
    func: None = None, *, ttl_seconds: int | None = None, namespace: str | None = None
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Coroutine[Any, Any, R]]]: ...


def cached(
    func: Callable[P, Awaitable[R]] | None = None,
    *,
    ttl_seconds: int | None = None,
    namespace: str | None = None,
) -> (
    Callable[P, Coroutine[Any, Any, R]]
    | Callable[[Callable[P, Awaitable[R]]], Callable[P, Coroutine[Any, Any, R]]]
):
    """Cache async function results in diskcache or Redis."""

    def decorator(
        inner: Callable[P, Awaitable[R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        cache_namespace = namespace or f"{inner.__module__}.{inner.__qualname__}"

        @functools.wraps(inner)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            key = make_cache_key(cache_namespace, *_strip_self(args), **kwargs)
            cached_value = await cache_get(key)
            if cached_value is not None:
                return cached_value
            value = await inner(*args, **kwargs)
            await cache_set(key, value, ttl_seconds)
            return value

        return wrapper

    if func is None:
        return decorator
    if not inspect.iscoroutinefunction(func):
        raise TypeError("@cached supports async functions only")
    return decorator(func)


__all__ = [
    "DiskCacheBackend",
    "RedisCacheBackend",
    "cache_get",
    "cache_set",
    "cached",
    "get_cache_backend",
    "make_cache_key",
    "set_cache_backend",
]
