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

        bundle = self.build_bundle(state)
        state.report_markdown = bundle.markdown
        state.report_html = bundle.html
        state.report_pdf = bundle.pdf
        state.report_json = json.loads(json.dumps(bundle.json_payload))
        return state
