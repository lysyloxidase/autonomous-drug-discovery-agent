"""Typed agent state shared by both orchestrators."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from adda.extraction.models import Entity, Relation
from adda.models.corpus import Corpus
from adda.ranking import TargetScore


class AgentState(BaseModel):
    """State object passed between every Phase 6 pipeline node."""

    disease_query: str
    corpus: Corpus | None = None
    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    kg_built: bool = False
    target_scores: list[TargetScore] = Field(default_factory=list)
    triaged_molecules: dict[str, Any] = Field(default_factory=dict)
    report_markdown: str | None = None
    report_html: str | None = None
    report_pdf: bytes | None = None
    report_json: dict[str, Any] = Field(default_factory=dict)
    citation_accuracy: float | None = None
    step_log: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)
    checkpoint_id: str | None = None
    iteration_count: int = 0
    retrieved_pmids: list[str] = Field(default_factory=list)
    retrieved_dois: list[str] = Field(default_factory=list)
    verified_citations: list[str] = Field(default_factory=list)
    rejected_citations: list[str] = Field(default_factory=list)

    def mark_completed(self, step_name: str) -> None:
        """Record a completed step once."""

        if step_name not in self.completed_steps:
            self.completed_steps.append(step_name)

    def refresh_retrieved_identifiers(self) -> None:
        """Derive retrieval-only citation identifiers from the corpus."""

        if self.corpus is None:
            return
        pmids = [
            publication.pmid
            for publication in self.corpus.publications
            if publication.pmid
        ]
        dois = [
            publication.doi.lower()
            for publication in self.corpus.publications
            if publication.doi
        ]
        self.retrieved_pmids = sorted(set(pmids))
        self.retrieved_dois = sorted(set(dois))
