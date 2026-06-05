"""DOI/PMID/PMCID crosswalk plus title-hash fallback."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable

from adda.models import Publication

_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def normalize_doi(doi: str | None) -> str | None:
    """Normalize a DOI for dedupe."""

    if not doi:
        return None
    value = doi.strip().lower()
    value = value.removeprefix("https://doi.org/")
    value = value.removeprefix("http://doi.org/")
    value = value.removeprefix("doi:")
    return value or None


def normalize_pmid(pmid: str | None) -> str | None:
    """Normalize a PMID to its numeric string."""

    if not pmid:
        return None
    value = pmid.strip()
    value = value.removeprefix("https://pubmed.ncbi.nlm.nih.gov/")
    value = value.rstrip("/")
    return value or None


def normalize_pmcid(pmcid: str | None) -> str | None:
    """Normalize PMCID to an uppercase PMC-prefixed identifier."""

    if not pmcid:
        return None
    value = pmcid.strip()
    value = value.removeprefix("https://www.ncbi.nlm.nih.gov/pmc/articles/")
    value = value.rstrip("/")
    if value and not value.upper().startswith("PMC"):
        value = f"PMC{value}"
    return value.upper() or None


def normalize_title(title: str) -> str:
    """Normalize title text for fallback hashing."""

    lowered = title.strip().lower()
    without_punct = _PUNCT_RE.sub(" ", lowered)
    return _SPACE_RE.sub(" ", without_punct).strip()


def title_hash(title: str) -> str:
    """Return the SHA1 hash of a normalized title."""

    normalized = normalize_title(title)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def canonical_key(
    *,
    doi: str | None = None,
    pmid: str | None = None,
    pmcid: str | None = None,
    title: str | None = None,
) -> str:
    """Return canonical key with DOI > PMID > PMCID > title hash precedence."""

    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        return f"doi:{normalized_doi}"
    normalized_pmid = normalize_pmid(pmid)
    if normalized_pmid:
        return f"pmid:{normalized_pmid}"
    normalized_pmcid = normalize_pmcid(pmcid)
    if normalized_pmcid:
        return f"pmcid:{normalized_pmcid}"
    if title:
        return f"title:{title_hash(title)}"
    raise ValueError("Cannot compute canonical key without DOI, PMID, PMCID, or title")


def identifier_keys(publication: Publication) -> set[str]:
    """Return every dedupe key carried by a publication."""

    keys = {
        canonical_key(
            doi=publication.doi,
            pmid=publication.pmid,
            pmcid=publication.pmcid,
            title=publication.title,
        )
    }
    if publication.doi:
        keys.add(f"doi:{normalize_doi(publication.doi)}")
    if publication.pmid:
        keys.add(f"pmid:{normalize_pmid(publication.pmid)}")
    if publication.pmcid:
        keys.add(f"pmcid:{normalize_pmcid(publication.pmcid)}")
    if publication.title:
        keys.add(f"title:{title_hash(publication.title)}")
    return {key for key in keys if not key.endswith(":None")}


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        if item not in self.parent:
            self.parent[item] = item
            return item
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _preferred_key(keys: Iterable[str]) -> str:
    precedence = {"doi": 0, "pmid": 1, "pmcid": 2, "title": 3}
    return sorted(keys, key=lambda key: (precedence[key.split(":", 1)[0]], key))[0]


def _dedupe_list(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            result.append(cleaned)
    return result


def _first_non_empty(values: Iterable[str | None]) -> str | None:
    for value in values:
        if value:
            return value
    return None


def _merge_group(publications: list[Publication], canonical_id: str) -> Publication:
    ordered = sorted(
        publications,
        key=lambda pub: (
            pub.full_text is None,
            pub.abstract is None,
            pub.citation_count is None,
            len(pub.sources),
        ),
    )
    primary = ordered[0]
    citation_counts = [
        pub.citation_count for pub in publications if pub.citation_count is not None
    ]
    return Publication(
        canonical_id=canonical_id,
        pmid=_first_non_empty(pub.pmid for pub in publications),
        pmcid=_first_non_empty(pub.pmcid for pub in publications),
        doi=_first_non_empty(pub.doi for pub in publications),
        title=_first_non_empty(pub.title for pub in publications) or primary.title,
        abstract=_first_non_empty(pub.abstract for pub in ordered),
        full_text=_first_non_empty(pub.full_text for pub in ordered),
        authors=_dedupe_list(author for pub in publications for author in pub.authors),
        journal=_first_non_empty(pub.journal for pub in publications),
        year=next((pub.year for pub in publications if pub.year is not None), None),
        publication_date=next(
            (pub.publication_date for pub in publications if pub.publication_date),
            None,
        ),
        citation_count=max(citation_counts) if citation_counts else None,
        mesh_terms=_dedupe_list(
            term for pub in publications for term in pub.mesh_terms
        ),
        sources=_dedupe_list(source for pub in publications for source in pub.sources),
        is_preprint=any(pub.is_preprint for pub in publications),
        license=_first_non_empty(pub.license for pub in publications),
    )


def dedupe_publications(publications: Iterable[Publication]) -> list[Publication]:
    """Merge duplicate publications using identifier union plus title hash."""

    publication_list = list(publications)
    if not publication_list:
        return []

    union_find = _UnionFind()
    keys_by_publication: dict[int, set[str]] = {}
    for index, publication in enumerate(publication_list):
        keys = identifier_keys(publication)
        keys_by_publication[index] = keys
        primary_key = canonical_key(
            doi=publication.doi,
            pmid=publication.pmid,
            pmcid=publication.pmcid,
            title=publication.title,
        )
        union_find.find(primary_key)
        for key in keys:
            union_find.union(primary_key, key)

    grouped_indexes: dict[str, list[int]] = defaultdict(list)
    for index, keys in keys_by_publication.items():
        grouped_indexes[union_find.find(_preferred_key(keys))].append(index)

    merged: list[Publication] = []
    for indexes in grouped_indexes.values():
        group = [publication_list[index] for index in indexes]
        group_keys = set().union(
            *(identifier_keys(publication) for publication in group)
        )
        merged.append(_merge_group(group, _preferred_key(group_keys)))
    return sorted(merged, key=lambda publication: publication.canonical_id)


def compute_canonical_id(
    title: str,
    *,
    doi: str | None = None,
    pmid: str | None = None,
    pmcid: str | None = None,
) -> str:
    """Convenience wrapper for client normalizers."""

    return canonical_key(doi=doi, pmid=pmid, pmcid=pmcid, title=title)
