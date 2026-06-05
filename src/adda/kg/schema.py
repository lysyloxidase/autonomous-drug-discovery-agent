"""Neo4j property-graph schema and Phase 2 extraction mappers."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from adda._version import __version__
from adda.extraction.models import Entity, EntityType, Relation, RelationType


class NodeLabel(StrEnum):
    """Neo4j node labels used by the knowledge graph."""

    DISEASE = "Disease"
    GENE = "Gene"
    PATHWAY = "Pathway"
    DRUG = "Drug"
    PHENOTYPE = "Phenotype"
    VARIANT = "Variant"
    PUBLICATION = "Publication"


class KGRelationType(StrEnum):
    """Neo4j relationship types used by the knowledge graph."""

    ASSOCIATED_WITH = "ASSOCIATED_WITH"
    TARGETS = "TARGETS"
    PARTICIPATES_IN = "PARTICIPATES_IN"
    TREATS = "TREATS"
    CAUSES = "CAUSES"
    CONTRIBUTES_TO = "CONTRIBUTES_TO"
    MENTIONS = "MENTIONS"


class EdgeProvenance(BaseModel):
    """Required provenance properties for every graph edge."""

    source_pmids: list[str] = Field(default_factory=list)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    evidence_tier: str = ""
    source_db: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    extractor_version: str = __version__

    def to_neo4j_properties(self) -> dict[str, Any]:
        """Serialize provenance for Neo4j relationship properties."""

        return {
            "source_pmids": self.source_pmids,
            "extraction_confidence": self.extraction_confidence,
            "evidence_tier": self.evidence_tier,
            "source_db": self.source_db,
            "created_at": self.created_at.isoformat(),
            "extractor_version": self.extractor_version,
        }


class KGNode(BaseModel):
    """A Neo4j node row for APOC loading."""

    label: NodeLabel
    id: str
    name: str
    ontology: str | None = None
    entity_type: str | None = None

    def to_loader_row(self) -> dict[str, Any]:
        """Serialize as an APOC node loader row."""

        props = {
            "id": self.id,
            "name": self.name,
            "ontology": self.ontology,
            "entity_type": self.entity_type,
        }
        return {
            "label": self.label.value,
            "id": self.id,
            "props": {key: value for key, value in props.items() if value is not None},
        }


class KGEdge(BaseModel):
    """A Neo4j relationship row for APOC loading."""

    source_label: NodeLabel
    source_id: str
    target_label: NodeLabel
    target_id: str
    relation_type: KGRelationType
    provenance: EdgeProvenance

    def to_loader_row(self) -> dict[str, Any]:
        """Serialize as an APOC relationship loader row."""

        return {
            "source_label": self.source_label.value,
            "source_id": self.source_id,
            "target_label": self.target_label.value,
            "target_id": self.target_id,
            "type": self.relation_type.value,
            "props": self.provenance.to_neo4j_properties(),
        }


NODE_CONSTRAINTS: tuple[str, ...] = tuple(
    f"CREATE CONSTRAINT {label.value.lower()}_id IF NOT EXISTS "
    f"FOR (n:{label.value}) REQUIRE n.id IS UNIQUE"
    for label in NodeLabel
)

PLUGIN_CHECK_QUERY = (
    "RETURN apoc.version() AS apoc_version, gds.version() AS gds_version"
)

MISSING_PROVENANCE_QUERY = """
MATCH ()-[r]->()
WHERE r.source_pmids IS NULL
   OR r.extraction_confidence IS NULL
   OR r.evidence_tier IS NULL
   OR r.source_db IS NULL
   OR r.created_at IS NULL
   OR r.extractor_version IS NULL
RETURN count(r) AS missing_count
"""

DISEASE_GENE_PROVENANCE_QUERY = """
MATCH (d:Disease)-[r:ASSOCIATED_WITH]->(g:Gene)
RETURN d.id AS disease_id,
       g.id AS gene_id,
       r.source_pmids AS source_pmids,
       r.extraction_confidence AS extraction_confidence,
       r.evidence_tier AS evidence_tier,
       r.source_db AS source_db,
       r.created_at AS created_at,
       r.extractor_version AS extractor_version
"""


def entity_label(entity_type: EntityType) -> NodeLabel | None:
    """Map Phase 2 entity types to KG node labels."""

    return {
        EntityType.DISEASE: NodeLabel.DISEASE,
        EntityType.GENE: NodeLabel.GENE,
        EntityType.CHEMICAL: NodeLabel.DRUG,
        EntityType.PATHWAY: NodeLabel.PATHWAY,
        EntityType.PHENOTYPE: NodeLabel.PHENOTYPE,
        EntityType.VARIANT: NodeLabel.VARIANT,
    }.get(entity_type)


def entity_to_node(entity: Entity) -> KGNode | None:
    """Convert an extracted entity into a KG node."""

    label = entity_label(entity.entity_type)
    if label is None:
        return None
    return KGNode(
        label=label,
        id=entity.normalized_id,
        name=entity.text,
        ontology=entity.ontology,
        entity_type=entity.entity_type.value,
    )


def publication_node(pmid: str) -> KGNode:
    """Create a publication node from a PMID."""

    return KGNode(label=NodeLabel.PUBLICATION, id=pmid, name=f"PMID:{pmid}")


def provenance_from_relation(relation: Relation) -> EdgeProvenance:
    """Build required provenance from a Phase 2 relation."""

    return EdgeProvenance(
        source_pmids=sorted(set(relation.source_pmids)),
        extraction_confidence=relation.confidence,
        evidence_tier="",
        source_db=relation.extractor,
        extractor_version=__version__,
    )


def _relation_for_labels(
    relation: Relation,
    subject_label: NodeLabel,
    object_label: NodeLabel,
) -> tuple[NodeLabel, Entity, KGRelationType, NodeLabel, Entity] | None:
    subject = relation.subject
    object_entity = relation.object
    if subject_label is NodeLabel.DISEASE and object_label is NodeLabel.GENE:
        return (
            subject_label,
            subject,
            KGRelationType.ASSOCIATED_WITH,
            object_label,
            object_entity,
        )
    if subject_label is NodeLabel.GENE and object_label is NodeLabel.DISEASE:
        return (
            object_label,
            object_entity,
            KGRelationType.ASSOCIATED_WITH,
            subject_label,
            subject,
        )
    if subject_label is NodeLabel.DRUG and object_label is NodeLabel.GENE:
        return (
            subject_label,
            subject,
            KGRelationType.TARGETS,
            object_label,
            object_entity,
        )
    if subject_label is NodeLabel.GENE and object_label is NodeLabel.DRUG:
        return (
            object_label,
            object_entity,
            KGRelationType.TARGETS,
            subject_label,
            subject,
        )
    if subject_label is NodeLabel.GENE and object_label is NodeLabel.PATHWAY:
        return (
            subject_label,
            subject,
            KGRelationType.PARTICIPATES_IN,
            object_label,
            object_entity,
        )
    if subject_label is NodeLabel.PATHWAY and object_label is NodeLabel.GENE:
        return (
            object_label,
            object_entity,
            KGRelationType.PARTICIPATES_IN,
            subject_label,
            subject,
        )
    if subject_label is NodeLabel.DRUG and object_label is NodeLabel.DISEASE:
        return (
            subject_label,
            subject,
            KGRelationType.TREATS,
            object_label,
            object_entity,
        )
    if subject_label is NodeLabel.DISEASE and object_label is NodeLabel.DRUG:
        return (
            object_label,
            object_entity,
            KGRelationType.TREATS,
            subject_label,
            subject,
        )
    if subject_label is NodeLabel.GENE and object_label is NodeLabel.PHENOTYPE:
        relation_type = (
            KGRelationType.CAUSES
            if relation.relation is RelationType.CAUSE
            else KGRelationType.CONTRIBUTES_TO
        )
        return subject_label, subject, relation_type, object_label, object_entity
    if subject_label is NodeLabel.PHENOTYPE and object_label is NodeLabel.GENE:
        relation_type = (
            KGRelationType.CAUSES
            if relation.relation is RelationType.CAUSE
            else KGRelationType.CONTRIBUTES_TO
        )
        return object_label, object_entity, relation_type, subject_label, subject
    return None


def relation_to_edge(relation: Relation) -> KGEdge | None:
    """Map a Phase 2 relation to a schema-valid KG edge."""

    subject_label = entity_label(relation.subject.entity_type)
    object_label = entity_label(relation.object.entity_type)
    if subject_label is None or object_label is None:
        return None
    mapped = _relation_for_labels(relation, subject_label, object_label)
    if mapped is None:
        return None
    source_label, source_entity, relation_type, target_label, target_entity = mapped
    return KGEdge(
        source_label=source_label,
        source_id=source_entity.normalized_id,
        target_label=target_label,
        target_id=target_entity.normalized_id,
        relation_type=relation_type,
        provenance=provenance_from_relation(relation),
    )


def mention_edges(entity: Entity) -> list[KGEdge]:
    """Create Publication-[:MENTIONS]->Entity edges for source PMIDs."""

    target_label = entity_label(entity.entity_type)
    if target_label is None:
        return []
    return [
        KGEdge(
            source_label=NodeLabel.PUBLICATION,
            source_id=pmid,
            target_label=target_label,
            target_id=entity.normalized_id,
            relation_type=KGRelationType.MENTIONS,
            provenance=EdgeProvenance(
                source_pmids=[pmid],
                extraction_confidence=entity.confidence,
                evidence_tier="",
                source_db=entity.extractor,
            ),
        )
        for pmid in sorted(set(entity.source_pmids))
    ]
