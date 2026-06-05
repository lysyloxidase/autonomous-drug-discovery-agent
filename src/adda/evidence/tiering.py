"""3-tier evidence classification with explicit honesty rules."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from adda.evidence.opentargets import OpenTargetsAssociation, normalize_datatype_id
from adda.extraction.models import Relation


class EvidenceTier(StrEnum):
    """Evidence-strength tiers used downstream in KG and reports."""

    ROBUST = "robust"
    PLAUSIBLE = "plausible"
    SPECULATIVE = "speculative"


ROBUST_DATATYPES = {"genetic_association", "known_drug"}
REPLICATING_DATATYPES = {
    "genetic_association",
    "somatic_mutation",
    "known_drug",
    "affected_pathway",
    "rna_expression",
    "animal_model",
    "literature",
}


def _association_dict(
    ot_association: dict[str, Any] | OpenTargetsAssociation | None,
) -> dict[str, Any]:
    if ot_association is None:
        return {}
    if isinstance(ot_association, OpenTargetsAssociation):
        return ot_association.model_dump_for_breakdown()
    return dict(ot_association)


def _datatype_scores(association: dict[str, Any]) -> dict[str, float]:
    raw = association.get("datatype_scores") or association.get("datatypeScores") or {}
    if not isinstance(raw, dict):
        return {}
    return {
        normalize_datatype_id(str(key)): float(value)
        for key, value in raw.items()
        if isinstance(value, (int, float)) and value > 0
    }


def _independent_datatypes(datatype_scores: dict[str, float]) -> list[str]:
    return sorted(
        datatype
        for datatype in REPLICATING_DATATYPES
        if datatype_scores.get(datatype, 0.0) > 0
    )


def _all_relations_speculative(relations: list[Relation]) -> bool:
    if not relations:
        return False
    return all(
        relation.is_cooccurrence_only or relation.extractor == "local_llm"
        for relation in relations
    )


def _has_replicated_non_preclinical_datatypes(datatypes: list[str]) -> bool:
    if len(datatypes) < 2:
        return False
    preclinical_only = {"animal_model", "affected_pathway", "rna_expression"}
    return not set(datatypes).issubset(preclinical_only)


def _has_typed_pubtator_relation(relations: list[Relation]) -> bool:
    return any(
        relation.extractor == "pubtator3" and not relation.is_cooccurrence_only
        for relation in relations
    )


def classify_evidence(
    ot_association: dict[str, Any] | OpenTargetsAssociation | None,
    kg_relations: list[Relation],
    has_known_drug: bool,
) -> tuple[EvidenceTier, dict[str, Any]]:
    """Return the evidence tier plus explicit per-criterion reasoning."""

    association = _association_dict(ot_association)
    datatype_scores = _datatype_scores(association)
    independent_datatypes = _independent_datatypes(datatype_scores)
    relation_flags = [
        {
            "extractor": relation.extractor,
            "is_cooccurrence_only": relation.is_cooccurrence_only,
            "relation": relation.relation.value,
            "source_pmids": relation.source_pmids,
        }
        for relation in kg_relations
    ]

    criteria = {
        "has_genetic_evidence": datatype_scores.get("genetic_association", 0.0) > 0,
        "has_known_drug": has_known_drug
        or bool(association.get("known_drug"))
        or datatype_scores.get("known_drug", 0.0) > 0,
        "independent_datatypes": independent_datatypes,
        "has_replication": _has_replicated_non_preclinical_datatypes(
            independent_datatypes
        ),
        "has_animal_model": datatype_scores.get("animal_model", 0.0) > 0,
        "has_pathway_or_expression": datatype_scores.get("affected_pathway", 0.0) > 0
        or datatype_scores.get("rna_expression", 0.0) > 0,
        "has_typed_pubtator_relation": _has_typed_pubtator_relation(kg_relations),
        "all_relations_speculative": _all_relations_speculative(kg_relations),
        "relation_flags": relation_flags,
    }

    reasons: list[str] = []
    if criteria["has_genetic_evidence"]:
        reasons.append("human genetic evidence from Open Targets")
    if criteria["has_known_drug"]:
        reasons.append("known drug or approved indication signal")
    if criteria["has_replication"]:
        reasons.append("two or more independent Open Targets datatypes")
    if reasons:
        return (
            EvidenceTier.ROBUST,
            {
                "criteria": criteria,
                "reasons": reasons,
                "datatype_scores": datatype_scores,
            },
        )

    plausible_reasons: list[str] = []
    if criteria["has_animal_model"] and criteria["has_pathway_or_expression"]:
        plausible_reasons.append("animal model plus pathway or expression evidence")
    if criteria["has_typed_pubtator_relation"] and (
        datatype_scores.get("affected_pathway", 0.0) > 0
        or datatype_scores.get("literature", 0.0) >= 0.5
    ):
        plausible_reasons.append("typed PubTator relation with mechanistic support")
    if plausible_reasons and not criteria["all_relations_speculative"]:
        return (
            EvidenceTier.PLAUSIBLE,
            {
                "criteria": criteria,
                "reasons": plausible_reasons,
                "datatype_scores": datatype_scores,
            },
        )

    reasons = ["literature co-occurrence, single-source, or unverified LLM evidence"]
    return (
        EvidenceTier.SPECULATIVE,
        {"criteria": criteria, "reasons": reasons, "datatype_scores": datatype_scores},
    )


def classify_relation_edge(relation: Relation) -> EvidenceTier:
    """Classify one KG relation edge before stronger database support is added."""

    if relation.is_cooccurrence_only or relation.extractor == "local_llm":
        return EvidenceTier.SPECULATIVE
    if relation.extractor == "pubtator3":
        return EvidenceTier.PLAUSIBLE
    return EvidenceTier.SPECULATIVE
