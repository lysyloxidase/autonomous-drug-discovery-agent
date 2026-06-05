# Autonomous Drug Discovery Agent

Autonomous Drug Discovery Agent turns a disease name into a citation-grounded
therapeutic-target research report. Phase 1 builds the retrieval foundation:
PubMed, Europe PMC, OpenAlex, and PubTator3 clients with rate limiting, caching,
and DOI/PMID/PMCID deduplication.

> Research-only software. This project does not provide clinical advice,
> diagnosis, treatment recommendations, or patient-specific decision support.

## Phase 1 Scope

| Capability | Status | Notes |
| --- | --- | --- |
| PubMed E-utilities | Implemented | esearch plus efetch MEDLINE XML parsing |
| Europe PMC | Implemented | REST search plus PMCID fullTextXML helper |
| OpenAlex | Implemented | works search, citation counts, identifier crosswalk |
| PubTator3 | Implemented | search, BioC-JSON export, relations helper |
| Rate limiting | Implemented | async token bucket per source |
| Caching | Implemented | diskcache by default, Redis optional |
| Deduplication | Implemented | DOI > PMID > PMCID > title hash |
| Corpus assembly | Implemented | graceful source degradation and cache-hit flag |

## Real vs Mocked

Runtime clients call public literature APIs directly. Tests use mocked HTTP
responses and local cache backends so CI remains deterministic and does not
consume API quotas. Later phases can add VCR cassettes for selected integration
smoke tests without changing the retrieval interfaces.

## Quickstart

```bash
uv sync --all-extras
cp .env.example .env
uv run adda retrieve "glioblastoma" --max-results 20 --json
```

OpenAlex requires `OPENALEX_API_KEY` for normal retrieval. PubMed works without
`NCBI_API_KEY`, but the key raises the rate limit from 3 requests/sec to 10
requests/sec.

## Development

```bash
make test
make lint
make typecheck
```

## Architecture

Phase 1 retrieves a multi-source literature corpus, normalizes all records into
`Publication`, deduplicates by identifier union, and returns a `Corpus` with
source counts and cache-hit metadata. PubTator3 annotations are intentionally
kept close to the retrieval layer because later phases use them as the primary
entity evidence source.

