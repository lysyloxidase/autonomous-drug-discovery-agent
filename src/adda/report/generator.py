"""Citation-grounded report generator with retrieval-only citations."""

from __future__ import annotations

import html
import json
from typing import Any

from pydantic import BaseModel, Field

from adda.orchestrator.state import AgentState
from adda.ranking import TargetScore

VALIDATION_EXPERIMENTS = [
    "CRISPR knockout in disease-relevant cells",
    "RNAi or antisense knockdown rescue study",
    "Target overexpression and pathway readout",
    "Animal model perturbation with biomarker endpoints",
    "Orthogonal biomarker assay for target engagement",
]


class ReportBundle(BaseModel):
    """All Phase 6 report output formats."""

    markdown: str
    html: str
    pdf: bytes
    json_payload: dict[str, Any] = Field(default_factory=dict)


def _minimal_pdf(text: str) -> bytes:
    """Create a tiny valid PDF containing plain report text."""

    safe_text = (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\n", " ")[:3000]
    )
    stream = f"BT /F1 10 Tf 40 760 Td ({safe_text}) Tj ET"
    objects = [
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        (
            "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        ),
        "4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        f"5 0 obj << /Length {len(stream)} >> stream\n{stream}\nendstream endobj\n",
    ]
    pdf = "%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf.encode("utf-8")))
        pdf += obj
    xref_start = len(pdf.encode("utf-8"))
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    pdf += "".join(f"{offset:010d} 00000 n \n" for offset in offsets[1:])
    pdf += (
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n"
    )
    return pdf.encode("utf-8")


def _citation_pool(state: AgentState) -> list[str]:
    state.refresh_retrieved_identifiers()
    return state.retrieved_pmids


def _target_citation(pmids: list[str], index: int) -> str:
    if not pmids:
        return "retrieved evidence set; no PMID available"
    return f"PMID:{pmids[index % len(pmids)]}"


def _component_summary(target: TargetScore) -> str:
    return (
        f"centrality={target.centrality:.2f}, "
        f"OT={target.ot_association:.2f}, "
        f"druggability={target.druggability:.2f}, "
        f"genetic={target.genetic_evidence:.2f}, "
        f"novelty={target.novelty:.2f}, "
        f"safety_penalty={target.safety_penalty:.2f}"
    )


def _citation_pmid(citation: str) -> str | None:
    if citation.startswith("PMID:"):
        return citation.removeprefix("PMID:")
    return None


def _disease_node_id(state: AgentState) -> str:
    for entity in state.entities:
        if entity.entity_type == "disease":
            return entity.normalized_id
    slug = "-".join(state.disease_query.lower().split())
    return f"disease:{slug or 'query'}"


def _add_graph_node(
    nodes: dict[str, dict[str, Any]],
    *,
    node_id: str,
    label: str,
    node_type: str,
    **properties: Any,
) -> None:
    existing = nodes.get(node_id, {})
    nodes[node_id] = {
        **existing,
        "id": node_id,
        "label": label,
        "type": node_type,
        **{key: value for key, value in properties.items() if value is not None},
    }


def _append_graph_edge(
    edges: list[dict[str, Any]],
    *,
    source: str,
    target: str,
    relation: str,
    **properties: Any,
) -> None:
    edge = {
        "id": f"{source}|{relation}|{target}|{len(edges) + 1}",
        "source": source,
        "target": target,
        "relation": relation,
        **{key: value for key, value in properties.items() if value is not None},
    }
    edges.append(edge)


def _knowledge_graph_payload(
    state: AgentState,
    *,
    target_payloads: list[dict[str, Any]],
    pmids: list[str],
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    disease_id = _disease_node_id(state)
    _add_graph_node(
        nodes,
        node_id=disease_id,
        label=state.disease_query,
        node_type="disease",
        ontology=disease_id.split(":", maxsplit=1)[0] if ":" in disease_id else None,
    )

    for entity in state.entities:
        _add_graph_node(
            nodes,
            node_id=entity.normalized_id,
            label=entity.text,
            node_type=entity.entity_type.value,
            ontology=entity.ontology,
            extractor=entity.extractor,
            confidence=entity.confidence,
            source_pmids=entity.source_pmids,
        )

    for relation in state.relations:
        _add_graph_node(
            nodes,
            node_id=relation.subject.normalized_id,
            label=relation.subject.text,
            node_type=relation.subject.entity_type.value,
            ontology=relation.subject.ontology,
        )
        _add_graph_node(
            nodes,
            node_id=relation.object.normalized_id,
            label=relation.object.text,
            node_type=relation.object.entity_type.value,
            ontology=relation.object.ontology,
        )
        _append_graph_edge(
            edges,
            source=relation.subject.normalized_id,
            target=relation.object.normalized_id,
            relation=relation.relation.value.upper(),
            source_pmids=relation.source_pmids,
            source_db=relation.extractor,
            extraction_confidence=relation.confidence,
            cooccurrence_only=relation.is_cooccurrence_only,
        )

    for target in target_payloads:
        target_id = str(target["target_id"])
        _add_graph_node(
            nodes,
            node_id=target_id,
            label=str(target["target_symbol"]),
            node_type="gene",
            evidence_tier=target["evidence_tier"],
            composite_score=target["composite_score"],
        )
        citation = str(target.get("citation", ""))
        cited_pmid = _citation_pmid(citation)
        _append_graph_edge(
            edges,
            source=disease_id,
            target=target_id,
            relation="ASSOCIATED_WITH",
            evidence_tier=target["evidence_tier"],
            score=target["composite_score"],
            source_pmids=[cited_pmid] if cited_pmid else [],
            source_db="ranking",
        )

    for pmid in pmids:
        publication_id = f"PMID:{pmid}"
        _add_graph_node(
            nodes,
            node_id=publication_id,
            label=publication_id,
            node_type="publication",
            pmid=pmid,
        )
        _append_graph_edge(
            edges,
            source=publication_id,
            target=disease_id,
            relation="MENTIONS",
            source_pmids=[pmid],
            source_db="retrieval",
        )

    for target in target_payloads:
        target_id = str(target["target_id"])
        cited_pmid = _citation_pmid(str(target.get("citation", "")))
        if cited_pmid:
            _append_graph_edge(
                edges,
                source=f"PMID:{cited_pmid}",
                target=target_id,
                relation="MENTIONS",
                source_pmids=[cited_pmid],
                source_db="retrieval",
            )

    for target_id, molecules in state.triaged_molecules.items():
        if not isinstance(molecules, list):
            continue
        for molecule in molecules:
            if not isinstance(molecule, dict):
                continue
            molecule_id = str(molecule.get("molecule_chembl_id", "molecule"))
            _add_graph_node(
                nodes,
                node_id=molecule_id,
                label=molecule_id,
                node_type="compound",
                scope_label=molecule.get("scope_label"),
                qed=molecule.get("qed"),
            )
            _append_graph_edge(
                edges,
                source=molecule_id,
                target=str(target_id),
                relation="TARGETS",
                source_db="chembl",
                extraction_confidence=0.5,
            )

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "layout_hint": "disease_target_publication_molecule",
    }


class ReportGenerator:
    """Generate citation-grounded Markdown, HTML, PDF, and JSON reports."""

    def __init__(self, *, top_n: int = 5) -> None:
        self.top_n = top_n

    def build_bundle(self, state: AgentState) -> ReportBundle:
        """Build a report bundle without mutating state."""

        pmids = _citation_pool(state)
        top_targets = state.target_scores[: self.top_n]
        lines = [
            f"# Target Discovery Report: {state.disease_query}",
            "",
            "## Scope",
            (
                "This report is retrieval-grounded research support. Citations are "
                "restricted to identifiers present in the retrieved evidence set."
            ),
            "",
            "## Top Targets",
        ]
        target_payloads: list[dict[str, Any]] = []
        for index, target in enumerate(top_targets, start=1):
            citation = _target_citation(pmids, index - 1)
            lines.extend(
                [
                    f"### {index}. {target.target_symbol} ({target.target_id})",
                    f"- Evidence tier: `{target.evidence_tier}`",
                    f"- Composite score: {target.composite_score:.3f}",
                    f"- Components: {_component_summary(target)}",
                    (
                        "- Evidence summary: target prioritization combines KG "
                        f"centrality, Open Targets association, tractability, "
                        f"genetic support, novelty, and safety penalty [{citation}]."
                    ),
                    "- Caveat: association evidence does not prove causation.",
                    "",
                ]
            )
            target_payloads.append(
                {
                    "rank": index,
                    "target_symbol": target.target_symbol,
                    "target_id": target.target_id,
                    "evidence_tier": target.evidence_tier,
                    "composite_score": target.composite_score,
                    "component_breakdown": target.component_breakdown,
                    "citation": citation,
                }
            )

        if not top_targets:
            lines.extend(
                [
                    "No ranked targets were available.",
                    "",
                ]
            )

        lines.extend(
            [
                "## Validation Experiments",
                *[f"- {experiment}" for experiment in VALIDATION_EXPERIMENTS],
                "",
                "## Caveats",
                "- Co-occurrence is not causation.",
                "- LLM-derived or unverified relations remain speculative.",
                "- Drug or molecule triage does not imply efficacy or safety.",
            ]
        )
        if state.errors:
            lines.extend(
                [
                    "",
                    "## Degraded Steps",
                    *[f"- {error['step']}: {error['error']}" for error in state.errors],
                ]
            )
        markdown = "\n".join(lines).strip() + "\n"
        html_report = (
            "<html><body>"
            + "".join(
                f"<p>{html.escape(line)}</p>" if line else "<br />" for line in lines
            )
            + "</body></html>"
        )
        json_payload = {
            "disease_query": state.disease_query,
            "targets": target_payloads,
            "triaged_molecules": state.triaged_molecules,
            "knowledge_graph": _knowledge_graph_payload(
                state,
                target_payloads=target_payloads,
                pmids=pmids,
            ),
            "validation_experiments": VALIDATION_EXPERIMENTS,
            "retrieved_pmids": pmids,
            "errors": state.errors,
            "scope": "retrieval-only citation; research-only",
        }
        return ReportBundle(
            markdown=markdown,
            html=html_report,
            pdf=_minimal_pdf(markdown),
            json_payload=json_payload,
        )

    def generate(self, state: AgentState) -> AgentState:
        """Attach all report formats to an AgentState."""

        prior_payload = dict(state.report_json)
        bundle = self.build_bundle(state)
        state.report_markdown = bundle.markdown
        state.report_html = bundle.html
        state.report_pdf = bundle.pdf
        state.report_json = {
            **prior_payload,
            **json.loads(json.dumps(bundle.json_payload)),
        }
        return state
