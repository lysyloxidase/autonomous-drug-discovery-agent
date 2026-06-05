from __future__ import annotations

from adda.evidence.tiering import (
    EvidenceTier,
    classify_evidence,
    classify_relation_edge,
)
from adda.extraction.models import Entity, EntityType, Relation, RelationType


def entity(text: str, entity_type: EntityType, normalized_id: str) -> Entity:
    return Entity(
        text=text,
        entity_type=entity_type,
        normalized_id=normalized_id,
        ontology="MeSH" if entity_type is EntityType.DISEASE else "NCBI Gene",
        source_pmids=["1"],
        extractor="pubtator3",
        confidence=0.8,
    )


def relation(
    *,
    extractor: str = "pubtator3",
    cooccurrence: bool = False,
) -> Relation:
    disease = entity("glioblastoma", EntityType.DISEASE, "EFO_0000519")
    gene = entity("TP53", EntityType.GENE, "ENSG00000141510")
    return Relation(
        subject=disease,
        relation=RelationType.ASSOCIATE,
        object=gene,
        source_pmids=["1"],
        extractor=extractor,
        confidence=0.7,
        is_cooccurrence_only=cooccurrence,
    )


def test_genetic_evidence_is_robust() -> None:
    tier, breakdown = classify_evidence(
        {"datatype_scores": {"genetic_association": 0.72}},
        [],
        False,
    )

    assert tier is EvidenceTier.ROBUST
    assert "human genetic evidence" in breakdown["reasons"][0]


def test_known_drug_indication_is_robust() -> None:
    tier, breakdown = classify_evidence(None, [], True)

    assert tier is EvidenceTier.ROBUST
    assert breakdown["criteria"]["has_known_drug"] is True


def test_two_independent_datatypes_are_robust() -> None:
    tier, breakdown = classify_evidence(
        {"datatype_scores": {"somatic_mutation": 0.4, "rna_expression": 0.3}},
        [],
        False,
    )

    assert tier is EvidenceTier.ROBUST
    assert breakdown["criteria"]["has_replication"] is True


def test_animal_model_plus_pathway_is_plausible() -> None:
    tier, breakdown = classify_evidence(
        {"datatype_scores": {"animal_model": 0.6, "affected_pathway": 0.7}},
        [],
        False,
    )

    assert tier is EvidenceTier.PLAUSIBLE
    assert "animal model" in breakdown["reasons"][0]


def test_typed_pubtator_with_mechanistic_support_is_plausible() -> None:
    tier, breakdown = classify_evidence(
        {"datatype_scores": {"affected_pathway": 0.7}},
        [relation()],
        False,
    )

    assert tier is EvidenceTier.PLAUSIBLE
    assert breakdown["criteria"]["has_typed_pubtator_relation"] is True


def test_cooccurrence_and_local_llm_only_are_forced_speculative() -> None:
    cooccurrence_relation = relation(cooccurrence=True)
    llm_relation = relation(extractor="local_llm")

    cooccurrence_tier, cooccurrence_breakdown = classify_evidence(
        None,
        [cooccurrence_relation],
        False,
    )
    llm_tier, _ = classify_evidence(None, [llm_relation], False)

    assert cooccurrence_tier is EvidenceTier.SPECULATIVE
    assert llm_tier is EvidenceTier.SPECULATIVE
    assert cooccurrence_breakdown["criteria"]["all_relations_speculative"] is True
    assert classify_relation_edge(cooccurrence_relation) is EvidenceTier.SPECULATIVE
    assert classify_relation_edge(llm_relation) is EvidenceTier.SPECULATIVE
    assert classify_relation_edge(relation()) is EvidenceTier.PLAUSIBLE
