# ADR 0005: Dual Orchestrator

## Status

Accepted for later phases

## Context

Long-running research workflows need both deterministic steps and adaptive
planning.

## Decision

Use a deterministic pipeline for retrieval, dedupe, extraction, and ranking;
allow an agentic orchestrator to plan retries, evidence gap checks, and report
composition around those deterministic tools.

## Consequences

Core evidence handling stays testable while still allowing autonomous behavior
where it adds value.

