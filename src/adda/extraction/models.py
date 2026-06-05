"""Entity and relation models for biomedical extraction."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EntityType(StrEnum):
    """Supported biomedical entity classes."""

    GENE = "gene"
    DISEASE = "disease"
    CHEMICAL = "chemical"
    VARIANT = "variant"
    SPECIES = "species"
    CELL_LINE = "cell_line"
    PATHWAY = "pathway"
    PHENOTYPE = "phenotype"


class Entity(BaseModel):
    """A normalized entity mention."""

    text: str
    entity_type: EntityType
    normalized_id: str
    ontology: str
    source_pmids: list[str] = Field(default_factory=list)
    extractor: str
    confidence: float = Field(ge=0.0, le=1.0)


class RelationType(StrEnum):
    """PubTator3 relation types plus KG-specific relation labels."""

    TREAT = "treat"
    CAUSE = "cause"
    COTREAT = "cotreat"
    CONVERT = "convert"
    COMPARE = "compare"
    INTERACT = "interact"
    ASSOCIATE = "associate"
    POSITIVE_CORRELATE = "positive_correlate"
    NEGATIVE_CORRELATE = "negative_correlate"
    PREVENT = "prevent"
    INHIBIT = "inhibit"
    STIMULATE = "stimulate"
    DRUG_INTERACT = "drug_interact"


class Relation(BaseModel):
    """A typed relation between two normalized entities."""

    subject: Entity
    relation: RelationType
    object: Entity
    source_pmids: list[str] = Field(default_factory=list)
    extractor: str
    confidence: float = Field(ge=0.0, le=1.0)
    is_cooccurrence_only: bool = False


class ExtractionResult(BaseModel):
    """Entities and relations extracted from one or more documents."""

    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
