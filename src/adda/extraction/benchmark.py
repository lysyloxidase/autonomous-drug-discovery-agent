"""Measure NER and relation extraction quality against gold annotations."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, Field

from adda.extraction.models import Entity, ExtractionResult, Relation

T = TypeVar("T")


class MetricReport(BaseModel):
    """Precision, recall, and F1 for one extraction task."""

    precision: float
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    false_negatives: int
    support: int


class ExtractionBenchmarkReport(BaseModel):
    """Benchmark report for Phase 2 honesty gates."""

    evaluated_at: str
    benchmark_name: str
    ner: MetricReport
    relation_extraction: MetricReport
    notes: list[str] = Field(default_factory=list)


def _metric(
    predicted: Iterable[T],
    gold: Iterable[T],
    key_fn: Callable[[T], tuple[str, ...]],
) -> MetricReport:
    predicted_keys = {key_fn(item) for item in predicted}
    gold_keys = {key_fn(item) for item in gold}
    true_positives = len(predicted_keys & gold_keys)
    false_positives = len(predicted_keys - gold_keys)
    false_negatives = len(gold_keys - predicted_keys)
    precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if true_positives + false_negatives
        else 0.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return MetricReport(
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        support=len(gold_keys),
    )


def entity_key(entity: Entity) -> tuple[str, ...]:
    """Stable entity key for evaluation."""

    return (
        entity.entity_type.value,
        entity.normalized_id,
        entity.ontology,
    )


def relation_key(relation: Relation) -> tuple[str, ...]:
    """Stable relation key for evaluation."""

    return (
        relation.subject.normalized_id,
        relation.relation.value,
        relation.object.normalized_id,
    )


def benchmark_extraction(
    predicted: ExtractionResult,
    gold: ExtractionResult,
    *,
    benchmark_name: str = "PubTator3/BioRED subset",
    notes: Sequence[str] = (),
) -> ExtractionBenchmarkReport:
    """Compute entity and relation precision/recall against gold records."""

    return ExtractionBenchmarkReport(
        evaluated_at=datetime.now(UTC).isoformat(),
        benchmark_name=benchmark_name,
        ner=_metric(predicted.entities, gold.entities, entity_key),
        relation_extraction=_metric(predicted.relations, gold.relations, relation_key),
        notes=list(notes),
    )


def write_benchmark_report(
    report: ExtractionBenchmarkReport,
    output_path: str | Path = "reports/extraction_eval.json",
) -> Path:
    """Write a benchmark report to disk."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def load_extraction_result(path: str | Path) -> ExtractionResult:
    """Load a serialized extraction result fixture."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ExtractionResult.model_validate(data)


def evaluate_biored_subset(
    *,
    predicted_path: str | Path,
    gold_path: str | Path,
    output_path: str | Path = "reports/extraction_eval.json",
) -> ExtractionBenchmarkReport:
    """Evaluate a BioRED-format subset fixture and write metrics."""

    predicted = load_extraction_result(predicted_path)
    gold = load_extraction_result(gold_path)
    report = benchmark_extraction(
        predicted,
        gold,
        benchmark_name="BioRED subset",
        notes=[
            "BioRED full benchmark contains 600 abstracts and 6,503 relations.",
            "This helper writes numbers for the provided subset only.",
        ],
    )
    write_benchmark_report(report, output_path)
    return report
