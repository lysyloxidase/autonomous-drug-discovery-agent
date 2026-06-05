from __future__ import annotations

from adda.extraction.models import Entity, EntityType, Relation, RelationType
from adda.kg.schema import (
    MISSING_PROVENANCE_QUERY,
    NODE_CONSTRAINTS,
    PLUGIN_CHECK_QUERY,
    KGRelationType,
    NodeLabel,
    entity_to_node,
    mention_edges,
    provenance_from_relation,
    publication_node,
    relation_to_edge,
)


def entity(
    text: str,
    entity_type: EntityType,
    normalized_id: str,
    *,
    extractor: str = "pubtator3",
) -> Entity:
    ontology = {
        EntityType.DISEASE: "MeSH",
        EntityType.GENE: "NCBI Gene",
        EntityType.CHEMICAL: "ChEMBL",
        EntityType.PATHWAY: "Reactome",
        EntityType.PHENOTYPE: "HPO",
        EntityType.VARIANT: "dbSNP",
    }.get(entity_type, "unknown")
    return Entity(
        text=text,
        entity_type=entity_type,
        normalized_id=normalized_id,
        ontology=ontology,
        source_pmids=["1"],
        extractor=extractor,
        confidence=0.87,
    )


def relation(
    subject: Entity,
    relation_type: RelationType,
    object_entity: Entity,
) -> Relation:
    return Relation(
        subject=subject,
        relation=relation_type,
        object=object_entity,
        source_pmids=["1"],
        extractor=subject.extractor,
        confidence=0.87,
    )


def test_schema_constraints_and_plugin_queries_cover_core_requirements() -> None:
    assert len(NODE_CONSTRAINTS) == len(NodeLabel)
    assert any("FOR (n:Disease) REQUIRE n.id IS UNIQUE" in q for q in NODE_CONSTRAINTS)
    assert "apoc.version()" in PLUGIN_CHECK_QUERY
    assert "gds.version()" in PLUGIN_CHECK_QUERY
    assert "r.source_pmids IS NULL" in MISSING_PROVENANCE_QUERY


def test_entity_and_publication_nodes_use_business_keys() -> None:
    disease = entity("glioblastoma", EntityType.DISEASE, "D005909")
    drug = entity("imatinib", EntityType.CHEMICAL, "CHEMBL941")
    publication = publication_node("12345")

    disease_node = entity_to_node(disease)
    drug_node = entity_to_node(drug)

    assert disease_node is not None
    assert disease_node.label is NodeLabel.DISEASE
    assert disease_node.id == "D005909"
    assert drug_node is not None
    assert drug_node.label is NodeLabel.DRUG
    assert publication.label is NodeLabel.PUBLICATION
    assert publication.id == "12345"


def test_relation_mapping_creates_schema_edges_with_full_provenance() -> None:
    disease = entity("glioblastoma", EntityType.DISEASE, "D005909")
    gene = entity("TP53", EntityType.GENE, "7157")
    drug = entity("imatinib", EntityType.CHEMICAL, "CHEMBL941")
    pathway = entity("p53 signaling", EntityType.PATHWAY, "R-HSA-69541")
    phenotype = entity("apoptosis", EntityType.PHENOTYPE, "HP:0000001")

    edges = [
        relation_to_edge(relation(disease, RelationType.ASSOCIATE, gene)),
        relation_to_edge(relation(drug, RelationType.INHIBIT, gene)),
        relation_to_edge(relation(gene, RelationType.ASSOCIATE, pathway)),
        relation_to_edge(relation(drug, RelationType.TREAT, disease)),
        relation_to_edge(relation(gene, RelationType.CAUSE, phenotype)),
    ]

    assert [edge.relation_type if edge else None for edge in edges] == [
        KGRelationType.ASSOCIATED_WITH,
        KGRelationType.TARGETS,
        KGRelationType.PARTICIPATES_IN,
        KGRelationType.TREATS,
        KGRelationType.CAUSES,
    ]
    for edge in edges:
        assert edge is not None
        props = edge.provenance.to_neo4j_properties()
        assert set(props) == {
            "source_pmids",
            "extraction_confidence",
            "evidence_tier",
            "source_db",
            "created_at",
            "extractor_version",
        }
        assert props["source_pmids"] == ["1"]


def test_relation_mapping_reverses_direction_to_match_schema() -> None:
    disease = entity("glioblastoma", EntityType.DISEASE, "D005909")
    gene = entity("TP53", EntityType.GENE, "7157")

    edge = relation_to_edge(relation(gene, RelationType.ASSOCIATE, disease))

    assert edge is not None
    assert edge.source_label is NodeLabel.DISEASE
    assert edge.source_id == "D005909"
    assert edge.target_label is NodeLabel.GENE
    assert edge.target_id == "7157"


def test_mentions_edges_and_provenance_from_relation() -> None:
    gene = entity("TP53", EntityType.GENE, "7157", extractor="local_llm")
    gene_relation = relation(gene, RelationType.ASSOCIATE, gene)

    mentions = mention_edges(gene)
    provenance = provenance_from_relation(gene_relation)

    assert len(mentions) == 1
    assert mentions[0].source_label is NodeLabel.PUBLICATION
    assert mentions[0].relation_type is KGRelationType.MENTIONS
    assert mentions[0].provenance.source_db == "local_llm"
    assert provenance.evidence_tier == ""
    assert provenance.source_db == "local_llm"
