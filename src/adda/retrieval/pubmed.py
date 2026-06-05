"""PubMed E-utilities client."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from typing import Any

import httpx

from adda.cache import cached
from adda.models import Publication
from adda.ratelimit import TokenBucket
from adda.retrieval.base import HTTPRetrievalClient
from adda.retrieval.dedupe import compute_canonical_id, normalize_doi

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = " ".join(part.strip() for part in element.itertext() if part.strip())
    return value or None


def _date_from_article(article: ET.Element) -> date | None:
    article_date = article.find(".//ArticleDate")
    year = _text(article_date.find("Year")) if article_date is not None else None
    month = _text(article_date.find("Month")) if article_date is not None else None
    day = _text(article_date.find("Day")) if article_date is not None else None
    if not year:
        pub_date = article.find(".//JournalIssue/PubDate")
        year = _text(pub_date.find("Year")) if pub_date is not None else None
        month = _text(pub_date.find("Month")) if pub_date is not None else None
        day = _text(pub_date.find("Day")) if pub_date is not None else None
    if not year or not year.isdigit():
        return None
    month_number = 1
    if month:
        month_number = (
            int(month) if month.isdigit() else _MONTHS.get(month[:3].lower(), 1)
        )
    day_number = int(day) if day and day.isdigit() else 1
    try:
        return date(int(year), month_number, day_number)
    except ValueError:
        return None


def _year_from_date(publication_date: date | None, article: ET.Element) -> int | None:
    if publication_date:
        return publication_date.year
    year = _text(article.find(".//JournalIssue/PubDate/Year"))
    return int(year) if year and year.isdigit() else None


def _authors(article: ET.Element) -> list[str]:
    names: list[str] = []
    for author in article.findall(".//AuthorList/Author"):
        collective = _text(author.find("CollectiveName"))
        if collective:
            names.append(collective)
            continue
        first = _text(author.find("ForeName"))
        last = _text(author.find("LastName"))
        if first and last:
            names.append(f"{first} {last}")
        elif last:
            names.append(last)
    return names


def _article_ids(article: ET.Element) -> tuple[str | None, str | None]:
    doi: str | None = None
    pmcid: str | None = None
    for article_id in article.findall(".//ArticleIdList/ArticleId"):
        id_type = article_id.attrib.get("IdType")
        value = _text(article_id)
        if id_type == "doi" and value:
            doi = normalize_doi(value)
        elif id_type == "pmc" and value:
            pmcid = value
    return doi, pmcid


def _mesh_terms(article: ET.Element) -> list[str]:
    descriptors = article.findall(".//MeshHeadingList/MeshHeading/DescriptorName")
    return [term for descriptor in descriptors if (term := _text(descriptor))]


class PubMedClient(HTTPRetrievalClient):
    """Client for PubMed E-utilities search and fetch."""

    source_name = "pubmed"
    BASE = "https://eutils.ncbi.nlm.nih.gov"

    def __init__(
        self,
        api_key: str | None = None,
        rate: TokenBucket | None = None,
        *,
        base_url: str = BASE,
        timeout: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(base_url=base_url, rate=rate, timeout=timeout, client=client)
        self.api_key = api_key

    @cached
    async def search_pmids(self, query: str, max_results: int = 200) -> list[str]:
        """Return PMIDs from PubMed esearch."""

        params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": max_results,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        data = await self._get_json("/entrez/eutils/esearch.fcgi", params=params)
        result = data.get("esearchresult")
        id_list = result.get("idlist") if isinstance(result, dict) else []
        return [str(pmid) for pmid in id_list] if isinstance(id_list, list) else []

    @cached
    async def fetch_details(self, pmids: list[str]) -> list[Publication]:
        """Fetch MEDLINE XML details for PMIDs."""

        if not pmids:
            return []
        params: dict[str, Any] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        if self.api_key:
            params["api_key"] = self.api_key
        xml = await self._get_text("/entrez/eutils/efetch.fcgi", params=params)
        return self._parse_publications(xml)

    @cached
    async def retrieve(self, query: str, max_results: int = 200) -> list[Publication]:
        """Search PubMed and return normalized publications."""

        pmids = await self.search_pmids(query, max_results=max_results)
        return await self.fetch_details(pmids)

    def _parse_publications(self, xml: str) -> list[Publication]:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return []
        publications: list[Publication] = []
        for article in root.findall(".//PubmedArticle"):
            publication = self._publication_from_article(article)
            if publication:
                publications.append(publication)
        return publications

    def _publication_from_article(self, article: ET.Element) -> Publication | None:
        pmid = _text(article.find(".//MedlineCitation/PMID"))
        title = _text(article.find(".//Article/ArticleTitle"))
        if not title:
            return None
        abstract_parts = [
            text
            for abstract_text in article.findall(".//Article/Abstract/AbstractText")
            if (text := _text(abstract_text))
        ]
        doi, pmcid = _article_ids(article)
        publication_date = _date_from_article(article)
        return Publication(
            canonical_id=compute_canonical_id(title, doi=doi, pmid=pmid, pmcid=pmcid),
            pmid=pmid,
            pmcid=pmcid,
            doi=doi,
            title=title,
            abstract=" ".join(abstract_parts) if abstract_parts else None,
            authors=_authors(article),
            journal=_text(article.find(".//Journal/Title")),
            year=_year_from_date(publication_date, article),
            publication_date=publication_date,
            mesh_terms=_mesh_terms(article),
            sources=[self.source_name],
        )
