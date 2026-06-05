# Autonomous Drug Discovery Agent

This project builds an autonomous, retrieval-first research agent for
therapeutic-target discovery. Phase 1 focuses on trustworthy corpus assembly
from PubMed, Europe PMC, OpenAlex, and PubTator3.

The project is research-only and does not provide clinical advice.

Phase 5 adds transparent target ranking and ChEMBL/RDKit known-active molecule
triage. All target score components are visible, and molecule outputs are
explicitly labeled as known actives only, not de novo design or docking.

Phase 6 adds dual orchestration and citation-grounded report generation. The
custom and LangGraph orchestrators run the same nodes, and reports are verified
with a retrieval-only citation-accuracy gate.
