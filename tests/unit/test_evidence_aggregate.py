from __future__ import annotations

import math
from typing import Any

from adda.evidence.aggregate import (
    EVIDENCE_TIER_WRITEBACK_QUERY,
    MAX_THEORETICAL_HARMONIC_SUM,
    AssociationEvidence,
    EvidenceTierUpdate,
    aggregate_association,
    aggregate_datatype_scores,
    harmonic_sum_score,
    rank_associations,
    validate_known_top_targets,
    write_evidence_tiers_to_kg,
)
from adda.evidence.tiering import EvidenceTier


class FakeDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute_query(
        self, query: str, *, parameters_: dict[str, Any]
    ) -> list[dict[str, int]]:
        self.calls.append((query, parameters_))
        return [{"updated": len(parameters_["updates"])}]


def test_harmonic_sum_matches_hand_computed_reference() -> None:
    expected = (1.0 / 1**2 + 0.9 / 2**2 + 0.8 / 3**2) / (
        sum(1.0 / (index**2) for index in range(1, 1001))
    )

    assert harmonic_sum_score([1.0, 0.9, 0.8]) == round(expected, 6)
    assert math.isclose(MAX_THEORETICAL_HARMONIC_SUM, 1.644, rel_tol=0.001)


def test_harmonic_sum_validates_weights_and_aggregate_datatypes() -> None:
    assert harmonic_sum_score([0.5, 0.5], weights=[1.0, 0.5]) > 0
    assert aggregate_datatype_scores({"literature": 1.0, "animal_model": 0.5}) > 0

    try:
        harmonic_sum_score([0.5], weights=[1.0, 0.5])
    except ValueError as exc:
        assert "same length" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError")


def test_aggregate_association_carries_tier_and_source_breakdown() -> None:
    evidence = aggregate_association(
        {
            "disease_id": "EFO_0000519",
            "target_id": "ENSG00000141510",
            "target_symbol": "TP53",
            "datatype_scores": {"genetic_association": 0.8},
        },
        [],
    )

    assert evidence.tier is EvidenceTier.ROBUST
    assert evidence.score > 0
    assert evidence.source_breakdown["classification"]["criteria"][
        "has_genetic_evidence"
    ]


def test_validation_gate_reproduces_known_open_targets_top_targets() -> None:
    ranked = rank_associations(
        [
            AssociationEvidence(
                target_id="B",
                score=0.2,
                tier=EvidenceTier.PLAUSIBLE,
                source_breakdown={},
            ),
            AssociationEvidence(
                target_id="A",
                score=0.9,
                tier=EvidenceTier.ROBUST,
                source_breakdown={},
            ),
        ]
    )

    result = validate_known_top_targets(ranked, ["A"], top_k=1)

    assert ranked[0].target_id == "A"
    assert result["passed"] is True
    assert result["recall_at_k"] == 1.0


def test_write_evidence_tiers_to_kg_updates_neo4j_edges() -> None:
    driver = FakeDriver()

    updated = write_evidence_tiers_to_kg(
        driver,
        [
            EvidenceTierUpdate(
                source_id="EFO_0000519",
                target_id="ENSG00000141510",
                relation_type="ASSOCIATED_WITH",
                evidence_tier=EvidenceTier.ROBUST,
                evidence_score=0.88,
                source_breakdown={"why": "genetics"},
            )
        ],
    )

    assert updated == 1
    query, params = driver.calls[0]
    assert query == EVIDENCE_TIER_WRITEBACK_QUERY
    assert params["updates"][0]["evidence_tier"] == "robust"
    assert params["updates"][0]["source_breakdown"] == {"why": "genetics"}


def test_write_evidence_tiers_noops_on_empty_updates() -> None:
    assert write_evidence_tiers_to_kg(FakeDriver(), []) == 0
