"""Normalize entity surface forms to reference ontologies."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

from pydantic import BaseModel, Field

from adda.extraction.models import EntityType

_SPACE_RE = re.compile(r"\s+")


class GroundingMatch(BaseModel):
    """A normalized ontology match."""

    normalized_id: str
    ontology: str
    confidence: float = Field(ge=0.0, le=1.0)


AliasKey = tuple[EntityType, str]


DEFAULT_ALIASES: dict[AliasKey, GroundingMatch] = {
    (EntityType.GENE, "tp53"): GroundingMatch(
        normalized_id="7157", ontology="NCBI Gene", confidence=0.99
    ),
    (EntityType.GENE, "egfr"): GroundingMatch(
        normalized_id="1956", ontology="NCBI Gene", confidence=0.99
    ),
    (EntityType.DISEASE, "glioblastoma"): GroundingMatch(
        normalized_id="D005909", ontology="MeSH", confidence=0.98
    ),
    (EntityType.CHEMICAL, "imatinib"): GroundingMatch(
        normalized_id="CHEBI:45783", ontology="ChEBI", confidence=0.95
    ),
    (EntityType.PHENOTYPE, "apoptosis"): GroundingMatch(
        normalized_id="GO:0006915", ontology="GO", confidence=0.90
    ),
    (EntityType.PATHWAY, "p53 signaling pathway"): GroundingMatch(
        normalized_id="R-HSA-69541", ontology="Reactome", confidence=0.90
    ),
}


def normalize_surface(text: str) -> str:
    """Normalize a surface form for alias lookup."""

    return _SPACE_RE.sub(" ", text.strip().lower()).strip()


def infer_ontology(normalized_id: str, entity_type: EntityType) -> str:
    """Infer an ontology label from an ID and entity type."""

    value = normalized_id.strip()
    upper = value.upper()
    if upper.startswith("CHEBI:"):
        return "ChEBI"
    if upper.startswith("CHEMBL"):
        return "ChEMBL"
    if upper.startswith("MESH:") or re.fullmatch(r"D\d{6}", upper):
        return "MeSH"
    if upper.startswith("MONDO:"):
        return "MONDO"
    if upper.startswith("DOID:"):
        return "DOID"
    if upper.startswith("EFO:"):
        return "EFO"
    if upper.startswith("HP:"):
        return "HPO"
    if upper.startswith("GO:"):
        return "GO"
    if upper.startswith("R-HSA-"):
        return "Reactome"
    if upper.startswith("RS"):
        return "dbSNP"
    if upper.startswith("CVCL_"):
        return "Cellosaurus"
    if upper.startswith("TAX:") or upper.startswith("NCBITAXON:"):
        return "NCBI Taxonomy"
    if entity_type is EntityType.GENE and value.isdigit():
        return "NCBI Gene"
    return {
        EntityType.GENE: "NCBI Gene",
        EntityType.DISEASE: "MeSH",
        EntityType.CHEMICAL: "MeSH",
        EntityType.VARIANT: "dbSNP",
        EntityType.SPECIES: "NCBI Taxonomy",
        EntityType.CELL_LINE: "Cellosaurus",
        EntityType.PATHWAY: "Reactome",
        EntityType.PHENOTYPE: "HPO",
    }[entity_type]


def unresolved_id(text: str, entity_type: EntityType) -> str:
    """Return a stable unresolved ID for clearly tagged fallback entities."""

    digest = hashlib.sha1(
        f"{entity_type.value}:{normalize_surface(text)}".encode()
    ).hexdigest()[:12]
    return f"UNRESOLVED:{digest}"


class ReferenceOntologyGrounder:
    """Alias-map grounder with an explicit cache."""

    def __init__(
        self,
        aliases: Mapping[AliasKey, GroundingMatch] | None = None,
    ) -> None:
        self.aliases: dict[AliasKey, GroundingMatch] = dict(DEFAULT_ALIASES)
        if aliases:
            self.aliases.update(aliases)
        self._cache: dict[AliasKey, GroundingMatch | None] = {}
        self.lookup_count = 0

    def ground(self, text: str, entity_type: EntityType) -> GroundingMatch | None:
        """Return a grounding match, caching misses and hits."""

        key = (entity_type, normalize_surface(text))
        if key in self._cache:
            return self._cache[key]
        self.lookup_count += 1
        match = self.aliases.get(key)
        self._cache[key] = match
        return match

    def ground_or_unresolved(
        self,
        text: str,
        entity_type: EntityType,
        *,
        confidence: float = 0.4,
    ) -> GroundingMatch:
        """Return a grounding match or a tagged unresolved fallback."""

        match = self.ground(text, entity_type)
        if match is not None:
            return match
        return GroundingMatch(
            normalized_id=unresolved_id(text, entity_type),
            ontology="unresolved",
            confidence=confidence,
        )
