"""Post-hoc PMID/DOI verification and citation-accuracy scoring."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, Field

from adda.orchestrator.state import AgentState

PMID_PATTERN = re.compile(r"(?:PMID[:\s]*)(\d{1,10})", re.IGNORECASE)
DOI_PATTERN = re.compile(r"(?:DOI[:\s]*)(10\.\d{4,9}/[^\s\]\)>,;]+)", re.IGNORECASE)


class CitationVerificationResult(BaseModel):
    """Citation verification output with an accuracy metric."""

    total_cited: int
    verified: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    citation_accuracy: float
    sanitized_report: str
    details: list[dict[str, Any]] = Field(default_factory=list)


def parse_pmids(text: str) -> list[str]:
    """Extract cited PMIDs from report text."""

    return sorted(set(PMID_PATTERN.findall(text)))


def parse_dois(text: str) -> list[str]:
    """Extract cited DOIs from report text."""

    return sorted({match.lower() for match in DOI_PATTERN.findall(text)})


def _strip_rejected_pmids(report: str, rejected_pmids: Sequence[str]) -> str:
    sanitized = report
    for pmid in rejected_pmids:
        sanitized = re.sub(
            rf"\s*\[?PMID[:\s]*{re.escape(pmid)}\]?",
            " [unverified PMID removed]",
            sanitized,
            flags=re.IGNORECASE,
        )
    return sanitized


class CitationVerifier:
    """Verify citations exist and are present in retrieved evidence."""

    def __init__(
        self,
        *,
        pmid_exists: Callable[[str], bool] | None = None,
        doi_exists: Callable[[str], bool] | None = None,
    ) -> None:
        self.pmid_exists = pmid_exists
        self.doi_exists = doi_exists

    def verify_report(
        self,
        report: str,
        *,
        evidence_pmids: Sequence[str],
        evidence_dois: Sequence[str] = (),
    ) -> CitationVerificationResult:
        """Verify cited identifiers against existence and retrieval-only sets."""

        evidence_pmid_set = set(evidence_pmids)
        evidence_doi_set = {doi.lower() for doi in evidence_dois}
        cited_pmids = parse_pmids(report)
        cited_dois = parse_dois(report)
        verified: list[str] = []
        rejected: list[str] = []
        details: list[dict[str, Any]] = []

        for pmid in cited_pmids:
            in_evidence = pmid in evidence_pmid_set
            exists = self.pmid_exists(pmid) if self.pmid_exists else in_evidence
            identifier = f"PMID:{pmid}"
            if in_evidence and exists:
                verified.append(identifier)
            else:
                rejected.append(identifier)
            details.append(
                {
                    "identifier": identifier,
                    "exists": exists,
                    "in_retrieved_evidence": in_evidence,
                    "verified": in_evidence and exists,
                }
            )

        for doi in cited_dois:
            in_evidence = doi in evidence_doi_set
            exists = self.doi_exists(doi) if self.doi_exists else in_evidence
            identifier = f"DOI:{doi}"
            if in_evidence and exists:
                verified.append(identifier)
            else:
                rejected.append(identifier)
            details.append(
                {
                    "identifier": identifier,
                    "exists": exists,
                    "in_retrieved_evidence": in_evidence,
                    "verified": in_evidence and exists,
                }
            )

        total = len(cited_pmids) + len(cited_dois)
        accuracy = round(len(verified) / total, 6) if total else 1.0
        rejected_pmids = [
            item.removeprefix("PMID:") for item in rejected if item.startswith("PMID:")
        ]
        return CitationVerificationResult(
            total_cited=total,
            verified=verified,
            rejected=rejected,
            citation_accuracy=accuracy,
            sanitized_report=_strip_rejected_pmids(report, rejected_pmids),
            details=details,
        )

    def verify_state(self, state: AgentState) -> AgentState:
        """Verify citations on a report-bearing AgentState."""

        state.refresh_retrieved_identifiers()
        report = state.report_markdown or ""
        result = self.verify_report(
            report,
            evidence_pmids=state.retrieved_pmids,
            evidence_dois=state.retrieved_dois,
        )
        state.report_markdown = result.sanitized_report
        state.citation_accuracy = result.citation_accuracy
        state.verified_citations = result.verified
        state.rejected_citations = result.rejected
        state.report_json = {
            **state.report_json,
            "citation_accuracy": result.citation_accuracy,
            "verified_citations": result.verified,
            "rejected_citations": result.rejected,
            "citation_details": result.details,
        }
        return state
