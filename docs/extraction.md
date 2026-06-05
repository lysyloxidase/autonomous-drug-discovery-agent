# Entity Extraction

Phase 2 uses PubTator3 BioC annotations as the authoritative entity and typed
relation source. Entities normalize to explicit ontology IDs, and PubTator3
relations are treated as typed database-supported edges rather than mere
co-occurrence.

scispaCy is a supplemental fallback for passages without PubTator3 coverage. It
is always tagged `extractor="scispacy"` and grounded through the ontology cache
or marked `ontology="unresolved"`.

Local-LLM relation extraction is intentionally conservative. The Ollama adapter
requires Pydantic-constrained JSON. Relations without database support are
tagged `extractor="local_llm"` and `is_cooccurrence_only=true`, which forces
them into the SPECULATIVE evidence tier in later phases.

The benchmark utilities compute precision, recall, and F1 against PubTator3 or
BioRED-shaped gold records and write `reports/extraction_eval.json`.

