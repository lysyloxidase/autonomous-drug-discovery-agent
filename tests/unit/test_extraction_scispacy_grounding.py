from __future__ import annotations

from dataclasses import dataclass

from adda.extraction.grounding import (
    GroundingMatch,
    ReferenceOntologyGrounder,
)
from adda.extraction.models import EntityType
from adda.extraction.scispacy_fallback import extract_scispacy_entities
from adda.models import Publication


@dataclass
class FakeSpan:
    text: str
    label_: str
    kb_ents: list[tuple[str, float]] | None = None


@dataclass
class FakeDoc:
    ents: list[FakeSpan]


class FakeNLP:
    def __call__(self, text: str) -> FakeDoc:
        return FakeDoc(
            [
                FakeSpan("EGFR", "GENE_OR_GENE_PRODUCT", [("1956", 0.93)]),
                FakeSpan("glioblastoma", "DISEASE"),
                FakeSpan("ignored", "UNKNOWN"),
            ]
        )


def test_scispacy_fallback_runs_on_full_text_and_tags_extractor() -> None:
    grounder = ReferenceOntologyGrounder(
        {
            (EntityType.DISEASE, "glioblastoma"): GroundingMatch(
                normalized_id="D005909",
                ontology="MeSH",
                confidence=0.98,
            )
        }
    )
    publications = [
        Publication(
            canonical_id="pmid:1",
            pmid="1",
            title="Record",
            full_text="EGFR is altered in glioblastoma.",
        )
    ]

    entities = extract_scispacy_entities(
        publications,
        nlp=FakeNLP(),
        grounder=grounder,
    )

    by_text = {entity.text: entity for entity in entities}
    assert by_text["EGFR"].extractor == "scispacy"
    assert by_text["EGFR"].ontology == "NCBI Gene"
    assert by_text["EGFR"].confidence == 0.93
    assert by_text["glioblastoma"].normalized_id == "D005909"
    assert by_text["glioblastoma"].source_pmids == ["1"]


def test_scispacy_fallback_skips_pubtator_annotated_pmids() -> None:
    publications = [
        Publication(
            canonical_id="pmid:1",
            pmid="1",
            title="Record",
            abstract="EGFR is altered.",
        )
    ]

    assert (
        extract_scispacy_entities(
            publications,
            nlp=FakeNLP(),
            skip_pmids={"1"},
        )
        == []
    )


def test_grounding_cache_normalizes_surface_forms_once() -> None:
    grounder = ReferenceOntologyGrounder(
        {
            (EntityType.GENE, "alk"): GroundingMatch(
                normalized_id="238",
                ontology="NCBI Gene",
                confidence=0.97,
            )
        }
    )

    first = grounder.ground("ALK", EntityType.GENE)
    second = grounder.ground(" alk ", EntityType.GENE)
    unresolved = grounder.ground_or_unresolved("not real", EntityType.CHEMICAL)

    assert first == second
    assert first is not None
    assert first.normalized_id == "238"
    assert grounder.lookup_count == 2
    assert unresolved.ontology == "unresolved"
    assert unresolved.normalized_id.startswith("UNRESOLVED:")
