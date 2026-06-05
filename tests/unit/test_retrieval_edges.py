# pyright: reportPrivateUsage=false

from __future__ import annotations

import httpx
import pytest
import respx

from adda.ratelimit import TokenBucket
from adda.retrieval.base import MissingAPIKeyError
from adda.retrieval.europepmc import EuropePMCClient
from adda.retrieval.openalex import OpenAlexClient
from adda.retrieval.pubmed import PubMedClient
from adda.retrieval.pubtator3 import PubTator3Client, _extract_pmids


def fast_bucket() -> TokenBucket:
    return TokenBucket(rate=1_000.0, capacity=1_000)


@pytest.mark.asyncio
async def test_openalex_requires_api_key() -> None:
    client = OpenAlexClient(api_key=None, rate=fast_bucket())

    with pytest.raises(MissingAPIKeyError):
        await client.retrieve("glioblastoma")


@pytest.mark.asyncio
@respx.mock
async def test_openalex_skips_untitled_and_uses_oa_status_license() -> None:
    respx.get("https://openalex-edge.test/works").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"doi": "10.1000/missing-title"},
                    {
                        "display_name": "Displayed title",
                        "ids": "not-a-dict",
                        "publication_date": "not-a-date",
                        "open_access": {"oa_status": "green"},
                    },
                ]
            },
        )
    )
    client = OpenAlexClient(
        api_key="test-key",
        base_url="https://openalex-edge.test",
        rate=fast_bucket(),
    )

    publications = await client.retrieve("glioblastoma")

    assert len(publications) == 1
    assert publications[0].title == "Displayed title"
    assert publications[0].publication_date is None
    assert publications[0].license == "green"


@pytest.mark.asyncio
@respx.mock
async def test_europepmc_full_text_and_fallback_author_string() -> None:
    respx.get("https://europepmc-edge.test/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "resultList": {
                    "result": [
                        {
                            "pmid": "10",
                            "title": "Preprint record",
                            "authorString": "Curie M, Meitner L",
                            "pubType": "preprint",
                        },
                        {"pmid": "11"},
                    ]
                }
            },
        )
    )
    respx.get("https://europepmc-edge.test/PMC10/fullTextXML").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<article><body><p>First paragraph.</p><p>Second.</p></body></article>"
            ),
        )
    )
    client = EuropePMCClient(
        base_url="https://europepmc-edge.test",
        rate=fast_bucket(),
    )

    publications = await client.retrieve("glioblastoma")
    full_text = await client.full_text("PMC10")

    assert len(publications) == 1
    assert publications[0].authors == ["Curie M", "Meitner L"]
    assert publications[0].is_preprint is True
    assert full_text == "First paragraph. Second."


@pytest.mark.asyncio
@respx.mock
async def test_europepmc_bad_full_text_xml_returns_none() -> None:
    respx.get("https://europepmc-edge.test/PMC10/fullTextXML").mock(
        return_value=httpx.Response(200, text="<article>")
    )
    client = EuropePMCClient(
        base_url="https://europepmc-edge.test",
        rate=fast_bucket(),
    )

    assert await client.full_text("PMC10") is None


def test_pubmed_parser_handles_malformed_xml_and_collective_author() -> None:
    client = PubMedClient(rate=fast_bucket())
    assert client._parse_publications("<bad") == []

    publications = client._parse_publications(
        """
        <PubmedArticleSet>
          <PubmedArticle>
            <MedlineCitation>
              <PMID>99</PMID>
              <Article>
                <ArticleTitle>Collective record</ArticleTitle>
                <ArticleDate>
                  <Year>2024</Year><Month>Feb</Month><Day>03</Day>
                </ArticleDate>
                <AuthorList>
                  <Author><CollectiveName>Consortium</CollectiveName></Author>
                </AuthorList>
              </Article>
            </MedlineCitation>
          </PubmedArticle>
          <PubmedArticle>
            <MedlineCitation><PMID>100</PMID><Article /></MedlineCitation>
          </PubmedArticle>
        </PubmedArticleSet>
        """
    )

    assert len(publications) == 1
    assert publications[0].publication_date is not None
    assert publications[0].publication_date.isoformat() == "2024-02-03"
    assert publications[0].authors == ["Consortium"]


def test_pubtator_extract_pmids_accepts_common_shapes() -> None:
    assert _extract_pmids(["1", "x", 2]) == ["1", "2"]
    assert _extract_pmids({"pmids": "1, 2 3"}) == ["1", "2", "3"]
    assert _extract_pmids({"results": [{"id": 4}, {"pmid_str": "5"}]}) == [
        "4",
        "5",
    ]
    assert _extract_pmids({"results": [{"id": "not-numeric"}]}) == []


@pytest.mark.asyncio
@respx.mock
async def test_pubtator_relations_handles_non_list_payload() -> None:
    respx.get("https://pubtator-edge.test/relations").mock(
        return_value=httpx.Response(200, json={"relations": {"type": "treat"}})
    )
    client = PubTator3Client(
        base_url="https://pubtator-edge.test",
        rate=fast_bucket(),
    )

    assert await client.relations("@A", "treat", "@B") == []


def test_pubtator_document_fallbacks() -> None:
    client = PubTator3Client(rate=fast_bucket())

    publications = client._publications_from_biocjson(
        {
            "documents": [
                {
                    "id": "7",
                    "passages": [
                        {"infons": {"section": "body"}, "text": "Body text only."}
                    ],
                },
                {"id": "8", "passages": []},
            ]
        }
    )

    assert len(publications) == 1
    assert publications[0].title == "Body text only."
    assert publications[0].full_text == "Body text only."
