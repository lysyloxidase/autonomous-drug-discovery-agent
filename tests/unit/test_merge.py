from __future__ import annotations

from adda.models import Publication
from adda.retrieval.base import RetrievalClient
from adda.retrieval.merge import assemble_corpus


class FakeClient(RetrievalClient):
    def __init__(
        self,
        source_name: str,
        publications: list[Publication],
        *,
        fail: bool = False,
    ) -> None:
        self.source_name = source_name
        self.publications = publications
        self.fail = fail
        self.calls = 0

    async def retrieve(self, query: str, max_results: int = 200) -> list[Publication]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("source unavailable")
        return self.publications[:max_results]


def publication(source: str) -> Publication:
    return Publication(
        canonical_id="pmid:123",
        pmid="123",
        title="Cached corpus record",
        sources=[source],
    )


async def test_assemble_corpus_reports_cache_hit_on_second_query() -> None:
    client = FakeClient("pubmed", [publication("pubmed")])

    first = await assemble_corpus("glioblastoma", clients=[client])
    second = await assemble_corpus("glioblastoma", clients=[client])

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert client.calls == 1
    assert second.per_source_counts == {"pubmed": 1}


async def test_assemble_corpus_degrades_when_one_source_fails() -> None:
    good = FakeClient("pubmed", [publication("pubmed")])
    bad = FakeClient("openalex", [], fail=True)

    corpus = await assemble_corpus(
        "glioblastoma",
        clients=[good, bad],
        use_cache=False,
    )

    assert corpus.per_source_counts == {"pubmed": 1, "openalex": 0}
    assert len(corpus.publications) == 1
    assert corpus.publications[0].sources == ["pubmed"]
