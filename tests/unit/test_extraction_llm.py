from __future__ import annotations

import json

import httpx
import pytest
import respx

from adda.extraction.llm_relations import (
    OllamaRelationExtractor,
    parse_llm_relation_json,
    speculative_relations,
)
from adda.extraction.models import RelationType


def llm_payload(db_supported: bool = False) -> dict[str, object]:
    return {
        "relations": [
            {
                "subject_text": "TP53",
                "subject_type": "gene",
                "subject_id": "7157",
                "relation": "associate",
                "object_text": "glioblastoma",
                "object_type": "disease",
                "object_id": "D005909",
                "source_pmids": ["12345"],
                "confidence": 0.64,
                "db_supported": db_supported,
            }
        ]
    }


def test_local_llm_json_returns_valid_constrained_relations() -> None:
    relations = parse_llm_relation_json(llm_payload(db_supported=True))

    assert len(relations) == 1
    relation = relations[0]
    assert relation.relation is RelationType.ASSOCIATE
    assert relation.extractor == "local_llm"
    assert relation.is_cooccurrence_only is False
    assert relation.subject.ontology == "NCBI Gene"
    assert relation.object.ontology == "MeSH"


def test_llm_relations_without_db_support_are_speculative() -> None:
    relations = parse_llm_relation_json(json.dumps(llm_payload(db_supported=False)))

    assert relations[0].is_cooccurrence_only is True
    assert speculative_relations(relations) == relations


def test_invalid_llm_relation_json_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_llm_relation_json(
            {
                "relations": [
                    {
                        "subject_text": "TP53",
                        "subject_type": "gene",
                        "relation": "not_allowed",
                        "object_text": "glioblastoma",
                        "object_type": "disease",
                        "confidence": 0.5,
                    }
                ]
            }
        )


@pytest.mark.asyncio
@respx.mock
async def test_ollama_relation_extractor_uses_structured_output() -> None:
    route = respx.post("http://ollama.test/api/generate").mock(
        return_value=httpx.Response(
            200,
            json={"response": json.dumps(llm_payload(db_supported=False))},
        )
    )
    extractor = OllamaRelationExtractor(base_url="http://ollama.test")

    relations = await extractor.extract_relations("TP53 associates with glioblastoma.")
    await extractor.aclose()

    assert route.called
    request_json = json.loads(route.calls.last.request.content.decode("utf-8"))
    assert request_json["model"] == "qwen2.5:7b"
    assert "relations" in request_json["format"]["properties"]
    assert relations[0].is_cooccurrence_only is True
