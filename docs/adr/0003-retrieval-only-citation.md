# ADR 0003: Retrieval-Only Citation Grounding

## Status

Accepted

## Context

The project should not invent citations or rely on generated references.

## Decision

All Phase 1 citations must originate from retrieval clients and normalize into
the canonical `Publication` model.

## Consequences

Reports can only cite records present in the retrieved corpus. Missing evidence
is represented as a retrieval gap, not filled by generation.

