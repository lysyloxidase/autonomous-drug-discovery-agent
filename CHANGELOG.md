# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog 1.1.0, and this project adheres to
Semantic Versioning.

## [0.1.0] - 2026-06-05

### Added

- Phase 1 retrieval layer for PubMed, Europe PMC, OpenAlex, and PubTator3.
- Async token-bucket rate limiting and transient HTTP retry helpers.
- Disk and Redis cache adapters with async cache decorator.
- Canonical `Publication` and `Corpus` Pydantic models.
- DOI/PMID/PMCID/title-hash deduplication.
- Corpus assembly with graceful source degradation and cache-hit metadata.
- Project docs, ADRs, Docker scaffolding, and quality tooling.

