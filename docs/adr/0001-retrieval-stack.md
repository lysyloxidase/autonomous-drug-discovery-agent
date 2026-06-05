# ADR 0001: Retrieval Stack

## Status

Accepted

## Context

The agent needs citation-grounded target evidence from biomedical literature.

## Decision

Use PubMed for canonical biomedical abstracts and MeSH terms, Europe PMC for OA
full text and preprints, OpenAlex for citations and identifier crosswalks, and
PubTator3 for biomedical entity annotations.

## Consequences

The retrieval layer has multiple independent sources and can degrade gracefully
when one source is unavailable.

