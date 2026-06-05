# Autonomous Drug Discovery Agent

Autonomous Drug Discovery Agent turns a disease name into a citation-grounded
therapeutic-target research report. Phase 1 builds the retrieval foundation;
Phase 2 adds entity extraction, ontology grounding, and honest relation-quality
measurement. Later phases add a provenance-first KG, evidence tiering,
transparent target ranking, and known-active molecule triage.

> Research-only software. This project does not provide clinical advice,
> diagnosis, treatment recommendations, or patient-specific decision support.

## Scope

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
| PubTator3 entity extraction | Implemented | BioC annotations normalize to ontology IDs |
| scispaCy fallback | Implemented | optional injectable pipeline, tagged fallback output |
| Local-LLM relation extraction | Implemented | Ollama structured JSON, speculative flags |
| Extraction benchmark | Implemented | precision/recall/F1 report writer |
| Neo4j knowledge graph | Implemented | schema constraints, APOC batch load, provenance on every edge |
| GDS centrality | Implemented | PageRank, degree, betweenness normalized to 0-1 |
| Open Targets evidence | Implemented | GraphQL associations, datatype scores, tractability |
| Evidence tiering | Implemented | robust/plausible/speculative with co-occurrence forced speculative |
| Target ranking | Implemented | transparent weighted centrality, Open Targets, druggability, genetics, novelty, safety |
| ChEMBL molecule lookup | Implemented | known actives only, pChEMBL >= 5 binding assays |
| RDKit molecule triage | Implemented | descriptors, Lipinski/Veber/QED, PAINS/Brenk, Tanimoto, Murcko scaffolds |

## Extraction Honesty Gate

| Evaluation | NER precision | NER recall | RE precision | RE recall | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| BioRED smoke subset | 0.6667 | 1.0000 | 0.5000 | 1.0000 | Small committed fixture; not full benchmark performance |

LLM-derived relations without database support are always tagged
`is_cooccurrence_only=true`. Later evidence ranking must force those relations
to the SPECULATIVE tier.

## Real vs Mocked

Runtime clients call public literature APIs directly. Tests use mocked HTTP
responses and local cache backends so CI remains deterministic and does not
consume API quotas. Extraction tests use BioC-shaped PubTator3 fixtures, fake
scispaCy-like pipelines, and mocked Ollama responses. Later phases can add VCR
cassettes for selected integration smoke tests without changing the interfaces.
ChEMBL tests use fake client resources; RDKit tests run local chemistry
descriptors. Molecule outputs are labeled known actives only, not de novo
design and not docking.

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
source counts and cache-hit metadata. Phase 2 turns PubTator3 annotations into
grounded `Entity` and typed `Relation` records, then supplements gaps with
tagged scispaCy and local-LLM fallbacks. Phase 3 loads those records into Neo4j
with required provenance on every edge and computes GDS centrality features for
the ranking layer. Phase 4 grounds disease-target claims in Open Targets and
writes explainable evidence tiers back to KG relationships. Phase 5 combines
centrality, Open Targets evidence, druggability, genetic support, novelty, and
safety penalties into visible target scores, then triages ChEMBL known actives
with RDKit.
