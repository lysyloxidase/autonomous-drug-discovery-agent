"""Async token bucket and transient HTTP retry helpers."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

import httpx
from tenacity import (
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.asyncio import AsyncRetrying

P = ParamSpec("P")
R = TypeVar("R")

TRANSIENT_STATUS_CODES = {429, 503}


class TokenBucket:
    """Per-source async token bucket.

    A custom clock and sleeper can be injected for deterministic tests.
    """

    def __init__(
        self,
        rate: float,
        capacity: int | None = None,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = rate
        self.capacity = float(capacity or max(1, int(rate)))
        self._tokens = self.capacity
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._updated_at = self._clock()
        self._lock = asyncio.Lock()

    @property
    def tokens(self) -> float:
        """Current available token count, after refilling."""

        self._refill()
        return self._tokens

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._updated_at)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._updated_at = now

    async def acquire(self, tokens: int = 1) -> None:
        """Wait until the requested number of tokens is available."""

        if tokens <= 0:
            raise ValueError("tokens must be positive")
        if tokens > self.capacity:
            raise ValueError("tokens cannot exceed bucket capacity")

        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                await self._sleep(deficit / self.rate)


def is_retryable_http_error(exc: BaseException) -> bool:
    """Return true for transient network errors and 429/503 responses."""

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in TRANSIENT_STATUS_CODES
    return isinstance(
        exc,
        (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError),
    )


def retry_transient(
    *,
    attempts: int = 3,
    min_seconds: float = 1.0,
    max_seconds: float = 30.0,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorate an async function with exponential backoff for transient errors."""

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            retrying = AsyncRetrying(
                retry=retry_if_exception(is_retryable_http_error),
                stop=stop_after_attempt(attempts),
                wait=wait_exponential(multiplier=min_seconds, max=max_seconds),
                reraise=True,
            )
            async for attempt in retrying:
                with attempt:
                    return await func(*args, **kwargs)
            raise RuntimeError("retry loop exhausted without returning")

        return wrapper

    return decorator
