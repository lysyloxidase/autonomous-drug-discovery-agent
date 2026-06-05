from __future__ import annotations

import httpx
import pytest
import respx

from adda.ratelimit import TokenBucket
from adda.retrieval.europepmc import EuropePMCClient
from adda.retrieval.openalex import OpenAlexClient
from adda.retrieval.pubmed import PubMedClient
from adda.retrieval.pubtator3 import PubTator3Client


def fast_bucket() -> TokenBucket:
    return TokenBucket(rate=1_000.0, capacity=1_000)


@pytest.mark.asyncio
@respx.mock
async def test_pubmed_client_returns_records() -> None:
    respx.get("https://pubmed.test/entrez/eutils/esearch.fcgi").mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["38410657"]}},
        )
    )
    respx.get("https://pubmed.test/entrez/eutils/efetch.fcgi").mock(
        return_value=httpx.Response(
            200,
            text="""
            <PubmedArticleSet>
              <PubmedArticle>
                <MedlineCitation>
                  <PMID>38410657</PMID>
                  <Article>
                    <ArticleTitle>PubTator 3.0</ArticleTitle>
                    <Abstract>
                      <AbstractText>Entity annotations.</AbstractText>
                    </Abstract>
                    <Journal><Title>Nucleic Acids Research</Title>
                      <JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue>
                    </Journal>
                    <AuthorList>
                      <Author>
                        <ForeName>Chih-Hsuan</ForeName>
                        <LastName>Wei</LastName>
                      </Author>
                    </AuthorList>
                  </Article>
                  <MeshHeadingList>
                    <MeshHeading>
                      <DescriptorName>Text Mining</DescriptorName>
                    </MeshHeading>
                  </MeshHeadingList>
                </MedlineCitation>
                <PubmedData>
                  <ArticleIdList>
                    <ArticleId IdType="doi">10.1093/nar/gkae235</ArticleId>
                    <ArticleId IdType="pmc">PMC11223871</ArticleId>
                  </ArticleIdList>
                </PubmedData>
              </PubmedArticle>
            </PubmedArticleSet>
            """,
        )
    )
    client = PubMedClient(base_url="https://pubmed.test", rate=fast_bucket())

    publications = await client.retrieve("glioblastoma")

    assert len(publications) == 1
    assert publications[0].canonical_id == "doi:10.1093/nar/gkae235"
    assert publications[0].pmid == "38410657"
    assert publications[0].authors == ["Chih-Hsuan Wei"]


@pytest.mark.asyncio
@respx.mock
async def test_europepmc_client_returns_records() -> None:
    respx.get("https://europepmc.test/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "resultList": {
                    "result": [
                        {
                            "pmid": "1",
                            "pmcid": "PMC1",
                            "doi": "10.1000/epmc",
                            "title": "Europe PMC record",
                            "abstractText": "Abstract",
                            "journalTitle": "Journal",
                            "pubYear": "2025",
                            "firstPublicationDate": "2025-01-02",
                            "citedByCount": 7,
                            "authorList": {"author": [{"fullName": "Ada Lovelace"}]},
                            "meshHeadingList": {
                                "meshHeading": [{"descriptorName": "Glioblastoma"}]
                            },
                            "license": "cc-by",
                        }
                    ]
                }
            },
        )
    )
    client = EuropePMCClient(base_url="https://europepmc.test", rate=fast_bucket())

    publications = await client.retrieve("glioblastoma")

    assert len(publications) == 1
    assert publications[0].doi == "10.1000/epmc"
    assert publications[0].citation_count == 7
    assert publications[0].license == "cc-by"


@pytest.mark.asyncio
@respx.mock
async def test_openalex_client_returns_records() -> None:
    respx.get("https://openalex.test/works").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "OpenAlex record",
                        "doi": "https://doi.org/10.1000/openalex",
                        "ids": {
                            "pmid": "https://pubmed.ncbi.nlm.nih.gov/2",
                            "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2",
                        },
                        "abstract_inverted_index": {
                            "Gene": [0],
                            "targets": [1],
                            "matter.": [2],
                        },
                        "authorships": [
                            {"author": {"display_name": "Rosalind Franklin"}}
                        ],
                        "primary_location": {
                            "source": {"display_name": "Nature"},
                            "license": "cc-by",
                        },
                        "publication_year": 2026,
                        "publication_date": "2026-01-01",
                        "cited_by_count": 13,
                    }
                ]
            },
        )
    )
    client = OpenAlexClient(
        api_key="test-key",
        base_url="https://openalex.test",
        rate=fast_bucket(),
    )

    publications = await client.retrieve("glioblastoma")

    assert len(publications) == 1
    assert publications[0].abstract == "Gene targets matter."
    assert publications[0].pmid == "2"
    assert publications[0].pmcid == "PMC2"
    assert publications[0].citation_count == 13


@pytest.mark.asyncio
@respx.mock
async def test_pubtator3_client_returns_records_and_relations() -> None:
    respx.get("https://pubtator.test/search/").mock(
        return_value=httpx.Response(200, json={"results": [{"pmid": "3"}]})
    )
    respx.get("https://pubtator.test/publications/export/biocjson").mock(
        return_value=httpx.Response(
            200,
            json={
                "documents": [
                    {
                        "id": "3",
                        "infons": {
                            "article-id_pmid": "3",
                            "article-id_doi": "10.1000/pubtator",
                        },
                        "passages": [
                            {"infons": {"type": "title"}, "text": "PubTator record"},
                            {
                                "infons": {"type": "abstract"},
                                "text": "Annotated abstract.",
                            },
                        ],
                    }
                ]
            },
        )
    )
    respx.get("https://pubtator.test/relations").mock(
        return_value=httpx.Response(200, json={"relations": [{"type": "treat"}]})
    )
    client = PubTator3Client(base_url="https://pubtator.test", rate=fast_bucket())

    publications = await client.retrieve("glioblastoma")
    relations = await client.relations("@GENE_X", "treat", "@DISEASE_Y")

    assert len(publications) == 1
    assert publications[0].canonical_id == "doi:10.1000/pubtator"
    assert publications[0].abstract == "Annotated abstract."
    assert relations == [{"type": "treat"}]
