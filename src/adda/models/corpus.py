"""Canonical publication and corpus models."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class Publication(BaseModel):
    """A normalized literature record from any retrieval source."""

    model_config = ConfigDict(validate_assignment=True)

    canonical_id: str
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    title: str
    abstract: str | None = None
    full_text: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    year: int | None = None
    publication_date: date | None = None
    citation_count: int | None = None
    mesh_terms: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    is_preprint: bool = False
    license: str | None = None


class Corpus(BaseModel):
    """A deduplicated corpus returned for a disease query."""

    disease_query: str
    publications: list[Publication]
    per_source_counts: dict[str, int]
    retrieved_at: str
    cache_hit: bool = False
