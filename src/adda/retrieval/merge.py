"""Multi-source corpus assembly."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog

from adda.cache import cache_get, cache_set, make_cache_key
from adda.config import Settings, load_settings
from adda.models import Corpus, Publication
from adda.ratelimit import TokenBucket
from adda.retrieval.base import RetrievalClient
from adda.retrieval.dedupe import dedupe_publications
from adda.retrieval.europepmc import EuropePMCClient
from adda.retrieval.openalex import OpenAlexClient
from adda.retrieval.pubmed import PubMedClient
from adda.retrieval.pubtator3 import PubTator3Client

LOGGER = structlog.get_logger(__name__)


def clients_from_settings(settings: Settings | None = None) -> list[RetrievalClient]:
    """Build the default Phase 1 retrieval clients from settings."""

    settings = settings or load_settings()

    pubmed = settings.sources["pubmed"]
    europepmc = settings.sources["europepmc"]
    openalex = settings.sources["openalex"]
    pubtator3 = settings.sources["pubtator3"]

    return [
        PubMedClient(
            api_key=settings.ncbi_api_key,
            rate=TokenBucket(pubmed.requests_per_second, pubmed.burst),
            base_url=pubmed.base_url,
            timeout=pubmed.timeout_seconds,
        ),
        EuropePMCClient(
            rate=TokenBucket(europepmc.requests_per_second, europepmc.burst),
            base_url=europepmc.base_url,
            timeout=europepmc.timeout_seconds,
        ),
        OpenAlexClient(
            api_key=settings.openalex_api_key,
            rate=TokenBucket(openalex.requests_per_second, openalex.burst),
            base_url=openalex.base_url,
            timeout=openalex.timeout_seconds,
        ),
        PubTator3Client(
            rate=TokenBucket(pubtator3.requests_per_second, pubtator3.burst),
            base_url=pubtator3.base_url,
            timeout=pubtator3.timeout_seconds,
        ),
    ]


async def _retrieve_one(
    client: RetrievalClient,
    query: str,
    max_results: int,
) -> tuple[str, list[Publication], Exception | None]:
    try:
        publications = await client.retrieve(query, max_results=max_results)
    except Exception as exc:
        LOGGER.warning(
            "retrieval_source_failed",
            source=client.source_name,
            error=str(exc),
        )
        return client.source_name, [], exc
    return client.source_name, publications, None


async def _close_clients(clients: Sequence[RetrievalClient]) -> None:
    for client in clients:
        close = getattr(client, "aclose", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


async def assemble_corpus(
    disease_query: str,
    *,
    clients: Sequence[RetrievalClient] | None = None,
    max_results: int = 200,
    use_cache: bool = True,
) -> Corpus:
    """Retrieve, dedupe, and cache a disease-query corpus."""

    created_clients = clients is None
    active_clients = list(clients or clients_from_settings())
    source_names = [client.source_name for client in active_clients]
    cache_key = make_cache_key(
        "corpus",
        disease_query.strip().lower(),
        max_results,
        sorted(source_names),
    )
    if use_cache:
        cached_value = await cache_get(cache_key)
        if isinstance(cached_value, Corpus):
            return cached_value.model_copy(update={"cache_hit": True})

    try:
        results = await asyncio.gather(
            *[
                _retrieve_one(client, disease_query, max_results)
                for client in active_clients
            ]
        )
        publications: list[Publication] = []
        per_source_counts: dict[str, int] = {}
        for source_name, source_publications, _error in results:
            per_source_counts[source_name] = len(source_publications)
            publications.extend(source_publications)

        corpus = Corpus(
            disease_query=disease_query,
            publications=dedupe_publications(publications),
            per_source_counts=per_source_counts,
            retrieved_at=datetime.now(UTC).isoformat(),
            cache_hit=False,
        )
        if use_cache:
            await cache_set(cache_key, corpus)
        return corpus
    finally:
        if created_clients:
            await _close_clients(active_clients)
