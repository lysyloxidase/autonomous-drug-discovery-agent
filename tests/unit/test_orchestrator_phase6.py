from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from adda.models.corpus import Corpus, Publication
from adda.orchestrator import (
    BuildKGTool,
    CustomOrchestrator,
    EvidenceTool,
    ExtractTool,
    LangGraphOrchestrator,
    OrchestratorError,
    RankTool,
    ReportTool,
    RetrieveTool,
    TransientToolError,
    TriageTool,
    VerifyCitationsTool,
)
from adda.orchestrator.runtime import PIPELINE_STEPS
from adda.orchestrator.state import AgentState
from adda.orchestrator.tools import Tool
from adda.ranking import TargetScore


def make_corpus(disease: str) -> Corpus:
    return Corpus(
        disease_query=disease,
        publications=[
            Publication(
                canonical_id="pmid:2001",
                pmid="2001",
                title="Disease target evidence one",
            ),
            Publication(
                canonical_id="pmid:2002",
                pmid="2002",
                title="Disease target evidence two",
            ),
        ],
        per_source_counts={"pubmed": 2},
        retrieved_at=datetime.now(UTC).isoformat(),
    )


def make_target(index: int) -> TargetScore:
    return TargetScore(
        target_symbol=f"T{index}",
        target_id=f"ENSG{index:011d}",
        centrality=1.0 - index * 0.02,
        ot_association=0.9,
        druggability=0.8,
        genetic_evidence=0.7,
        novelty=0.6,
        safety_penalty=0.1,
        composite_score=0.9 - index * 0.01,
        evidence_tier="robust" if index <= 2 else "plausible",
        component_breakdown={
            "centrality": 1.0 - index * 0.02,
            "ot_association": 0.9,
            "druggability": 0.8,
            "genetic_evidence": 0.7,
            "novelty": 0.6,
            "safety_penalty": 0.1,
        },
    )


def retrieve_runner(state: AgentState) -> AgentState:
    state.corpus = make_corpus(state.disease_query)
    return state


def extract_runner(state: AgentState) -> AgentState:
    state.entities = []
    state.relations = []
    return state


def kg_runner(state: AgentState) -> AgentState:
    state.kg_built = True
    return state


def evidence_runner(state: AgentState) -> AgentState:
    state.report_json = {**state.report_json, "evidence_scored": True}
    return state


def rank_runner(state: AgentState) -> AgentState:
    state.target_scores = [make_target(index) for index in range(1, 7)]
    return state


def triage_runner(state: AgentState) -> AgentState:
    state.triaged_molecules = {
        "ENSG00000000001": [
            {"molecule_chembl_id": "CHEMBL1", "scope_label": "known actives only"}
        ]
    }
    return state


def pipeline_tools(
    *,
    retrieve_tool: Tool | None = None,
    rank_tool: Tool | None = None,
    triage_tool: Tool | None = None,
) -> list[Tool]:
    return [
        retrieve_tool or RetrieveTool(runner=retrieve_runner),
        ExtractTool(runner=extract_runner),
        BuildKGTool(runner=kg_runner),
        EvidenceTool(runner=evidence_runner),
        rank_tool or RankTool(runner=rank_runner),
        triage_tool or TriageTool(runner=triage_runner),
        ReportTool(),
        VerifyCitationsTool(),
    ]


def test_custom_orchestrator_runs_full_pipeline_to_verified_report(
    tmp_path: Path,
) -> None:
    orchestrator = CustomOrchestrator(
        pipeline_tools(),
        tmp_path,
        wait_multiplier=0,
    )

    state = orchestrator.run("glioblastoma")

    assert state.completed_steps == list(PIPELINE_STEPS)
    assert state.kg_built is True
    assert len(state.target_scores) == 6
    assert state.report_markdown is not None
    assert "T1" in state.report_markdown
    assert state.citation_accuracy == 1.0
    assert state.report_html is not None
    assert state.report_pdf is not None
    assert state.report_json["citation_accuracy"] == 1.0


def test_checkpoint_resume_after_mid_run_failure_matches_final_result(
    tmp_path: Path,
) -> None:
    calls = {"rank": 0}

    def flaky_rank(state: AgentState) -> AgentState:
        calls["rank"] += 1
        if calls["rank"] == 1:
            raise RuntimeError("rank process died")
        return rank_runner(state)

    orchestrator = CustomOrchestrator(
        pipeline_tools(rank_tool=RankTool(runner=flaky_rank)),
        tmp_path,
        wait_multiplier=0,
    )

    with pytest.raises(OrchestratorError):
        orchestrator.run("glioblastoma")

    checkpoint_id = orchestrator.last_checkpoint_id
    assert checkpoint_id is not None
    resumed = orchestrator.resume(checkpoint_id)

    assert resumed.completed_steps == list(PIPELINE_STEPS)
    assert resumed.citation_accuracy == 1.0
    assert calls["rank"] == 2


def test_transient_tool_error_retries_with_attempt_count(tmp_path: Path) -> None:
    calls = {"retrieve": 0}

    def flaky_retrieve(state: AgentState) -> AgentState:
        calls["retrieve"] += 1
        if calls["retrieve"] < 3:
            raise TransientToolError("temporary PubMed outage")
        return retrieve_runner(state)

    orchestrator = CustomOrchestrator(
        pipeline_tools(retrieve_tool=RetrieveTool(runner=flaky_retrieve)),
        tmp_path,
        wait_multiplier=0,
    )

    state = orchestrator.run("glioblastoma")

    retrieve_log = next(
        entry for entry in state.step_log if entry["step"] == "retrieve"
    )
    assert calls["retrieve"] == 3
    assert retrieve_log["attempts"] == 3


def test_partial_failure_recovery_degrades_report_without_crashing(
    tmp_path: Path,
) -> None:
    def failing_triage(state: AgentState) -> AgentState:
        raise RuntimeError("ChEMBL unavailable")

    triage = TriageTool(runner=failing_triage, continue_on_error=True)
    orchestrator = CustomOrchestrator(
        pipeline_tools(triage_tool=triage),
        tmp_path,
        wait_multiplier=0,
    )

    state = orchestrator.run("glioblastoma")

    assert state.citation_accuracy == 1.0
    assert state.errors[0]["step"] == "triage_molecules"
    assert state.errors[0]["recoverable"] is True
    assert "Degraded Steps" in (state.report_markdown or "")


def test_streaming_progress_events_cover_pipeline(tmp_path: Path) -> None:
    orchestrator = CustomOrchestrator(
        pipeline_tools(),
        tmp_path,
        wait_multiplier=0,
    )

    events = list(orchestrator.stream("glioblastoma"))

    started = [event["step"] for event in events if event["event"] == "step_started"]
    assert started == list(PIPELINE_STEPS)
    assert events[-1]["event"] == "complete"


def test_langgraph_parity_and_sqlite_checkpointer(tmp_path: Path) -> None:
    custom = CustomOrchestrator(
        pipeline_tools(),
        tmp_path / "custom",
        wait_multiplier=0,
    )
    langgraph = LangGraphOrchestrator(
        pipeline_tools(),
        tmp_path / "langgraph.sqlite",
        wait_multiplier=0,
    )

    try:
        custom_state = custom.run("glioblastoma")
        langgraph_state = langgraph.run("glioblastoma")
    finally:
        langgraph.close()

    assert type(langgraph.checkpointer).__name__ == "SqliteSaver"
    assert type(langgraph.checkpointer).__name__ != "MemorySaver"
    assert langgraph_state.target_scores == custom_state.target_scores
    assert langgraph_state.citation_accuracy == custom_state.citation_accuracy
    assert langgraph_state.report_json["targets"] == custom_state.report_json["targets"]


def test_langgraph_iteration_cap_prevents_unbounded_runs(tmp_path: Path) -> None:
    langgraph = LangGraphOrchestrator(
        pipeline_tools(),
        tmp_path / "cap.sqlite",
        wait_multiplier=0,
        iteration_cap=1,
    )

    try:
        with pytest.raises(OrchestratorError):
            langgraph.run("glioblastoma")
    finally:
        langgraph.close()
