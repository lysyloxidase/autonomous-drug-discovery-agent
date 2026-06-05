from __future__ import annotations

import httpx
import pytest

from adda.ratelimit import TokenBucket
from adda.ratelimit.token_bucket import retry_transient


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.mark.asyncio
async def test_token_bucket_enforces_rate_with_fake_clock() -> None:
    clock = FakeClock()
    bucket = TokenBucket(rate=2.0, capacity=2, clock=clock, sleep=clock.sleep)

    await bucket.acquire()
    await bucket.acquire()
    await bucket.acquire()

    assert clock.sleeps == [0.5]
    assert clock.now == 0.5


@pytest.mark.asyncio
async def test_retry_transient_retries_503() -> None:
    calls = 0

    @retry_transient(attempts=3, min_seconds=0, max_seconds=0)
    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            request = httpx.Request("GET", "https://example.test")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError(
                "unavailable",
                request=request,
                response=response,
            )
        return "ok"

    assert await flaky() == "ok"
    assert calls == 3
