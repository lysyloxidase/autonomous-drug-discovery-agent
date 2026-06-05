from __future__ import annotations

import math

from adda.evidence.aggregate import AssociationEvidence
from adda.evidence.tiering import EvidenceTier
from adda.ranking.target_ranker import (
    TargetCandidate,
    TargetRanker,
    benchmark_known_targets,
    candidate_from_association,
    druggability_from_tractability,
    novelty_from_literature_count,
)


def test_ranker_exposes_all_components_and_weighted_composite() -> None:
    candidate = TargetCandidate(
        target_symbol="EGFR",
        target_id="ENSG00000146648",
        centrality=0.8,
        ot_association=0.7,
        druggability=0.9,
        genetic_evidence=0.4,
        novelty=0.5,
        safety_penalty=0.2,
        evidence_tier="robust",
    )

    score = TargetRanker().rank_candidates([candidate])[0]

    assert score.target_symbol == "EGFR"
    assert score.evidence_tier == "robust"
    assert score.component_breakdown["centrality"] == 0.8
    assert score.component_breakdown["weighted_ot_association"] == 0.7 * 0.25
    assert score.component_breakdown["weighted_safety_penalty"] == 0.2 * 0.10
    assert math.isclose(score.composite_score, 0.605)


def test_user_adjustable_weights_change_target_order() -> None:
    central = TargetCandidate(
        target_symbol="CENT",
        target_id="CENT",
        centrality=1.0,
        ot_association=0.1,
        druggability=0.1,
        genetic_evidence=0.1,
        novelty=0.1,
        safety_penalty=0.0,
        evidence_tier="plausible",
    )
    open_targets = TargetCandidate(
        target_symbol="OT",
        target_id="OT",
        centrality=0.1,
        ot_association=1.0,
        druggability=0.1,
        genetic_evidence=0.1,
        novelty=0.1,
        safety_penalty=0.0,
        evidence_tier="robust",
    )

    centrality_ranker = TargetRanker(
        weights={
            "centrality": 1.0,
            "ot_association": 0.0,
            "druggability": 0.0,
            "genetic_evidence": 0.0,
            "novelty": 0.0,
            "safety_penalty": 0.0,
        }
    )
    ot_ranker = TargetRanker(
        weights={
            "centrality": 0.0,
            "ot_association": 1.0,
            "druggability": 0.0,
            "genetic_evidence": 0.0,
            "novelty": 0.0,
            "safety_penalty": 0.0,
        }
    )

    assert (
        centrality_ranker.rank_candidates([central, open_targets])[0].target_id
        == "CENT"
    )
    assert ot_ranker.rank_candidates([central, open_targets])[0].target_id == "OT"


def test_evidence_tier_breaks_composite_score_ties() -> None:
    robust = TargetCandidate(
        target_symbol="ROBUST",
        target_id="A",
        centrality=0.5,
        ot_association=0.5,
        druggability=0.5,
        genetic_evidence=0.5,
        novelty=0.5,
        safety_penalty=0.0,
        evidence_tier="robust",
    )
    speculative = TargetCandidate(
        target_symbol="SPEC",
        target_id="Z",
        centrality=0.5,
        ot_association=0.5,
        druggability=0.5,
        genetic_evidence=0.5,
        novelty=0.5,
        safety_penalty=0.0,
        evidence_tier="speculative",
    )

    ranked = TargetRanker().rank_candidates([speculative, robust])

    assert ranked[0].target_id == "A"


def test_candidate_from_open_targets_association_uses_evidence_fields() -> None:
    association = AssociationEvidence(
        disease_id="EFO_0000311",
        target_id="ENSG00000141510",
        target_symbol="TP53",
        score=0.91,
        tier=EvidenceTier.ROBUST,
        source_breakdown={
            "open_targets": {
                "datatype_scores": {"genetic_association": 0.73},
                "tractability": [{"label": "Small molecule", "value": True}],
            }
        },
    )

    candidate = candidate_from_association(
        association,
        centrality=0.8,
        literature_count=50,
        safety_penalty=0.2,
    )

    assert candidate.target_symbol == "TP53"
    assert candidate.ot_association == 0.91
    assert candidate.druggability == 1.0
    assert candidate.genetic_evidence == 0.73
    assert candidate.evidence_tier == "robust"


def test_novelty_and_druggability_helpers_are_transparent() -> None:
    assert novelty_from_literature_count(0) == 1.0
    assert novelty_from_literature_count(1_000) == 0.5
    assert (
        druggability_from_tractability(
            [
                {"label": "Antibody", "value": True},
                {"label": "Small molecule", "value": False},
                {"label": "PROTAC", "value": 0.5},
            ]
        )
        == 0.8
    )


def test_known_target_benchmark_reports_recovery_by_source() -> None:
    ranked = TargetRanker().rank_candidates(
        [
            TargetCandidate(
                target_symbol="EGFR",
                target_id="ENSG00000146648",
                centrality=1.0,
                ot_association=1.0,
                druggability=1.0,
                genetic_evidence=0.5,
                novelty=0.4,
                safety_penalty=0.0,
                evidence_tier="robust",
            ),
            TargetCandidate(
                target_symbol="WEAK",
                target_id="WEAK",
                centrality=0.1,
                ot_association=0.1,
                druggability=0.1,
                genetic_evidence=0.1,
                novelty=0.1,
                safety_penalty=0.5,
                evidence_tier="speculative",
            ),
        ]
    )

    report = benchmark_known_targets(
        ranked,
        {
            "open_targets": ["ENSG00000146648"],
            "pharos_tcrd": ["ENSG00000146648"],
            "dgidb": ["ENSG00000146648"],
        },
        top_k=1,
    )

    assert report["passed"] is True
    assert report["sources"]["open_targets"]["recall_at_k"] == 1.0
