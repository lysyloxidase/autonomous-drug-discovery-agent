# ADR 0002: Local LLM via Ollama

## Status

Accepted for later phases

## Context

Later extraction and report phases may need summarization or planning while
keeping development reproducible.

## Decision

Use Ollama as the default local LLM runtime in Docker for development.

## Consequences

The retrieval layer remains independent of LLM availability. Later phases can
use local models without sending unpublished research context to external
providers by default.

