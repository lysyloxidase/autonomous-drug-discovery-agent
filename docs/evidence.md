# Evidence Tiering

Phase 4 grounds target-disease associations in Open Targets and classifies graph
edges into three evidence tiers.

Open Targets associations are pulled through the GraphQL API, including overall
association scores, per-datatype scores, known-drug signals, and tractability
buckets. Datatype scores are aggregated with an Open Targets-style harmonic sum:
scores are sorted, divided by rank squared, summed, and normalized by the
theoretical harmonic maximum.

Evidence tiers:

- `robust`: human genetic evidence, known-drug indication evidence, or
  replicated non-preclinical datatypes.
- `plausible`: animal/pathway/expression support or a typed PubTator3 relation
  with mechanistic support.
- `speculative`: co-occurrence-only literature, single-source weak evidence, or
  local-LLM relations not verified by a reference database.

The hard rule is simple: literature co-occurrence is not causation.
Co-occurrence-only and unverified local-LLM edges are always labeled
`speculative` and written back to the KG as `evidence_tier="speculative"`.

