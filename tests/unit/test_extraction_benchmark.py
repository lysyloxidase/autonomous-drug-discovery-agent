from __future__ import annotations

import json
from pathlib import Path

from adda.extraction.benchmark import (
    benchmark_extraction,
    evaluate_biored_subset,
    write_benchmark_report,
)
from adda.extraction.models import (
    Entity,
    EntityType,
    ExtractionResult,
    Relation,
    RelationType,
)


def entity(text: str, entity_type: EntityType, normalized_id: str) -> Entity:
    ontology = "NCBI Gene" if entity_type is EntityType.GENE else "MeSH"
    return Entity(
        text=text,
        entity_type=entity_type,
        normalized_id=normalized_id,
        ontology=ontology,
        source_pmids=["1"],
        extractor="pubtator3",
        confidence=1.0,
    )


def extraction_result() -> tuple[ExtractionResult, ExtractionResult]:
    tp53 = entity("TP53", EntityType.GENE, "7157")
    glioblastoma = entity("glioblastoma", EntityType.DISEASE, "D005909")
    egfr = entity("EGFR", EntityType.GENE, "1956")
    gold_relation = Relation(
        subject=tp53,
        relation=RelationType.ASSOCIATE,
        object=glioblastoma,
        source_pmids=["1"],
        extractor="pubtator3",
        confidence=1.0,
    )
    false_relation = Relation(
        subject=egfr,
        relation=RelationType.ASSOCIATE,
        object=glioblastoma,
        source_pmids=["1"],
        extractor="local_llm",
        confidence=0.4,
        is_cooccurrence_only=True,
    )
    return (
        ExtractionResult(
            entities=[tp53, glioblastoma, egfr],
            relations=[gold_relation, false_relation],
        ),
        ExtractionResult(
            entities=[tp53, glioblastoma],
            relations=[gold_relation],
        ),
    )


def test_benchmark_reports_precision_recall_numbers() -> None:
    predicted, gold = extraction_result()

    report = benchmark_extraction(predicted, gold, benchmark_name="PubTator3")

    assert report.ner.precision == 0.6667
    assert report.ner.recall == 1.0
    assert report.relation_extraction.precision == 0.5
    assert report.relation_extraction.recall == 1.0


def test_biored_subset_eval_writes_report(tmp_path) -> None:  # type: ignore[no-untyped-def]
    predicted, gold = extraction_result()
    predicted_path = tmp_path / "predicted.json"
    gold_path = tmp_path / "gold.json"
    output_path = tmp_path / "reports" / "extraction_eval.json"
    predicted_path.write_text(predicted.model_dump_json(), encoding="utf-8")
    gold_path.write_text(gold.model_dump_json(), encoding="utf-8")

    report = evaluate_biored_subset(
        predicted_path=predicted_path,
        gold_path=gold_path,
        output_path=output_path,
    )

    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert report.benchmark_name == "BioRED subset"
    assert loaded["relation_extraction"]["precision"] == 0.5


def test_write_benchmark_report_creates_parent_directory(tmp_path) -> None:  # type: ignore[no-untyped-def]
    predicted, gold = extraction_result()
    report = benchmark_extraction(predicted, gold)
    output_path = write_benchmark_report(report, tmp_path / "nested" / "report.json")

    assert output_path.exists()


def test_committed_biored_subset_fixture_metrics(tmp_path) -> None:  # type: ignore[no-untyped-def]
    fixtures = Path(__file__).parents[1] / "fixtures"
    report = evaluate_biored_subset(
        predicted_path=fixtures / "biored_subset_predicted.json",
        gold_path=fixtures / "biored_subset_gold.json",
        output_path=tmp_path / "extraction_eval.json",
    )

    assert report.ner.precision == 0.6667
    assert report.relation_extraction.precision == 0.5
