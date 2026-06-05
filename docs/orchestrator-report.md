# Orchestrator And Reports

Phase 6 implements the same pipeline with two orchestrators:

`plan -> retrieve -> extract -> build_kg -> score_evidence -> rank_targets -> triage_molecules -> write_report -> verify_citations`

The custom orchestrator demonstrates the engineering mechanics directly:
Pydantic `AgentState`, uniform `Tool` objects, tenacity retries, JSON
checkpoints after every node, resume from the last good checkpoint, degraded
continuation for noncritical tool failures, and streaming progress events.

The LangGraph orchestrator mirrors the same nodes with `StateGraph`,
`START`/`END`, and `SqliteSaver` checkpointing. Tests assert it does not use
`MemorySaver` and that it produces equivalent final state for the fixed disease
fixture.

Reports are citation-grounded. The generator emits Markdown, HTML, PDF, and
JSON, but citations are restricted to PMIDs/DOIs already present in the
retrieved corpus. The verifier parses every cited PMID/DOI, checks that it was
retrieved, strips or flags unverifiable citations, and writes
`citation_accuracy` back to state.

The golden fixture currently reaches `citation_accuracy = 1.0`, above the
required `0.95` gate.
