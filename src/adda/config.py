"""Application settings loaded from environment and YAML config files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CacheSettings(BaseSettings):
    """Cache backend settings."""

    backend: str = "disk"
    directory: Path = Path(".cache/adda")
    redis_url: str | None = None
    ttl_seconds: int = 86_400


class SourceSettings(BaseSettings):
    """Per-source HTTP settings."""

    base_url: str
    requests_per_second: float
    burst: int = 1
    timeout_seconds: float = 20.0


class Settings(BaseSettings):
    """Top-level runtime settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    ncbi_api_key: str | None = Field(default=None, validation_alias="NCBI_API_KEY")
    openalex_api_key: str | None = Field(
        default=None, validation_alias="OPENALEX_API_KEY"
    )
    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    cache: CacheSettings = Field(default_factory=CacheSettings)
    sources: dict[str, SourceSettings] = Field(default_factory=dict)


DEFAULT_SOURCES: dict[str, SourceSettings] = {
    "pubmed": SourceSettings(
        base_url="https://eutils.ncbi.nlm.nih.gov",
        requests_per_second=3.0,
        burst=3,
    ),
    "europepmc": SourceSettings(
        base_url="https://www.ebi.ac.uk/europepmc/webservices/rest",
        requests_per_second=10.0,
        burst=10,
    ),
    "openalex": SourceSettings(
        base_url="https://api.openalex.org",
        requests_per_second=5.0,
        burst=5,
    ),
    "pubtator3": SourceSettings(
        base_url="https://www.ncbi.nlm.nih.gov/research/pubtator3-api",
        requests_per_second=3.0,
        burst=3,
    ),
}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML config must be a mapping: {path}")
    return data


def _source_settings_from_yaml(raw: dict[str, Any]) -> dict[str, SourceSettings]:
    sources: dict[str, SourceSettings] = dict(DEFAULT_SOURCES)
    for name, values in raw.items():
        if not isinstance(values, dict):
            raise ValueError(f"Source config for {name!r} must be a mapping")
        base = sources.get(name)
        merged = base.model_dump() if base else {}
        merged.update(values)
        sources[name] = SourceSettings(**merged)
    return sources


def load_settings(
    config_path: str | Path = "configs/config.yaml",
    sources_path: str | Path = "configs/sources.yaml",
) -> Settings:
    """Load settings from YAML files plus environment overrides."""

    config_data = _read_yaml(Path(config_path))
    sources_data = _read_yaml(Path(sources_path))
    cache_data = config_data.get("cache", {})
    if not isinstance(cache_data, dict):
        raise ValueError("cache config must be a mapping")

    settings = Settings(
        cache=CacheSettings(**cache_data),
        sources=_source_settings_from_yaml(sources_data),
    )
    if settings.redis_url and not settings.cache.redis_url:
        settings.cache.redis_url = settings.redis_url
    if settings.ncbi_api_key:
        pubmed = settings.sources["pubmed"]
        settings.sources["pubmed"] = pubmed.model_copy(
            update={"requests_per_second": 10.0, "burst": max(pubmed.burst, 10)}
        )
    return settings
