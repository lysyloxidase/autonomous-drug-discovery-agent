"""OpenAlex client.

OpenAlex is used for citation counts, concepts, DOI/PMID/PMCID crosswalks, and
abstract reconstruction from ``abstract_inverted_index``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from adda.cache import cached
from adda.models import Publication
from adda.ratelimit import TokenBucket
from adda.retrieval.base import HTTPRetrievalClient, MissingAPIKeyError
from adda.retrieval.dedupe import compute_canonical_id, normalize_doi


def decode_inverted_index(inverted_index: dict[str, list[int]] | None) -> str:
    """Reconstruct plaintext abstract from an OpenAlex inverted index."""

    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted_index.items():
        for index in indexes:
            positions.append((index, word))
    positions.sort()
    return " ".join(word for _, word in positions)


def _identifier_tail(value: str | None) -> str | None:
    if not value:
        return None
    return value.rstrip("/").rsplit("/", maxsplit=1)[-1]


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _authors(result: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for authorship in result.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if isinstance(author, dict) and isinstance(author.get("display_name"), str):
            names.append(author["display_name"])
    return names


def _primary_source(result: dict[str, Any]) -> str | None:
    primary_location = result.get("primary_location")
    if not isinstance(primary_location, dict):
        return None
    source = primary_location.get("source")
    if isinstance(source, dict) and isinstance(source.get("display_name"), str):
        return source["display_name"]
    return None


def _license(result: dict[str, Any]) -> str | None:
    primary_location = result.get("primary_location")
    if isinstance(primary_location, dict) and isinstance(
        primary_location.get("license"), str
    ):
        return primary_location["license"]
    open_access = result.get("open_access")
    if isinstance(open_access, dict) and isinstance(open_access.get("oa_status"), str):
        return open_access["oa_status"]
    return None


class OpenAlexClient(HTTPRetrievalClient):
    """Client for OpenAlex works search."""

    source_name = "openalex"
    BASE = "https://api.openalex.org"

    def __init__(
        self,
        api_key: str | None,
        rate: TokenBucket | None = None,
        *,
        base_url: str = BASE,
        timeout: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(base_url=base_url, rate=rate, timeout=timeout, client=client)
        self.api_key = api_key

    @cached
    async def retrieve(self, query: str, max_results: int = 200) -> list[Publication]:
        """Search OpenAlex works and normalize results."""

        if not self.api_key:
            raise MissingAPIKeyError("OPENALEX_API_KEY is required for OpenAlex")
        data = await self._get_json(
            "/works",
            params={
                "search": query,
                "per-page": min(max_results, 200),
                "api_key": self.api_key,
            },
        )
        results = data.get("results", [])
        if not isinstance(results, list):
            return []
        publications: list[Publication] = []
        for result in results:
            if isinstance(result, dict):
                publication = self._publication_from_result(result)
                if publication:
                    publications.append(publication)
        return publications[:max_results]

    def _publication_from_result(self, result: dict[str, Any]) -> Publication | None:
        title = result.get("title") or result.get("display_name")
        if not isinstance(title, str) or not title.strip():
            return None
        ids = result.get("ids")
        if not isinstance(ids, dict):
            ids = {}
        raw_doi = result.get("doi")
        raw_pmid = ids.get("pmid")
        raw_pmcid = ids.get("pmcid")
        doi = normalize_doi(raw_doi if isinstance(raw_doi, str) else None)
        pmid = _identifier_tail(raw_pmid if isinstance(raw_pmid, str) else None)
        pmcid = _identifier_tail(raw_pmcid if isinstance(raw_pmcid, str) else None)
        publication_date = _parse_date(
            result.get("publication_date")
            if isinstance(result.get("publication_date"), str)
            else None
        )
        abstract = decode_inverted_index(
            result.get("abstract_inverted_index")
            if isinstance(result.get("abstract_inverted_index"), dict)
            else None
        )
        cited_by_count = result.get("cited_by_count")
        return Publication(
            canonical_id=compute_canonical_id(title, doi=doi, pmid=pmid, pmcid=pmcid),
            pmid=pmid,
            pmcid=pmcid,
            doi=doi,
            title=title.strip(),
            abstract=abstract or None,
            authors=_authors(result),
            journal=_primary_source(result),
            year=result.get("publication_year")
            if isinstance(result.get("publication_year"), int)
            else None,
            publication_date=publication_date,
            citation_count=cited_by_count if isinstance(cited_by_count, int) else None,
            sources=[self.source_name],
            license=_license(result),
        )
