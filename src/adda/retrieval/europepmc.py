"""Europe PMC REST client."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any

import httpx

from adda.cache import cached
from adda.models import Publication
from adda.ratelimit import TokenBucket
from adda.retrieval.base import HTTPRetrievalClient
from adda.retrieval.dedupe import compute_canonical_id, normalize_doi

_TAG_RE = re.compile(r"<[^>]+>")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _year(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value[:4].isdigit():
        return int(value[:4])
    return None


def _authors(record: dict[str, Any]) -> list[str]:
    author_list = record.get("authorList")
    if isinstance(author_list, dict):
        authors = author_list.get("author")
        if isinstance(authors, list):
            names = [
                author.get("fullName")
                for author in authors
                if isinstance(author, dict) and isinstance(author.get("fullName"), str)
            ]
            return [name for name in names if name]
    author_string = record.get("authorString")
    if isinstance(author_string, str):
        return [name.strip() for name in author_string.split(",") if name.strip()]
    return []


def _mesh_terms(record: dict[str, Any]) -> list[str]:
    mesh_heading_list = record.get("meshHeadingList")
    if not isinstance(mesh_heading_list, dict):
        return []
    headings = mesh_heading_list.get("meshHeading")
    if not isinstance(headings, list):
        return []
    terms: list[str] = []
    for heading in headings:
        if isinstance(heading, dict) and isinstance(heading.get("descriptorName"), str):
            terms.append(heading["descriptorName"])
    return terms


class EuropePMCClient(HTTPRetrievalClient):
    """Client for Europe PMC search and full-text XML retrieval."""

    source_name = "europepmc"
    BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    def __init__(
        self,
        rate: TokenBucket | None = None,
        *,
        base_url: str = BASE,
        timeout: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(base_url=base_url, rate=rate, timeout=timeout, client=client)

    @cached
    async def retrieve(self, query: str, max_results: int = 200) -> list[Publication]:
        """Search Europe PMC records and normalize them."""

        data = await self._get_json(
            "/search",
            params={
                "query": query,
                "format": "json",
                "resultType": "core",
                "pageSize": min(max_results, 1000),
            },
        )
        result_list = data.get("resultList")
        results = result_list.get("result") if isinstance(result_list, dict) else []
        if not isinstance(results, list):
            return []
        publications = [
            publication
            for record in results
            if isinstance(record, dict)
            if (publication := self._publication_from_record(record)) is not None
        ]
        return publications[:max_results]

    @cached
    async def full_text(self, pmcid: str) -> str | None:
        """Fetch and flatten Europe PMC fullTextXML for a PMCID."""

        xml = await self._get_text(f"/{pmcid}/fullTextXML")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return None
        text = " ".join(part.strip() for part in root.itertext() if part.strip())
        return _TAG_RE.sub(" ", text).strip() or None

    def _publication_from_record(self, record: dict[str, Any]) -> Publication | None:
        title = record.get("title")
        if not isinstance(title, str) or not title.strip():
            return None
        pmid = record.get("pmid") if isinstance(record.get("pmid"), str) else None
        pmcid = record.get("pmcid") if isinstance(record.get("pmcid"), str) else None
        raw_doi = record.get("doi")
        doi = normalize_doi(raw_doi if isinstance(raw_doi, str) else None)
        cited_by_count = record.get("citedByCount")
        pub_type = record.get("pubType")
        raw_license = record.get("license")
        return Publication(
            canonical_id=compute_canonical_id(title, doi=doi, pmid=pmid, pmcid=pmcid),
            pmid=pmid,
            pmcid=pmcid,
            doi=doi,
            title=title.strip(),
            abstract=record.get("abstractText")
            if isinstance(record.get("abstractText"), str)
            else None,
            authors=_authors(record),
            journal=record.get("journalTitle")
            if isinstance(record.get("journalTitle"), str)
            else None,
            year=_year(record.get("pubYear")),
            publication_date=_parse_date(
                record.get("firstPublicationDate")
                if isinstance(record.get("firstPublicationDate"), str)
                else None
            ),
            citation_count=cited_by_count if isinstance(cited_by_count, int) else None,
            mesh_terms=_mesh_terms(record),
            sources=[self.source_name],
            is_preprint=isinstance(pub_type, str) and "preprint" in pub_type.lower(),
            license=raw_license if isinstance(raw_license, str) else None,
        )
