from __future__ import annotations

from adda.models import Publication
from adda.retrieval.dedupe import canonical_key, dedupe_publications, title_hash


def test_canonical_key_precedence() -> None:
    key = canonical_key(
        doi="HTTPS://DOI.ORG/10.1000/ABC",
        pmid="123",
        pmcid="PMC456",
        title="Example Title",
    )

    assert key == "doi:10.1000/abc"
    assert canonical_key(pmid="123", pmcid="PMC456", title="Example") == "pmid:123"
    assert canonical_key(pmcid="456", title="Example") == "pmcid:PMC456"
    assert canonical_key(title="Example, title!") == (
        f"title:{title_hash('Example title')}"
    )


def test_dedupe_merges_same_paper_from_three_sources() -> None:
    records = [
        Publication(
            canonical_id="doi:10.1000/example",
            doi="10.1000/example",
            pmid="111",
            title="Target discovery in glioblastoma",
            abstract="PubMed abstract",
            sources=["pubmed"],
            mesh_terms=["Glioblastoma"],
        ),
        Publication(
            canonical_id="pmid:111",
            pmid="111",
            pmcid="PMC111",
            title="Target discovery in glioblastoma",
            full_text="Europe PMC full text",
            sources=["europepmc"],
        ),
        Publication(
            canonical_id="doi:10.1000/example",
            doi="https://doi.org/10.1000/example",
            pmcid="PMC111",
            title="Target discovery in glioblastoma",
            citation_count=42,
            sources=["openalex"],
        ),
    ]

    merged = dedupe_publications(records)

    assert len(merged) == 1
    publication = merged[0]
    assert publication.canonical_id == "doi:10.1000/example"
    assert publication.sources == ["pubmed", "europepmc", "openalex"]
    assert publication.full_text == "Europe PMC full text"
    assert publication.citation_count == 42
    assert publication.mesh_terms == ["Glioblastoma"]
