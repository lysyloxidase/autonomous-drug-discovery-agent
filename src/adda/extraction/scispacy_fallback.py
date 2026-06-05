"""Secondary scispaCy entity extraction for unannotated passages."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol, cast

from adda.extraction.grounding import (
    ReferenceOntologyGrounder,
    infer_ontology,
)
from adda.extraction.models import Entity, EntityType
from adda.models import Publication

SCISPACY_EXTRACTOR = "scispacy"


class ScispaCyPipeline(Protocol):
    """Protocol for a spaCy/scispaCy pipeline."""

    def __call__(self, text: str) -> Any:
        """Return a document-like object with ``ents``."""


_LABEL_MAP: dict[str, EntityType] = {
    "GENE_OR_GENE_PRODUCT": EntityType.GENE,
    "GENE": EntityType.GENE,
    "PROTEIN": EntityType.GENE,
    "DISEASE": EntityType.DISEASE,
    "CANCER": EntityType.DISEASE,
    "SIMPLE_CHEMICAL": EntityType.CHEMICAL,
    "CHEMICAL": EntityType.CHEMICAL,
    "CHEMICAL_ENTITY": EntityType.CHEMICAL,
    "ORGANISM": EntityType.SPECIES,
    "ORGANISM_SUBDIVISION": EntityType.SPECIES,
    "CELL_LINE": EntityType.CELL_LINE,
    "CELL_TYPE": EntityType.CELL_LINE,
    "PATHWAY": EntityType.PATHWAY,
    "PHENOTYPE": EntityType.PHENOTYPE,
}


def load_scispacy_model(model_name: str = "en_ner_bionlp13cg_md") -> ScispaCyPipeline:
    """Load a scispaCy model when the optional dependency is installed."""

    try:
        import spacy  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "scispaCy fallback requires spaCy/scispaCy to be installed"
        ) from exc
    return cast(ScispaCyPipeline, spacy.load(model_name))


def _source_text(publication: Publication) -> str | None:
    return publication.full_text or publication.abstract


def _kb_ents(span: Any) -> list[tuple[str, float]]:
    extension = getattr(span, "_", None)
    if extension is not None:
        value = getattr(extension, "kb_ents", None)
        if isinstance(value, list):
            return [
                (str(item[0]), float(item[1]))
                for item in value
                if isinstance(item, tuple) and len(item) >= 2
            ]
    value = getattr(span, "kb_ents", None)
    if isinstance(value, list):
        return [
            (str(item[0]), float(item[1]))
            for item in value
            if isinstance(item, tuple) and len(item) >= 2
        ]
    return []


def _entity_type_from_label(label: str) -> EntityType | None:
    return _LABEL_MAP.get(label.upper())


def _entity_from_span(
    span: Any,
    *,
    pmid: str | None,
    grounder: ReferenceOntologyGrounder,
) -> Entity | None:
    text = getattr(span, "text", None)
    label = getattr(span, "label_", None)
    if not isinstance(text, str) or not text.strip() or not isinstance(label, str):
        return None
    entity_type = _entity_type_from_label(label)
    if entity_type is None:
        return None

    kb_ents = _kb_ents(span)
    if kb_ents:
        normalized_id, score = kb_ents[0]
        ontology = infer_ontology(normalized_id, entity_type)
        confidence = max(0.0, min(score, 1.0))
    else:
        match = grounder.ground_or_unresolved(text, entity_type, confidence=0.35)
        normalized_id = match.normalized_id
        ontology = match.ontology
        confidence = match.confidence

    return Entity(
        text=text.strip(),
        entity_type=entity_type,
        normalized_id=normalized_id,
        ontology=ontology,
        source_pmids=[pmid] if pmid else [],
        extractor=SCISPACY_EXTRACTOR,
        confidence=confidence,
    )


def _dedupe_entities(entities: Iterable[Entity]) -> list[Entity]:
    grouped: dict[tuple[str, EntityType, str, str], Entity] = {}
    for entity in entities:
        key = (
            entity.text.lower(),
            entity.entity_type,
            entity.normalized_id,
            entity.extractor,
        )
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = entity
            continue
        pmids = sorted({*existing.source_pmids, *entity.source_pmids})
        grouped[key] = existing.model_copy(
            update={
                "source_pmids": pmids,
                "confidence": max(existing.confidence, entity.confidence),
            }
        )
    return sorted(
        grouped.values(),
        key=lambda entity: (
            entity.entity_type.value,
            entity.normalized_id,
            entity.text,
        ),
    )


def extract_scispacy_entities(
    publications: Sequence[Publication],
    *,
    nlp: ScispaCyPipeline,
    grounder: ReferenceOntologyGrounder | None = None,
    skip_pmids: set[str] | None = None,
) -> list[Entity]:
    """Run scispaCy over full text or abstracts not covered by PubTator3."""

    active_grounder = grounder or ReferenceOntologyGrounder()
    skipped = skip_pmids or set()
    entities: list[Entity] = []
    for publication in publications:
        if publication.pmid and publication.pmid in skipped:
            continue
        text = _source_text(publication)
        if not text:
            continue
        doc = nlp(text)
        spans = getattr(doc, "ents", [])
        if not isinstance(spans, Iterable):
            continue
        for span in spans:
            entity = _entity_from_span(
                span,
                pmid=publication.pmid,
                grounder=active_grounder,
            )
            if entity:
                entities.append(entity)
    return _dedupe_entities(entities)
