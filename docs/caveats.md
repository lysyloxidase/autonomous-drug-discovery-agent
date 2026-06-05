# Research Report Caveats

1. Outputs are research-only and not clinical advice.
2. Retrieval may miss relevant publications.
3. API outages or rate limits can reduce source coverage.
4. Preprints may not be peer reviewed.
5. Citation counts can lag or vary by source.
6. Abstract-only records can omit critical experimental context.
7. Open-access full text availability depends on record license.
8. Entity annotations can contain false positives and false negatives.
9. Identifier metadata can be incomplete or inconsistent.
10. Deduplication may merge records with ambiguous metadata.
11. Older literature may use outdated nomenclature.
12. Therapeutic target evidence does not imply druggability.
13. Association evidence does not imply causation.
14. All hypotheses require expert review and experimental validation.
15. Local-LLM relation extraction is weaker than database-backed extraction and
    must remain speculative unless independently supported.
16. Open Targets association scores are ranking heuristics, not causal
    probabilities.
17. Target ranking weights are transparent prioritization heuristics and should
    be sensitivity-tested for each disease program.
18. Molecule triage covers known ChEMBL actives only; it is not de novo
    generation, docking, or proof of efficacy.
19. Orchestration is mostly a deterministic DAG; only query reformulation,
    relation extraction, and report synthesis are genuinely agentic.
20. Citation verification can prove that a citation was retrieved and accepted,
    not that the cited study fully supports every downstream interpretation.
