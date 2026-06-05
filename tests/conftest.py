from __future__ import annotations

from collections.abc import Iterator

import pytest

from adda.cache import DiskCacheBackend, set_cache_backend


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path) -> Iterator[None]:  # type: ignore[no-untyped-def]
    backend = DiskCacheBackend(tmp_path / "cache")
    set_cache_backend(backend)
    try:
        yield
    finally:
        backend.clear()
        backend.close()
        set_cache_backend(None)
