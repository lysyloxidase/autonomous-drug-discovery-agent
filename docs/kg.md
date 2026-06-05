# Knowledge Graph

Phase 3 stores grounded extraction output in Neo4j as a provenance-first
property graph.

Core node labels are `Disease`, `Gene`, `Pathway`, `Drug`, `Phenotype`,
`Variant`, and `Publication`. Business keys use normalized ontology IDs or
PMIDs, and schema constraints enforce uniqueness for every label.

Relationship loading uses `apoc.periodic.iterate` and `apoc.merge.*` procedures
so batch runs are idempotent. Every edge must carry:

- `source_pmids`
- `extraction_confidence`
- `evidence_tier`
- `source_db`
- `created_at`
- `extractor_version`

The centrality layer uses the Graph Data Science Python client to project a
disease ego-network and stream PageRank, degree, and betweenness scores as
pandas DataFrames. Scores are normalized to `normalized_score` in the 0-1 range
before Phase 5 consumes them.

