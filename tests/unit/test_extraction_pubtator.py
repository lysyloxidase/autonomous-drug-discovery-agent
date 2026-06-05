from __future__ import annotations

from adda.extraction.models import EntityType, RelationType
from adda.extraction.pubtator_entities import parse_pubtator_biocjson


def bioc_fixture() -> dict[str, object]:
    return {
        "documents": [
            {
                "id": "12345",
                "passages": [
                    {
                        "infons": {"type": "abstract"},
                        "text": "TP53 treats glioblastoma in a model.",
                        "annotations": [
                            {
                                "id": "A1",
                                "text": "TP53",
                                "infons": {
                                    "type": "Gene",
                                    "identifier": "NCBI Gene:7157",
                                },
                            },
                            {
                                "id": "A2",
                                "text": "glioblastoma",
                                "infons": {
                                    "type": "Disease",
                                    "identifier": "MESH:D005909",
                                },
                            },
                            {
                                "id": "A3",
                                "text": "imatinib",
                                "infons": {
                                    "type": "Chemical",
                                    "identifier": "CHEBI:45783",
                                },
                            },
                            {
                                "id": "A4",
                                "text": "rs1042522",
                                "infons": {
                                    "type": "Variant",
                                    "identifier": "dbSNP:RS1042522",
                                },
                            },
                        ],
                        "relations": [
                            {
                                "infons": {"type": "treat", "confidence": "0.91"},
                                "nodes": [
                                    {"refid": "A3", "role": "subject"},
                                    {"refid": "A2", "role": "object"},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_pubtator_biocjson_parses_entities_with_stable_ontologies() -> None:
    result = parse_pubtator_biocjson(bioc_fixture())

    by_text = {entity.text: entity for entity in result.entities}

    assert by_text["TP53"].entity_type is EntityType.GENE
    assert by_text["TP53"].normalized_id == "7157"
    assert by_text["TP53"].ontology == "NCBI Gene"
    assert by_text["glioblastoma"].ontology == "MeSH"
    assert by_text["imatinib"].ontology == "ChEBI"
    assert by_text["rs1042522"].ontology == "dbSNP"
    assert by_text["TP53"].extractor == "pubtator3"
    assert by_text["TP53"].source_pmids == ["12345"]


def test_pubtator_biocjson_parses_typed_relations_not_cooccurrence() -> None:
    result = parse_pubtator_biocjson(bioc_fixture())

    assert len(result.relations) == 1
    relation = result.relations[0]
    assert relation.subject.text == "imatinib"
    assert relation.object.text == "glioblastoma"
    assert relation.relation is RelationType.TREAT
    assert relation.extractor == "pubtator3"
    assert relation.is_cooccurrence_only is False
    assert relation.confidence == 0.91


def test_pubtator_skips_untyped_or_unresolved_annotations() -> None:
    result = parse_pubtator_biocjson(
        {
            "documents": [
                {
                    "id": "1",
                    "annotations": [
                        {"id": "bad1", "text": "unknown", "infons": {"type": "Gene"}},
                        {
                            "id": "bad2",
                            "text": "unknown",
                            "infons": {"identifier": "1"},
                        },
                    ],
                    "relations": [{"type": "associate", "subject": "x", "object": "y"}],
                }
            ]
        }
    )

    assert result.entities == []
    assert result.relations == []
