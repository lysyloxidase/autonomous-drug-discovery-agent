# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog 1.1.0, and this project adheres to
Semantic Versioning.

## [0.1.0] - 2026-06-05

### Added

- Phase 1 retrieval layer for PubMed, Europe PMC, OpenAlex, and PubTator3.
- Phase 2 entity extraction and ontology grounding layer.
- Phase 3 Neo4j knowledge graph and centrality layer.
- Phase 4 Open Targets evidence grounding and tiering layer.
- Phase 5 transparent target ranking and ChEMBL/RDKit known-active molecule
  triage.
- Async token-bucket rate limiting and transient HTTP retry helpers.
- Disk and Redis cache adapters with async cache decorator.
- Canonical `Publication` and `Corpus` Pydantic models.
- DOI/PMID/PMCID/title-hash deduplication.
- Corpus assembly with graceful source degradation and cache-hit metadata.
- PubTator3 BioC entity and typed-relation parsing.
- scispaCy fallback extraction with explicit extractor tags.
- Ollama local-LLM constrained relation extraction with speculative flags.
- Extraction precision/recall/F1 benchmark reporting.
- Neo4j schema constraints and APOC batch loading.
- Required edge provenance model for all KG relationships.
- GDS PageRank, degree, and betweenness centrality wrappers.
- Open Targets GraphQL client for associations and tractability.
- Harmonic-sum evidence aggregation and known-top-target validation gate.
- Robust/plausible/speculative evidence tiering with co-occurrence forced
  speculative.
- Neo4j evidence-tier writeback helper.
- Multi-criteria target ranker with visible weighted component breakdowns.
- ChEMBL known-active client scoped to pChEMBL-filtered binding assays.
- RDKit molecule triage for descriptors, drug-likeness rules, alerts,
  fingerprint similarity, and scaffold clustering.
- Project docs, ADRs, Docker scaffolding, and quality tooling.
