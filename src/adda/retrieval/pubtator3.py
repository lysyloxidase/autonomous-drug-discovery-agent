"""PubTator3 client.

PubTator3 provides PubMed and PMC entity annotations plus BioC-JSON export.
The raw annotations become authoritative entity evidence in later phases.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx

from adda.cache import cached
from adda.models import Publication
from adda.ratelimit import TokenBucket
from adda.retrieval.base import HTTPRetrievalClient
from adda.retrieval.dedupe import compute_canonical_id, normalize_doi


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _extract_pmids(data: Any) -> list[str]:
    if isinstance(data, list):
        return [str(item) for item in data if str(item).isdigit()]
    if not isinstance(data, dict):
        return []
    for key in ("pmids", "pmid", "ids"):
        value = data.get(key)
        if isinstance(value, list):
            return [str(item) for item in value if str(item).isdigit()]
        if isinstance(value, str):
            return [item for item in value.replace(",", " ").split() if item.isdigit()]
    results = data.get("results") or data.get("publications") or []
    pmids: list[str] = []
    if isinstance(results, list):
        for item in results:
            if isinstance(item, str) and item.isdigit():
                pmids.append(item)
            elif isinstance(item, dict):
                for key in ("pmid", "pmid_str", "id"):
                    value = item.get(key)
                    if isinstance(value, str) and value.isdigit():
                        pmids.append(value)
                        break
                    if isinstance(value, int):
                        pmids.append(str(value))
                        break
    return pmids


def _passage_type(passage: dict[str, Any]) -> str:
    infons = passage.get("infons")
    if isinstance(infons, dict):
        for key in ("type", "section_type", "section"):
            value = infons.get(key)
            if isinstance(value, str):
                return value.lower()
    return ""


def _passage_texts(
    document: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    title: str | None = None
    abstract_parts: list[str] = []
    full_text_parts: list[str] = []
    passages = document.get("passages")
    if not isinstance(passages, list):
        return title, None, None
    for passage in passages:
        if not isinstance(passage, dict) or not isinstance(passage.get("text"), str):
            continue
        text = passage["text"].strip()
        if not text:
            continue
        section = _passage_type(passage)
        if "title" in section and title is None:
            title = text
        elif "abstract" in section:
            abstract_parts.append(text)
        else:
            full_text_parts.append(text)
    return (
        title,
        " ".join(abstract_parts) or None,
        " ".join(full_text_parts) or None,
    )


def _infons(document: dict[str, Any]) -> dict[str, Any]:
    value = document.get("infons")
    return value if isinstance(value, dict) else {}


class PubTator3Client(HTTPRetrievalClient):
    """Client for PubTator3 search, BioC-JSON export, and relations."""

    source_name = "pubtator3"
    BASE = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"

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
    async def search(self, query: str, max_results: int = 200) -> list[str]:
        """Search PubTator3 and return PMIDs."""

        data = await self._get_json(
            "/search/",
            params={"text": query, "page_size": max_results},
        )
        return _extract_pmids(data)[:max_results]

    @cached
    async def export_biocjson(self, pmids: list[str]) -> dict[str, Any]:
        """Export publications as BioC JSON by PMID."""

        if not pmids:
            return {"documents": []}
        return await self._get_json(
            "/publications/export/biocjson",
            params={"pmids": ",".join(pmids)},
        )

    @cached
    async def relations(self, e1: str, rel_type: str, e2: str) -> list[dict[str, Any]]:
        """Return PubTator3 relation records for two entities."""

        data = await self._get_json(
            "/relations",
            params={"e1": e1, "type": rel_type, "e2": e2},
        )
        relations = data.get("relations") or data.get("results") or []
        if not isinstance(relations, list):
            return []
        return [item for item in relations if isinstance(item, dict)]

    @cached
    async def retrieve(self, query: str, max_results: int = 200) -> list[Publication]:
        """Search PubTator3 and return normalized publications."""

        pmids = await self.search(query, max_results=max_results)
        publications: list[Publication] = []
        for chunk in _chunks(pmids, 100):
            data = await self.export_biocjson(chunk)
            publications.extend(self._publications_from_biocjson(data))
        return publications[:max_results]

    def _publications_from_biocjson(self, data: dict[str, Any]) -> list[Publication]:
        documents = data.get("documents")
        if not isinstance(documents, list):
            return []
        publications: list[Publication] = []
        for document in documents:
            if not isinstance(document, dict):
                continue
            publication = self._publication_from_document(document)
            if publication:
                publications.append(publication)
        return publications

    def _publication_from_document(
        self,
        document: dict[str, Any],
    ) -> Publication | None:
        infons = _infons(document)
        title, abstract, full_text = _passage_texts(document)
        pmid = str(infons.get("article-id_pmid") or document.get("id") or "")
        pmid = pmid if pmid.isdigit() else None
        pmcid_value = infons.get("article-id_pmc")
        pmcid = pmcid_value if isinstance(pmcid_value, str) else None
        doi_value = infons.get("article-id_doi") or infons.get("doi")
        doi = normalize_doi(doi_value if isinstance(doi_value, str) else None)
        if not title:
            fallback = abstract or full_text
            title = fallback[:160] if fallback else None
        if not title:
            return None
        return Publication(
            canonical_id=compute_canonical_id(title, doi=doi, pmid=pmid, pmcid=pmcid),
            pmid=pmid,
            pmcid=pmcid,
            doi=doi,
            title=title,
            abstract=abstract,
            full_text=full_text,
            sources=[self.source_name],
        )
