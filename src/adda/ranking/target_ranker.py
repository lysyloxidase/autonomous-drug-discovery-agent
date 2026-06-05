"""Transparent, explainable multi-criteria target prioritization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from adda.evidence.aggregate import AssociationEvidence

DEFAULT_WEIGHTS: dict[str, float] = {
    "centrality": 0.20,
    "ot_association": 0.25,
    "druggability": 0.20,
    "genetic_evidence": 0.15,
    "novelty": 0.10,
    "safety_penalty": 0.10,
}

TIER_RANK: dict[str, int] = {"robust": 3, "plausible": 2, "speculative": 1}


class TargetCandidate(BaseModel):
    """Transparent target features before weighted ranking."""

    target_symbol: str
    target_id: str
    centrality: float = Field(ge=0.0, le=1.0)
    ot_association: float = Field(ge=0.0, le=1.0)
    druggability: float = Field(ge=0.0, le=1.0)
    genetic_evidence: float = Field(ge=0.0, le=1.0)
    literature_count: int = Field(default=0, ge=0)
    novelty: float | None = Field(default=None, ge=0.0, le=1.0)
    safety_penalty: float = Field(ge=0.0, le=1.0)
    evidence_tier: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TargetScore(BaseModel):
    """Ranked target with all components visible."""

    target_symbol: str
    target_id: str
    centrality: float
    ot_association: float
    druggability: float
    genetic_evidence: float
    novelty: float
    safety_penalty: float
    composite_score: float
    evidence_tier: str
    component_breakdown: dict[str, float]


def clamp01(value: float) -> float:
    """Clamp a numeric value into the 0-1 range."""

    return max(0.0, min(float(value), 1.0))


def novelty_from_literature_count(count: int, *, saturation: int = 1_000) -> float:
    """Score novelty as inverse literature saturation."""

    if count <= 0:
        return 1.0
    if saturation <= 0:
        raise ValueError("saturation must be positive")
    return round(1.0 / (1.0 + count / saturation), 6)


def druggability_from_tractability(
    tractability: Sequence[Mapping[str, Any]],
) -> float:
    """Map Open Targets tractability buckets to a transparent 0-1 score."""

    modality_weights = {
        "small molecule": 1.0,
        "small_molecule": 1.0,
        "sm": 1.0,
        "antibody": 0.8,
        "ab": 0.8,
        "protac": 0.75,
        "other": 0.6,
        "druggable family": 0.7,
    }
    best = 0.0
    for bucket in tractability:
        label = str(bucket.get("label", "")).strip().lower()
        modality = str(bucket.get("modality", "")).strip().lower()
        value = bucket.get("value")
        if value in {False, None, "false", "False"}:
            continue
        score = modality_weights.get(label, modality_weights.get(modality, 0.5))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            score *= clamp01(float(value))
        best = max(best, score)
    return round(clamp01(best), 6)


def candidate_from_association(
    association: AssociationEvidence,
    *,
    centrality: float,
    literature_count: int,
    safety_penalty: float,
    druggability: float | None = None,
) -> TargetCandidate:
    """Create a ranking candidate from Phase 4 evidence output."""

    open_targets = association.source_breakdown.get("open_targets", {})
    datatype_scores = {}
    if isinstance(open_targets, Mapping):
        raw_scores = open_targets.get("datatype_scores", {})
        if isinstance(raw_scores, Mapping):
            datatype_scores = raw_scores
    tractability = (
        open_targets.get("tractability", [])
        if isinstance(open_targets, Mapping)
        else []
    )
    computed_druggability = (
        druggability
        if druggability is not None
        else druggability_from_tractability(
            tractability if isinstance(tractability, Sequence) else []
        )
    )
    genetic = datatype_scores.get("genetic_association", 0.0)
    return TargetCandidate(
        target_symbol=association.target_symbol or association.target_id or "unknown",
        target_id=association.target_id or "unknown",
        centrality=centrality,
        ot_association=association.score,
        druggability=computed_druggability,
        genetic_evidence=float(genetic) if isinstance(genetic, (int, float)) else 0.0,
        literature_count=literature_count,
        safety_penalty=safety_penalty,
        evidence_tier=association.tier.value,
        metadata=association.source_breakdown,
    )


class TargetRanker:
    """Weighted, explainable target prioritizer."""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        *,
        candidates_by_disease: Mapping[str, Sequence[TargetCandidate]] | None = None,
    ) -> None:
        self.weights = dict(DEFAULT_WEIGHTS)
        if weights:
            self.weights.update(weights)
        self._validate_weights(self.weights)
        self.candidates_by_disease = {
            disease_id: list(candidates)
            for disease_id, candidates in (candidates_by_disease or {}).items()
        }

    def rank(self, disease_id: str) -> list[TargetScore]:
        """Return targets sorted by composite score, with breakdowns."""

        return self.rank_candidates(self.candidates_by_disease.get(disease_id, []))

    def rank_candidates(
        self,
        candidates: Sequence[TargetCandidate],
    ) -> list[TargetScore]:
        """Rank an explicit candidate list."""

        scores = [self._score_candidate(candidate) for candidate in candidates]
        return sorted(
            scores,
            key=lambda score: (
                score.composite_score,
                TIER_RANK.get(score.evidence_tier, 0),
                score.target_id,
            ),
            reverse=True,
        )

    def _score_candidate(self, candidate: TargetCandidate) -> TargetScore:
        novelty = (
            candidate.novelty
            if candidate.novelty is not None
            else novelty_from_literature_count(candidate.literature_count)
        )
        components = {
            "centrality": candidate.centrality,
            "ot_association": candidate.ot_association,
            "druggability": candidate.druggability,
            "genetic_evidence": candidate.genetic_evidence,
            "novelty": novelty,
            "safety_penalty": candidate.safety_penalty,
        }
        weighted_positive = sum(
            components[name] * self.weights[name]
            for name in (
                "centrality",
                "ot_association",
                "druggability",
                "genetic_evidence",
                "novelty",
            )
        )
        weighted_safety = components["safety_penalty"] * self.weights["safety_penalty"]
        composite = round(clamp01(weighted_positive - weighted_safety), 6)
        return TargetScore(
            target_symbol=candidate.target_symbol,
            target_id=candidate.target_id,
            centrality=candidate.centrality,
            ot_association=candidate.ot_association,
            druggability=candidate.druggability,
            genetic_evidence=candidate.genetic_evidence,
            novelty=novelty,
            safety_penalty=candidate.safety_penalty,
            composite_score=composite,
            evidence_tier=candidate.evidence_tier,
            component_breakdown={
                **components,
                "weighted_centrality": candidate.centrality
                * self.weights["centrality"],
                "weighted_ot_association": candidate.ot_association
                * self.weights["ot_association"],
                "weighted_druggability": candidate.druggability
                * self.weights["druggability"],
                "weighted_genetic_evidence": candidate.genetic_evidence
                * self.weights["genetic_evidence"],
                "weighted_novelty": novelty * self.weights["novelty"],
                "weighted_safety_penalty": weighted_safety,
            },
        )

    @staticmethod
    def _validate_weights(weights: Mapping[str, float]) -> None:
        missing = set(DEFAULT_WEIGHTS) - set(weights)
        if missing:
            raise ValueError(f"missing ranking weights: {sorted(missing)}")
        for name, value in weights.items():
            if value < 0:
                raise ValueError(f"ranking weight must be non-negative: {name}")


def benchmark_known_targets(
    ranked_targets: Sequence[TargetScore],
    known_targets_by_source: Mapping[str, Sequence[str]],
    *,
    top_k: int = 10,
) -> dict[str, Any]:
    """Validate known targets from Open Targets, Pharos/TCRD, and DGIdb."""

    top_ids = [target.target_id for target in ranked_targets[:top_k]]
    source_results: dict[str, dict[str, Any]] = {}
    for source, known_targets in known_targets_by_source.items():
        known = list(known_targets)
        recovered = [target_id for target_id in known if target_id in top_ids]
        source_results[source] = {
            "known_targets": known,
            "recovered": recovered,
            "recall_at_k": len(recovered) / len(known) if known else 0.0,
            "passed": all(target_id in top_ids for target_id in known),
        }
    return {
        "top_k": top_k,
        "top_target_ids": top_ids,
        "sources": source_results,
        "passed": all(result["passed"] for result in source_results.values()),
    }
