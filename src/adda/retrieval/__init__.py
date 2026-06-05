"""Literature retrieval clients and corpus assembly helpers."""

from adda.retrieval.dedupe import canonical_key, dedupe_publications
from adda.retrieval.merge import assemble_corpus

__all__ = ["assemble_corpus", "canonical_key", "dedupe_publications"]
