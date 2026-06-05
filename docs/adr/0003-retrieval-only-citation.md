# ADR 0003: Retrieval-Only Citation Grounding

## Status

Accepted

## Context

The project should not invent citations or rely on generated references.

## Decision

All citations must originate from retrieval clients and normalize into the
canonical `Publication` model. Report generation may cite only PMIDs/DOIs
present in the retrieved `Corpus`; post-hoc verification strips or flags
anything outside that evidence set.

## Consequences

Reports can only cite records present in the retrieved corpus. Missing evidence
is represented as a retrieval gap, not filled by generation.
