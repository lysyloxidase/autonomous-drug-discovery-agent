# ADR 0005: Dual Orchestrator

## Status

Accepted for later phases

## Context

Long-running research workflows need both deterministic steps and adaptive
planning.

## Decision

Use a deterministic pipeline for retrieval, dedupe, extraction, KG loading,
evidence scoring, ranking, molecule triage, report writing, and citation
verification. Maintain two equivalent orchestrators:

- a custom Pydantic-state machine with retry, checkpoint/resume, degraded
  continuation, and streaming events
- a LangGraph graph with the same nodes and SQLite checkpointing

Be explicit that the pipeline is mostly a deterministic DAG. The genuinely
agentic parts are query reformulation, relation extraction, and report
synthesis.

## Consequences

Core evidence handling stays testable while still allowing autonomous behavior
where it adds value. The parity test keeps the custom and LangGraph
implementations from drifting.
