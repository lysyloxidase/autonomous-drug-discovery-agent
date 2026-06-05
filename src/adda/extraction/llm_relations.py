"""Local-LLM relation extraction with explicit quality tagging."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from adda.extraction.grounding import (
    ReferenceOntologyGrounder,
    infer_ontology,
    unresolved_id,
)
from adda.extraction.models import Entity, EntityType, Relation, RelationType

LOCAL_LLM_EXTRACTOR = "local_llm"


class LLMRelationCandidate(BaseModel):
    """One constrained JSON relation candidate returned by a local LLM."""

    subject_text: str
    subject_type: EntityType
    subject_id: str | None = None
    relation: RelationType
    object_text: str
    object_type: EntityType
    object_id: str | None = None
    source_pmids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    db_supported: bool = False


class LLMRelationResponse(BaseModel):
    """Structured response expected from Ollama."""

    relations: list[LLMRelationCandidate] = Field(default_factory=list)


def _entity_from_candidate(
    *,
    text: str,
    entity_type: EntityType,
    normalized_id: str | None,
    source_pmids: list[str],
    confidence: float,
    grounder: ReferenceOntologyGrounder | None,
) -> Entity:
    if normalized_id:
        ontology = infer_ontology(normalized_id, entity_type)
    elif grounder:
        match = grounder.ground_or_unresolved(text, entity_type, confidence=0.35)
        normalized_id = match.normalized_id
        ontology = match.ontology
        confidence = min(confidence, match.confidence)
    else:
        normalized_id = unresolved_id(text, entity_type)
        ontology = "unresolved"
        confidence = min(confidence, 0.35)
    return Entity(
        text=text,
        entity_type=entity_type,
        normalized_id=normalized_id,
        ontology=ontology,
        source_pmids=source_pmids,
        extractor=LOCAL_LLM_EXTRACTOR,
        confidence=confidence,
    )


def relation_from_candidate(
    candidate: LLMRelationCandidate,
    *,
    grounder: ReferenceOntologyGrounder | None = None,
) -> Relation:
    """Convert validated LLM JSON into a relation with honesty flags."""

    subject = _entity_from_candidate(
        text=candidate.subject_text,
        entity_type=candidate.subject_type,
        normalized_id=candidate.subject_id,
        source_pmids=candidate.source_pmids,
        confidence=candidate.confidence,
        grounder=grounder,
    )
    object_entity = _entity_from_candidate(
        text=candidate.object_text,
        entity_type=candidate.object_type,
        normalized_id=candidate.object_id,
        source_pmids=candidate.source_pmids,
        confidence=candidate.confidence,
        grounder=grounder,
    )
    return Relation(
        subject=subject,
        relation=candidate.relation,
        object=object_entity,
        source_pmids=candidate.source_pmids,
        extractor=LOCAL_LLM_EXTRACTOR,
        confidence=candidate.confidence,
        is_cooccurrence_only=not candidate.db_supported,
    )


def parse_llm_relation_json(
    payload: str | dict[str, Any],
    *,
    grounder: ReferenceOntologyGrounder | None = None,
) -> list[Relation]:
    """Parse constrained LLM JSON and return validated relations."""

    raw = json.loads(payload) if isinstance(payload, str) else payload
    response = LLMRelationResponse.model_validate(raw)
    return [
        relation_from_candidate(candidate, grounder=grounder)
        for candidate in response.relations
    ]


def speculative_relations(relations: Sequence[Relation]) -> list[Relation]:
    """Return relations that must be forced to the SPECULATIVE evidence tier."""

    return [relation for relation in relations if relation.is_cooccurrence_only]


class OllamaRelationExtractor:
    """Ollama structured-output relation extractor."""

    def __init__(
        self,
        *,
        model: str = "qwen2.5:7b",
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
        grounder: ReferenceOntologyGrounder | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self.grounder = grounder

    async def aclose(self) -> None:
        """Close the owned HTTP client."""

        if self._owns_client:
            await self._client.aclose()

    async def extract_relations(
        self,
        text: str,
        *,
        source_pmids: Sequence[str] = (),
    ) -> list[Relation]:
        """Ask Ollama for constrained relation JSON and validate it."""

        response = await self._client.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "stream": False,
                "format": LLMRelationResponse.model_json_schema(),
                "prompt": self._prompt(text, source_pmids),
                "options": {"num_ctx": 4096},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        generated = data.get("response")
        if not isinstance(generated, str):
            raise ValidationError.from_exception_data(
                "LLMRelationResponse",
                [
                    {
                        "type": "string_type",
                        "loc": ("response",),
                        "input": generated,
                    }
                ],
            )
        return parse_llm_relation_json(generated, grounder=self.grounder)

    def _prompt(self, text: str, source_pmids: Sequence[str]) -> str:
        allowed_relations = ", ".join(relation.value for relation in RelationType)
        allowed_entities = ", ".join(entity_type.value for entity_type in EntityType)
        pmids = ", ".join(source_pmids) if source_pmids else "unknown"
        return (
            "Extract only explicitly supported biomedical relations. "
            "Return JSON matching the supplied schema. "
            "Set db_supported=true only when the text names database-backed "
            "evidence or a PubTator/database relation; otherwise false. "
            f"Allowed relation values: {allowed_relations}. "
            f"Allowed entity types: {allowed_entities}. "
            f"Source PMIDs: {pmids}.\n\nText:\n{text}"
        )
