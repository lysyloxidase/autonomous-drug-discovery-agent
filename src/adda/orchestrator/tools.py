"""Uniform Tool abstraction for both Phase 6 orchestrators."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from adda.extraction.models import Entity, Relation
from adda.models.corpus import Corpus
from adda.orchestrator.state import AgentState
from adda.ranking import TargetScore
from adda.report.generator import ReportGenerator
from adda.report.verify_citations import CitationVerifier


class ToolInput(BaseModel):
    """Base typed tool input."""

    state: AgentState


class ToolOutput(BaseModel):
    """Base typed tool output."""

    state: AgentState


class RetrieveOutput(BaseModel):
    """Retrieve step output."""

    corpus: Corpus | None


class ExtractOutput(BaseModel):
    """Extract step output."""

    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


class BuildKGOutput(BaseModel):
    """KG build step output."""

    kg_built: bool


class RankOutput(BaseModel):
    """Ranking step output."""

    target_scores: list[TargetScore] = Field(default_factory=list)


class TriageOutput(BaseModel):
    """Molecule triage step output."""

    triaged_molecules: dict[str, Any] = Field(default_factory=dict)


class ReportOutput(BaseModel):
    """Report step output."""

    markdown: str
    html: str
    pdf: bytes
    json_payload: dict[str, Any]


class VerifyCitationsOutput(BaseModel):
    """Citation verification step output."""

    citation_accuracy: float
    verified_citations: list[str] = Field(default_factory=list)
    rejected_citations: list[str] = Field(default_factory=list)


class Tool(Protocol):
    """A uniform callable tool used by both orchestrators."""

    name: str
    continue_on_error: bool

    def run(self, state: AgentState) -> AgentState:
        """Return the updated agent state."""
        ...


Runner = Callable[[AgentState], AgentState]


class BaseTool(BaseModel):
    """Small Pydantic-backed tool wrapper around an optional runner."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    continue_on_error: bool = False
    runner: Runner | None = Field(default=None, exclude=True, repr=False)

    def run(self, state: AgentState) -> AgentState:
        """Run the configured callable, or pass state through unchanged."""

        if self.runner is None:
            return state
        return self.runner(state)


class RetrieveTool(BaseTool):
    """Retrieve literature for the disease query."""

    name: str = "retrieve"

    def run(self, state: AgentState) -> AgentState:
        updated = super().run(state)
        updated.refresh_retrieved_identifiers()
        return updated


class ExtractTool(BaseTool):
    """Extract entities and relations."""

    name: str = "extract"


class BuildKGTool(BaseTool):
    """Build or update the knowledge graph."""

    name: str = "build_kg"


class EvidenceTool(BaseTool):
    """Score and tier evidence."""

    name: str = "score_evidence"


class RankTool(BaseTool):
    """Rank disease targets."""

    name: str = "rank_targets"


class TriageTool(BaseTool):
    """Triage known active molecules."""

    name: str = "triage_molecules"


class ReportTool(BaseTool):
    """Generate citation-grounded reports."""

    name: str = "write_report"

    def run(self, state: AgentState) -> AgentState:
        if self.runner is not None:
            return super().run(state)
        return ReportGenerator().generate(state)


class VerifyCitationsTool(BaseTool):
    """Verify and enforce retrieval-only citations."""

    name: str = "verify_citations"

    def run(self, state: AgentState) -> AgentState:
        if self.runner is not None:
            return super().run(state)
        return CitationVerifier().verify_state(state)
