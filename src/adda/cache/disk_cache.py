"""Disk-backed cache adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from diskcache import Cache


class DiskCacheBackend:
    """Small wrapper around diskcache with a uniform get/set API."""

    def __init__(self, directory: str | Path = ".cache/adda") -> None:
        self.directory = Path(directory)
        self._cache = Cache(str(self.directory))

    def get(self, key: str) -> Any | None:
        return self._cache.get(key)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        self._cache.set(key, value, expire=ttl_seconds)

    def clear(self) -> None:
        self._cache.clear()

    def close(self) -> None:
        self._cache.close()
