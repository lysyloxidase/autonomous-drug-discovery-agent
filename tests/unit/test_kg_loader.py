from __future__ import annotations

from typing import Any

from adda.extraction.models import Entity, EntityType, Relation, RelationType
from adda.kg.loader import APOC_NODE_LOAD_QUERY, APOC_RELATION_LOAD_QUERY, KGLoader
from adda.kg.schema import EdgeProvenance, KGEdge, KGRelationType, NodeLabel


class FakeDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def execute_query(
        self,
        query: str,
        *,
        parameters_: dict[str, Any],
    ) -> list[dict[str, Any]]:
        self.calls.append((query, parameters_))
        if "apoc.version()" in query:
            return [{"apoc_version": "5.0", "gds_version": "2.7"}]
        if "missing_count" in query:
            return [{"missing_count": 0}]
        if "ASSOCIATED_WITH" in query:
            return [
                {
                    "disease_id": "D005909",
                    "gene_id": "7157",
                    "source_pmids": ["1"],
                    "extraction_confidence": 0.9,
                    "evidence_tier": "",
                    "source_db": "pubtator3",
                    "created_at": "2026-06-05T00:00:00+00:00",
                    "extractor_version": "0.1.0",
                }
            ]
        return []

    def close(self) -> None:
        self.closed = True


def entity(text: str, entity_type: EntityType, normalized_id: str) -> Entity:
    ontology = "MeSH" if entity_type is EntityType.DISEASE else "NCBI Gene"
    return Entity(
        text=text,
        entity_type=entity_type,
        normalized_id=normalized_id,
        ontology=ontology,
        source_pmids=["1"],
        extractor="pubtator3",
        confidence=0.9,
    )


def disease_gene_relation() -> Relation:
    return Relation(
        subject=entity("glioblastoma", EntityType.DISEASE, "D005909"),
        relation=RelationType.ASSOCIATE,
        object=entity("TP53", EntityType.GENE, "7157"),
        source_pmids=["1"],
        extractor="pubtator3",
        confidence=0.9,
    )


def test_loader_creates_constraints_and_checks_plugins() -> None:
    driver = FakeDriver()
    loader = KGLoader("bolt://test", ("neo4j", "pass"), driver=driver)

    loader.create_constraints()
    plugins = loader.check_plugins()
    loader.close()

    assert any("CREATE CONSTRAINT disease_id" in query for query, _ in driver.calls)
    assert plugins == {"apoc_version": "5.0", "gds_version": "2.7"}
    assert driver.closed is True


def test_merge_nodes_uses_apoc_periodic_iterate_and_is_idempotent_per_batch() -> None:
    driver = FakeDriver()
    loader = KGLoader("bolt://test", ("neo4j", "pass"), driver=driver)
    disease = entity("glioblastoma", EntityType.DISEASE, "D005909")

    loader.merge_nodes([disease, disease])

    query, params = driver.calls[-1]
    rows = params["rows"]
    assert query == APOC_NODE_LOAD_QUERY
    assert "apoc.periodic.iterate" in query
    assert len(rows) == 2
    assert {row["label"] for row in rows} == {"Disease", "Publication"}
    assert {row["id"] for row in rows} == {"D005909", "1"}


def test_merge_relations_uses_apoc_and_writes_full_edge_provenance() -> None:
    driver = FakeDriver()
    loader = KGLoader("bolt://test", ("neo4j", "pass"), driver=driver)

    loader.merge_relations([disease_gene_relation()])

    query, params = driver.calls[-1]
    rows = params["rows"]
    assert query == APOC_RELATION_LOAD_QUERY
    assert "apoc.merge.relationship" in query
    assert {row["type"] for row in rows} == {"ASSOCIATED_WITH", "MENTIONS"}
    for row in rows:
        assert set(row["props"]) == {
            "source_pmids",
            "extraction_confidence",
            "evidence_tier",
            "source_db",
            "created_at",
            "extractor_version",
        }


def test_attach_provenance_and_query_helpers_round_trip_mock_records() -> None:
    driver = FakeDriver()
    loader = KGLoader("bolt://test", ("neo4j", "pass"), driver=driver)
    edge = KGEdge(
        source_label=NodeLabel.DISEASE,
        source_id="D005909",
        target_label=NodeLabel.GENE,
        target_id="7157",
        relation_type=KGRelationType.ASSOCIATED_WITH,
        provenance=EdgeProvenance(
            source_pmids=["1"],
            extraction_confidence=0.9,
            source_db="pubtator3",
        ),
    )
    provenance = EdgeProvenance(
        source_pmids=["1", "2"],
        extraction_confidence=0.95,
        evidence_tier="curated",
        source_db="pubtator3",
        extractor_version="test",
    )

    loader.attach_provenance(edge, provenance)
    missing = loader.count_edges_missing_provenance()
    records = loader.disease_gene_edges()

    loaded_row = driver.calls[-3][1]["rows"][0]
    assert loaded_row["props"]["evidence_tier"] == "curated"
    assert missing == 0
    assert records[0]["disease_id"] == "D005909"
    assert records[0]["source_pmids"] == ["1"]
