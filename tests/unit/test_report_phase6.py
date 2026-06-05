from __future__ import annotations

from datetime import UTC, datetime

from adda.models.corpus import Corpus, Publication
from adda.orchestrator.state import AgentState
from adda.ranking import TargetScore
from adda.report import CitationVerifier, ReportGenerator, parse_pmids


def target_score(index: int) -> TargetScore:
    return TargetScore(
        target_symbol=f"TARGET{index}",
        target_id=f"ENSG{index:011d}",
        centrality=0.9,
        ot_association=0.8,
        druggability=0.7,
        genetic_evidence=0.6,
        novelty=0.5,
        safety_penalty=0.1,
        composite_score=0.75 - index * 0.01,
        evidence_tier="robust" if index == 1 else "plausible",
        component_breakdown={
            "centrality": 0.9,
            "ot_association": 0.8,
            "druggability": 0.7,
            "genetic_evidence": 0.6,
            "novelty": 0.5,
            "safety_penalty": 0.1,
        },
    )


def corpus() -> Corpus:
    return Corpus(
        disease_query="glioblastoma",
        publications=[
            Publication(
                canonical_id="pmid:1001",
                pmid="1001",
                doi="10.1000/a",
                title="Target evidence A",
            ),
            Publication(
                canonical_id="pmid:1002",
                pmid="1002",
                title="Target evidence B",
            ),
        ],
        per_source_counts={"pubmed": 2},
        retrieved_at=datetime.now(UTC).isoformat(),
    )


def state_with_targets() -> AgentState:
    state = AgentState(
        disease_query="glioblastoma",
        corpus=corpus(),
        target_scores=[target_score(index) for index in range(1, 7)],
        triaged_molecules={
            "ENSG00000000001": [
                {"molecule_chembl_id": "CHEMBL1", "scope_label": "known actives only"}
            ]
        },
    )
    state.refresh_retrieved_identifiers()
    return state


def test_report_generator_outputs_four_formats_and_top_five_targets() -> None:
    state = ReportGenerator().generate(state_with_targets())

    assert state.report_markdown is not None
    assert state.report_html is not None
    assert state.report_pdf is not None
    assert state.report_json["targets"][0]["target_symbol"] == "TARGET1"
    assert state.report_json["triaged_molecules"]["ENSG00000000001"][0][
        "molecule_chembl_id"
    ] == "CHEMBL1"
    graph = state.report_json["knowledge_graph"]
    assert {"nodes", "edges"} <= set(graph)
    assert any(node["type"] == "disease" for node in graph["nodes"])
    assert any(node["id"] == "CHEMBL1" for node in graph["nodes"])
    assert any(edge["relation"] == "ASSOCIATED_WITH" for edge in graph["edges"])
    assert any(edge["relation"] == "TARGETS" for edge in graph["edges"])
    assert len(state.report_json["targets"]) == 5
    assert state.report_pdf.startswith(b"%PDF")
    assert "Evidence tier" in state.report_markdown
    assert "CRISPR knockout" in state.report_markdown
    assert "Co-occurrence is not causation" in state.report_markdown
    assert set(parse_pmids(state.report_markdown)) <= {"1001", "1002"}


def test_citation_verifier_enforces_retrieval_only_and_strips_invented_pmids() -> None:
    verifier = CitationVerifier(pmid_exists=lambda pmid: pmid in {"1001", "9999"})

    result = verifier.verify_report(
        "Supported claim [PMID:1001]. Invented claim [PMID:9999].",
        evidence_pmids=["1001"],
    )

    assert result.citation_accuracy == 0.5
    assert result.verified == ["PMID:1001"]
    assert result.rejected == ["PMID:9999"]
    assert "PMID:9999" not in result.sanitized_report
    assert "unverified PMID removed" in result.sanitized_report


def test_verify_state_sets_accuracy_gate_to_one_for_golden_report() -> None:
    state = ReportGenerator().generate(state_with_targets())

    verified = CitationVerifier().verify_state(state)

    assert verified.citation_accuracy == 1.0
    assert verified.citation_accuracy is not None
    assert verified.citation_accuracy >= 0.95
    assert verified.rejected_citations == []
    assert verified.verified_citations
