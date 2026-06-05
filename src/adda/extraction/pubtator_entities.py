"""Primary entity path: PubTator3 annotations as ground truth."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from adda.extraction.grounding import infer_ontology
from adda.extraction.models import (
    Entity,
    EntityType,
    ExtractionResult,
    Relation,
    RelationType,
)

PUBTATOR_EXTRACTOR = "pubtator3"

_ENTITY_TYPE_ALIASES: dict[str, EntityType] = {
    "gene": EntityType.GENE,
    "genes": EntityType.GENE,
    "gene/protein": EntityType.GENE,
    "protein": EntityType.GENE,
    "disease": EntityType.DISEASE,
    "diseases": EntityType.DISEASE,
    "chemical": EntityType.CHEMICAL,
    "chemicals": EntityType.CHEMICAL,
    "variant": EntityType.VARIANT,
    "variants": EntityType.VARIANT,
    "mutation": EntityType.VARIANT,
    "species": EntityType.SPECIES,
    "organism": EntityType.SPECIES,
    "cell line": EntityType.CELL_LINE,
    "cell_line": EntityType.CELL_LINE,
    "cellline": EntityType.CELL_LINE,
    "pathway": EntityType.PATHWAY,
    "phenotype": EntityType.PHENOTYPE,
}

_RELATION_TYPE_ALIASES: dict[str, RelationType] = {
    relation.value: relation for relation in RelationType
}
_RELATION_TYPE_ALIASES.update(
    {
        "positive correlate": RelationType.POSITIVE_CORRELATE,
        "negative correlate": RelationType.NEGATIVE_CORRELATE,
        "drug interact": RelationType.DRUG_INTERACT,
        "drug-interact": RelationType.DRUG_INTERACT,
    }
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _document_pmid(document: dict[str, Any]) -> str | None:
    infons = _as_dict(document.get("infons"))
    for value in (
        infons.get("article-id_pmid"),
        infons.get("pmid"),
        document.get("id"),
    ):
        if isinstance(value, str) and value.isdigit():
            return value
        if isinstance(value, int):
            return str(value)
    return None


def _annotation_infons(annotation: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(annotation.get("infons"))


def _entity_type(raw_type: Any) -> EntityType | None:
    if not isinstance(raw_type, str):
        return None
    return _ENTITY_TYPE_ALIASES.get(raw_type.strip().lower())


def _relation_type(raw_type: Any) -> RelationType | None:
    if not isinstance(raw_type, str):
        return None
    return _RELATION_TYPE_ALIASES.get(raw_type.strip().lower().replace("-", "_"))


def _first_identifier(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(int(value))
    if isinstance(value, list):
        for item in value:
            identifier = _first_identifier(item)
            if identifier:
                return identifier
        return None
    if not isinstance(value, str):
        return None
    for separator in (",", "|"):
        value = value.replace(separator, ";")
    for item in value.split(";"):
        cleaned = item.strip()
        if cleaned and cleaned != "-":
            return cleaned
    return None


def _normalized_identifier(infons: dict[str, Any]) -> str | None:
    for key in (
        "identifier",
        "identifiers",
        "normalized_id",
        "database_id",
        "db_id",
        "id",
        "ncbi_gene",
        "mesh",
        "chebi",
        "dbsnp",
    ):
        identifier = _first_identifier(infons.get(key))
        if identifier:
            return identifier
    return None


def _canonical_identifier(identifier: str, entity_type: EntityType) -> str:
    value = identifier.strip()
    lower = value.lower()
    prefix_map = {
        "ncbi gene:": "",
        "ncbigene:": "",
        "geneid:": "",
        "mesh:": "",
        "dbsnp:": "",
    }
    for prefix, replacement in prefix_map.items():
        if lower.startswith(prefix):
            value = replacement + value[len(prefix) :].strip()
            break
    if lower.startswith("chebi:"):
        value = f"CHEBI:{value.split(':', maxsplit=1)[1].strip()}"
    if entity_type is EntityType.VARIANT and value.upper().startswith("RS"):
        value = f"rs{value[2:]}"
    return value


def _annotation_confidence(infons: dict[str, Any]) -> float:
    value = infons.get("confidence")
    if isinstance(value, (int, float)):
        return max(0.0, min(float(value), 1.0))
    if isinstance(value, str):
        try:
            return max(0.0, min(float(value), 1.0))
        except ValueError:
            return 1.0
    return 1.0


def _annotation_text(annotation: dict[str, Any]) -> str | None:
    value = annotation.get("text")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _iter_annotations(document: dict[str, Any]) -> list[dict[str, Any]]:
    annotations: list[dict[str, Any]] = []
    document_annotations = document.get("annotations")
    if isinstance(document_annotations, list):
        annotations.extend(
            item for item in document_annotations if isinstance(item, dict)
        )
    passages = document.get("passages")
    if isinstance(passages, list):
        for passage in passages:
            if not isinstance(passage, dict):
                continue
            passage_annotations = passage.get("annotations")
            if isinstance(passage_annotations, list):
                annotations.extend(
                    item for item in passage_annotations if isinstance(item, dict)
                )
    return annotations


def _entity_from_annotation(
    annotation: dict[str, Any],
    pmid: str | None,
) -> Entity | None:
    infons = _annotation_infons(annotation)
    entity_type = _entity_type(infons.get("type") or infons.get("entity_type"))
    text = _annotation_text(annotation)
    normalized_id = _normalized_identifier(infons)
    if entity_type is None or text is None or normalized_id is None:
        return None
    normalized_id = _canonical_identifier(normalized_id, entity_type)
    return Entity(
        text=text,
        entity_type=entity_type,
        normalized_id=normalized_id,
        ontology=infer_ontology(normalized_id, entity_type),
        source_pmids=[pmid] if pmid else [],
        extractor=PUBTATOR_EXTRACTOR,
        confidence=_annotation_confidence(infons),
    )


def _entity_key(entity: Entity) -> tuple[str, EntityType, str, str, str]:
    return (
        entity.text.lower(),
        entity.entity_type,
        entity.normalized_id,
        entity.ontology,
        entity.extractor,
    )


def _merge_entity_group(entities: list[Entity]) -> Entity:
    first = entities[0]
    pmids = sorted({pmid for entity in entities for pmid in entity.source_pmids})
    confidence = max(entity.confidence for entity in entities)
    return first.model_copy(update={"source_pmids": pmids, "confidence": confidence})


def parse_pubtator_entities(data: dict[str, Any]) -> list[Entity]:
    """Parse PubTator3 BioC annotations into deduplicated entities."""

    grouped: dict[tuple[str, EntityType, str, str, str], list[Entity]] = defaultdict(
        list
    )
    documents = data.get("documents")
    if not isinstance(documents, list):
        return []
    for document in documents:
        if not isinstance(document, dict):
            continue
        pmid = _document_pmid(document)
        for annotation in _iter_annotations(document):
            entity = _entity_from_annotation(annotation, pmid)
            if entity:
                grouped[_entity_key(entity)].append(entity)
    return sorted(
        (_merge_entity_group(entities) for entities in grouped.values()),
        key=lambda entity: (
            entity.entity_type.value,
            entity.normalized_id,
            entity.text,
        ),
    )


def _annotation_id_map(
    document: dict[str, Any],
    pmid: str | None,
) -> dict[str, Entity]:
    mapping: dict[str, Entity] = {}
    for annotation in _iter_annotations(document):
        entity = _entity_from_annotation(annotation, pmid)
        if entity is None:
            continue
        annotation_id = annotation.get("id")
        if isinstance(annotation_id, str):
            mapping[annotation_id] = entity
    return mapping


def _iter_relations(document: dict[str, Any]) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    document_relations = document.get("relations")
    if isinstance(document_relations, list):
        relations.extend(item for item in document_relations if isinstance(item, dict))
    passages = document.get("passages")
    if isinstance(passages, list):
        for passage in passages:
            if not isinstance(passage, dict):
                continue
            passage_relations = passage.get("relations")
            if isinstance(passage_relations, list):
                relations.extend(
                    item for item in passage_relations if isinstance(item, dict)
                )
    return relations


def _relation_refids(relation: dict[str, Any]) -> tuple[str | None, str | None]:
    nodes = relation.get("nodes")
    if isinstance(nodes, list):
        refids = [
            node.get("refid")
            for node in nodes
            if isinstance(node, dict) and isinstance(node.get("refid"), str)
        ]
        if len(refids) >= 2:
            return refids[0], refids[1]
    for left_key, right_key in (
        ("subject", "object"),
        ("subj", "obj"),
        ("e1", "e2"),
        ("arg1", "arg2"),
    ):
        left = relation.get(left_key)
        right = relation.get(right_key)
        if isinstance(left, str) and isinstance(right, str):
            return left, right
    return None, None


def _relation_confidence(relation: dict[str, Any]) -> float:
    infons = _as_dict(relation.get("infons"))
    return _annotation_confidence(infons)


def _relation_from_bioc(
    relation: dict[str, Any],
    entity_by_annotation_id: dict[str, Entity],
    pmid: str | None,
) -> Relation | None:
    infons = _as_dict(relation.get("infons"))
    relation_type = _relation_type(
        relation.get("type") or infons.get("type") or infons.get("relation")
    )
    subject_refid, object_refid = _relation_refids(relation)
    if relation_type is None or subject_refid is None or object_refid is None:
        return None
    subject = entity_by_annotation_id.get(subject_refid)
    object_entity = entity_by_annotation_id.get(object_refid)
    if subject is None or object_entity is None:
        return None
    pmids = sorted(
        {
            pmid
            for pmid in [pmid, *subject.source_pmids, *object_entity.source_pmids]
            if pmid
        }
    )
    return Relation(
        subject=subject,
        relation=relation_type,
        object=object_entity,
        source_pmids=pmids,
        extractor=PUBTATOR_EXTRACTOR,
        confidence=_relation_confidence(relation),
        is_cooccurrence_only=False,
    )


def parse_pubtator_relations(data: dict[str, Any]) -> list[Relation]:
    """Parse PubTator3 typed BioC relations, never co-occurrence edges."""

    documents = data.get("documents")
    if not isinstance(documents, list):
        return []
    relations: list[Relation] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        pmid = _document_pmid(document)
        entity_by_annotation_id = _annotation_id_map(document, pmid)
        for raw_relation in _iter_relations(document):
            relation = _relation_from_bioc(raw_relation, entity_by_annotation_id, pmid)
            if relation:
                relations.append(relation)
    return relations


def parse_pubtator_biocjson(data: dict[str, Any]) -> ExtractionResult:
    """Parse PubTator3 BioC JSON into entity and typed-relation records."""

    return ExtractionResult(
        entities=parse_pubtator_entities(data),
        relations=parse_pubtator_relations(data),
    )
