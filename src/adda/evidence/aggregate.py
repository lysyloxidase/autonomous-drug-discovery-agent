"""Aggregate evidence scores and write evidence tiers back to KG edges."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from adda.evidence.opentargets import OpenTargetsAssociation
from adda.evidence.tiering import EvidenceTier, classify_evidence
from adda.extraction.models import Relation

MAX_THEORETICAL_HARMONIC_SUM = sum(1.0 / (index**2) for index in range(1, 1001))


class AssociationEvidence(BaseModel):
    """Aggregated, explainable evidence for one target-disease association."""

    disease_id: str | None = None
    target_id: str | None = None
    target_symbol: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    tier: EvidenceTier
    source_breakdown: dict[str, Any]


class EvidenceTierUpdate(BaseModel):
    """Neo4j edge evidence update payload."""

    source_id: str
    target_id: str
    relation_type: str
    evidence_tier: EvidenceTier
    evidence_score: float = Field(ge=0.0, le=1.0)
    source_breakdown: dict[str, Any] = Field(default_factory=dict)


EVIDENCE_TIER_WRITEBACK_QUERY = """
UNWIND $updates AS update
MATCH (source {id: update.source_id})-[r]->(target {id: update.target_id})
WHERE type(r) = update.relation_type
SET r.evidence_tier = update.evidence_tier,
    r.evidence_score = update.evidence_score,
    r.evidence_breakdown = update.source_breakdown
RETURN count(r) AS updated
"""


def harmonic_sum_score(
    scores: Sequence[float],
    *,
    weights: Sequence[float] | None = None,
    normalizer: float = MAX_THEORETICAL_HARMONIC_SUM,
) -> float:
    """Combine evidence scores using Open Targets-style harmonic ranking."""

    if weights is not None and len(weights) != len(scores):
        raise ValueError("weights must have the same length as scores")
    weighted_scores = [
        max(0.0, min(float(score), 1.0))
        * (float(weights[index]) if weights is not None else 1.0)
        for index, score in enumerate(scores)
    ]
    weighted_scores = sorted(weighted_scores, reverse=True)
    harmonic = sum(
        score / (position**2) for position, score in enumerate(weighted_scores, start=1)
    )
    if normalizer <= 0:
        raise ValueError("normalizer must be positive")
    return round(max(0.0, min(harmonic / normalizer, 1.0)), 6)


def aggregate_datatype_scores(datatype_scores: dict[str, float]) -> float:
    """Aggregate Open Targets datatype scores into one normalized score."""

    return harmonic_sum_score(list(datatype_scores.values()))


def aggregate_association(
    ot_association: dict[str, Any] | OpenTargetsAssociation | None,
    kg_relations: Sequence[Relation],
    *,
    has_known_drug: bool = False,
) -> AssociationEvidence:
    """Aggregate Open Targets and KG evidence into one explainable record."""

    association_dict = (
        ot_association.model_dump_for_breakdown()
        if isinstance(ot_association, OpenTargetsAssociation)
        else dict(ot_association or {})
    )
    datatype_scores = association_dict.get("datatype_scores", {})
    if not isinstance(datatype_scores, dict):
        datatype_scores = {}
    raw_overall_score = association_dict.get("overall_score")
    score = (
        float(raw_overall_score)
        if isinstance(raw_overall_score, (int, float))
        else aggregate_datatype_scores(
            {
                str(key): float(value)
                for key, value in datatype_scores.items()
                if isinstance(value, (int, float))
            }
        )
    )
    tier, breakdown = classify_evidence(
        ot_association,
        list(kg_relations),
        has_known_drug,
    )
    source_breakdown = {
        "open_targets": association_dict,
        "classification": breakdown,
        "kg_relation_count": len(kg_relations),
    }
    return AssociationEvidence(
        disease_id=association_dict.get("disease_id")
        if isinstance(association_dict.get("disease_id"), str)
        else None,
        target_id=association_dict.get("target_id")
        if isinstance(association_dict.get("target_id"), str)
        else None,
        target_symbol=association_dict.get("target_symbol")
        if isinstance(association_dict.get("target_symbol"), str)
        else None,
        score=max(0.0, min(score, 1.0)),
        tier=tier,
        source_breakdown=source_breakdown,
    )


def rank_associations(
    associations: Sequence[AssociationEvidence],
) -> list[AssociationEvidence]:
    """Sort associations by tier strength and score."""

    tier_rank = {
        EvidenceTier.ROBUST: 3,
        EvidenceTier.PLAUSIBLE: 2,
        EvidenceTier.SPECULATIVE: 1,
    }
    return sorted(
        associations,
        key=lambda item: (tier_rank[item.tier], item.score, item.target_id or ""),
        reverse=True,
    )


def validate_known_top_targets(
    ranked: Sequence[AssociationEvidence],
    known_target_ids: Sequence[str],
    *,
    top_k: int = 10,
) -> dict[str, Any]:
    """Check whether known Open Targets top targets are reproduced."""

    top_ids = [item.target_id for item in ranked[:top_k] if item.target_id]
    known = list(known_target_ids)
    overlap = [target_id for target_id in known if target_id in top_ids]
    return {
        "top_k": top_k,
        "known_target_ids": known,
        "observed_top_target_ids": top_ids,
        "overlap": overlap,
        "recall_at_k": len(overlap) / len(known) if known else math.nan,
        "passed": all(target_id in top_ids for target_id in known),
    }


def write_evidence_tiers_to_kg(
    driver: Any, updates: Sequence[EvidenceTierUpdate]
) -> int:
    """Write evidence tier and score properties back onto Neo4j edges."""

    if not updates:
        return 0
    rows = [
        {
            "source_id": update.source_id,
            "target_id": update.target_id,
            "relation_type": update.relation_type,
            "evidence_tier": update.evidence_tier.value,
            "evidence_score": update.evidence_score,
            "source_breakdown": update.source_breakdown,
        }
        for update in updates
    ]
    result = driver.execute_query(
        EVIDENCE_TIER_WRITEBACK_QUERY,
        parameters_={"updates": rows},
    )
    records = result[0] if isinstance(result, tuple) else result
    if not records:
        return 0
    value = dict(records[0]).get("updated", 0)
    return int(value) if isinstance(value, int) else 0
