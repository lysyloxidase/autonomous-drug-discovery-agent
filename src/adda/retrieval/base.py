"""Base retrieval client contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Coroutine
from typing import Any

import httpx

from adda.models import Publication
from adda.ratelimit import TokenBucket, retry_transient


class RetrievalError(RuntimeError):
    """Base retrieval failure."""


class MissingAPIKeyError(RetrievalError):
    """Raised when a source requires a configured API key."""


class RetrievalClient(ABC):
    """Abstract retrieval client."""

    source_name: str

    @abstractmethod
    def retrieve(
        self,
        query: str,
        max_results: int = 200,
    ) -> Coroutine[Any, Any, list[Publication]]:
        """Return normalized publications for a disease query."""


class HTTPRetrievalClient(RetrievalClient):
    """Shared HTTP behavior for source clients."""

    source_name = "unknown"

    def __init__(
        self,
        *,
        base_url: str,
        rate: TokenBucket | None = None,
        timeout: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.rate = rate or TokenBucket(rate=1.0, capacity=1)
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this object created it."""

        if self._owns_client:
            await self._client.aclose()

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    @retry_transient()
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        await self.rate.acquire()
        response = await self._client.request(
            method,
            self._url(path),
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._request("GET", path, params=params)
        data = response.json()
        if not isinstance(data, dict):
            raise RetrievalError(f"{self.source_name} returned non-object JSON")
        return data

    async def _get_text(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> str:
        response = await self._request("GET", path, params=params)
        return response.text
