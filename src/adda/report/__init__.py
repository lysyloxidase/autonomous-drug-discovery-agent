"""Citation-grounded report generation and verification."""

from adda.report.generator import ReportBundle, ReportGenerator
from adda.report.verify_citations import (
    CitationVerificationResult,
    CitationVerifier,
    parse_dois,
    parse_pmids,
)

__all__ = [
    "CitationVerificationResult",
    "CitationVerifier",
    "ReportBundle",
    "ReportGenerator",
    "parse_dois",
    "parse_pmids",
]
