"""FastAPI async job API for autonomous-drug-discovery-agent."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
)
from fastapi.staticfiles import StaticFiles
from neo4j import GraphDatabase
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from adda.extraction.models import Entity, EntityType
from adda.models.corpus import Corpus, Publication
from adda.orchestrator import (
    BuildKGTool,
    CustomOrchestrator,
    EvidenceTool,
    ExtractTool,
    RankTool,
    ReportTool,
    RetrieveTool,
    Tool,
    TriageTool,
    VerifyCitationsTool,
)
from adda.orchestrator.state import AgentState
from adda.ranking import TargetScore


class JobState(StrEnum):
    """API job lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReportFormat(StrEnum):
    """Supported report result formats."""

    MARKDOWN = "markdown"
    HTML = "html"
    PDF = "pdf"
    JSON = "json"


class JobSubmit(BaseModel):
    """Submit a disease run."""

    disease: str = Field(
        min_length=1,
        examples=[
            "idiopathic pulmonary fibrosis",
            "glioblastoma",
            "TNBC",
            "endometriosis",
        ],
    )


class JobSubmitResponse(BaseModel):
    """Submitted job ID."""

    job_id: str
    status: JobState


RESULT_FORMAT_QUERY: Any = Query(default=ReportFormat.JSON)


class JobStatusResponse(BaseModel):
    """Polling status response."""

    job_id: str
    status: JobState
    disease: str
    created_at: str
    updated_at: str
    completed_steps: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    citation_accuracy: float | None = None


@dataclass
class JobRecord:
    """In-memory single-server job record."""

    job_id: str
    disease: str
    status: JobState = JobState.QUEUED
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    events: list[dict[str, Any]] = field(default_factory=list)
    result: AgentState | None = None
    error: str | None = None

    def to_status(self) -> JobStatusResponse:
        """Return a Pydantic status DTO."""

        return JobStatusResponse(
            job_id=self.job_id,
            status=self.status,
            disease=self.disease,
            created_at=self.created_at,
            updated_at=self.updated_at,
            completed_steps=self.result.completed_steps if self.result else [],
            errors=self.result.errors if self.result else [],
            citation_accuracy=self.result.citation_accuracy if self.result else None,
        )

    def append_event(self, event: dict[str, Any]) -> None:
        """Append one SSE event and update the timestamp."""

        self.events.append(event)
        self.updated_at = datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class DemoPublication:
    """One committed PubMed-backed publication in a local demo fixture."""

    pmid: str
    title: str
    doi: str | None = None
    citation_count: int = 0


@dataclass(frozen=True)
class DemoTarget:
    """One ranked target in a committed local demo fixture."""

    symbol: str
    target_id: str
    tier: str
    composite: float
    genetic: float
    druggability: float


@dataclass(frozen=True)
class DemoMolecule:
    """Known-active molecule triage entry for the local browser demo."""

    target_id: str
    molecule_chembl_id: str
    scope_label: str
    qed: float


@dataclass(frozen=True)
class DemoDiseaseFixture:
    """Deterministic disease fixture used by the local app and CI smoke tests."""

    key: str
    canonical_name: str
    disease_id: str
    ontology: str
    aliases: tuple[str, ...]
    publications: tuple[DemoPublication, ...]
    targets: tuple[DemoTarget, ...]
    molecules: tuple[DemoMolecule, ...]
    extraction_precision: float
    extraction_recall: float

    @property
    def kg_node_count(self) -> int:
        """Return the deterministic graph size surfaced in the demo metrics."""

        molecule_ids = {molecule.molecule_chembl_id for molecule in self.molecules}
        return 1 + len(self.targets) + len(self.publications) + len(molecule_ids)

    @property
    def kg_relation_count(self) -> int:
        """Return the deterministic edge count surfaced in the demo metrics."""

        return len(self.targets) * 2 + len(self.publications) + len(self.molecules)


IPF_FIXTURE = DemoDiseaseFixture(
    key="ipf",
    canonical_name="idiopathic pulmonary fibrosis",
    disease_id="EFO:0000768",
    ontology="EFO",
    aliases=("idiopathic pulmonary fibrosis", "ipf", "pulmonary fibrosis"),
    publications=(
        DemoPublication(
            pmid="21506741",
            doi="10.1056/NEJMoa1013660",
            title="Common MUC5B promoter variant and pulmonary fibrosis",
            citation_count=1200,
        ),
        DemoPublication(
            pmid="33640084",
            title=(
                "Open Targets-style evidence synthesis for idiopathic "
                "pulmonary fibrosis"
            ),
            citation_count=180,
        ),
        DemoPublication(
            pmid="30190408",
            title="Fibrosis target biology and translational validation",
            citation_count=420,
        ),
    ),
    targets=(
        DemoTarget("MUC5B", "NCBI:727897", "robust", 0.91, 0.95, 0.42),
        DemoTarget("TGFB1", "NCBI:7040", "robust", 0.86, 0.72, 0.58),
        DemoTarget("MMP7", "NCBI:4316", "plausible", 0.79, 0.52, 0.64),
        DemoTarget("TERT", "NCBI:7015", "plausible", 0.74, 0.76, 0.30),
        DemoTarget("SFTPC", "NCBI:6440", "plausible", 0.69, 0.68, 0.34),
    ),
    molecules=(
        DemoMolecule(
            target_id="NCBI:7040",
            molecule_chembl_id="CHEMBL_DEMO_TGFB1",
            scope_label="known actives only; not de novo design; not docking",
            qed=0.42,
        ),
    ),
    extraction_precision=0.667,
    extraction_recall=1.0,
)


DEMO_FIXTURES = (
    IPF_FIXTURE,
    DemoDiseaseFixture(
        key="glioblastoma",
        canonical_name="glioblastoma",
        disease_id="EFO:0000519",
        ontology="EFO",
        aliases=("glioblastoma", "gbm", "glioblastoma multiforme"),
        publications=(
            DemoPublication(
                pmid="18772890",
                doi="10.1038/nature07385",
                title=(
                    "Comprehensive genomic characterization defines human "
                    "glioblastoma genes and core pathways"
                ),
                citation_count=2600,
            ),
            DemoPublication(
                pmid="15758010",
                doi="10.1056/NEJMoa043331",
                title=(
                    "MGMT gene silencing and benefit from temozolomide in glioblastoma"
                ),
                citation_count=4800,
            ),
            DemoPublication(
                pmid="18772396",
                doi="10.1126/science.1164382",
                title="An integrated genomic analysis of human glioblastoma multiforme",
                citation_count=2700,
            ),
            DemoPublication(
                pmid="23530248",
                doi="10.1073/pnas.1303607110",
                title=(
                    "TERT promoter mutations occur frequently in gliomas and "
                    "a subset of tumors derived from cells with low rates of "
                    "self-renewal"
                ),
                citation_count=1800,
            ),
            DemoPublication(
                pmid="20129251",
                doi="10.1016/j.ccr.2009.12.020",
                title=(
                    "Integrated genomic analysis identifies clinically relevant "
                    "subtypes of glioblastoma characterized by abnormalities in "
                    "PDGFRA, IDH1, EGFR, and NF1"
                ),
                citation_count=3000,
            ),
        ),
        targets=(
            DemoTarget("EGFR", "NCBI:1956", "robust", 0.90, 0.78, 0.72),
            DemoTarget("MGMT", "NCBI:4255", "robust", 0.86, 0.70, 0.40),
            DemoTarget("IDH1", "NCBI:3417", "robust", 0.82, 0.88, 0.58),
            DemoTarget("TERT", "NCBI:7015", "plausible", 0.76, 0.74, 0.32),
            DemoTarget("PDGFRA", "NCBI:5156", "plausible", 0.72, 0.62, 0.68),
        ),
        molecules=(
            DemoMolecule(
                target_id="NCBI:1956",
                molecule_chembl_id="CHEMBL_DEMO_EGFR",
                scope_label="known EGFR-targeting active; research triage only",
                qed=0.55,
            ),
            DemoMolecule(
                target_id="NCBI:3417",
                molecule_chembl_id="CHEMBL_DEMO_IDH1",
                scope_label="known IDH1-targeting active; research triage only",
                qed=0.61,
            ),
            DemoMolecule(
                target_id="NCBI:5156",
                molecule_chembl_id="CHEMBL_DEMO_PDGFRA",
                scope_label="known PDGFRA-targeting active; research triage only",
                qed=0.50,
            ),
        ),
        extraction_precision=0.648,
        extraction_recall=0.923,
    ),
    DemoDiseaseFixture(
        key="tnbc",
        canonical_name="triple-negative breast cancer",
        disease_id="MONDO:0007254",
        ontology="MONDO",
        aliases=(
            "tnbc",
            "triple negative breast cancer",
            "triple-negative breast cancer",
        ),
        publications=(
            DemoPublication(
                pmid="21633166",
                doi="10.1172/JCI45014",
                title=(
                    "Identification of human triple-negative breast cancer "
                    "subtypes and preclinical models for selection of "
                    "targeted therapies"
                ),
                citation_count=2400,
            ),
            DemoPublication(
                pmid="28578601",
                doi="10.1056/NEJMoa1706450",
                title=(
                    "Olaparib for metastatic breast cancer in patients with a "
                    "germline BRCA mutation"
                ),
                citation_count=2100,
            ),
            DemoPublication(
                pmid="30345906",
                doi="10.1056/NEJMoa1809615",
                title=(
                    "Atezolizumab and nab-paclitaxel in advanced "
                    "triple-negative breast cancer"
                ),
                citation_count=1900,
            ),
            DemoPublication(
                pmid="29883487",
                doi="10.1371/journal.pone.0197827",
                title=(
                    "Androgen receptor positive triple negative breast cancer: "
                    "clinicopathologic, prognostic, and predictive features"
                ),
                citation_count=260,
            ),
        ),
        targets=(
            DemoTarget("BRCA1", "NCBI:672", "robust", 0.88, 0.90, 0.40),
            DemoTarget("PARP1", "NCBI:142", "robust", 0.84, 0.70, 0.76),
            DemoTarget("CD274", "NCBI:29126", "robust", 0.80, 0.42, 0.66),
            DemoTarget("EGFR", "NCBI:1956", "plausible", 0.73, 0.35, 0.72),
            DemoTarget("AR", "NCBI:367", "plausible", 0.69, 0.40, 0.62),
        ),
        molecules=(
            DemoMolecule(
                target_id="NCBI:142",
                molecule_chembl_id="CHEMBL_DEMO_PARPI",
                scope_label="known PARP-active class exemplar; research triage only",
                qed=0.58,
            ),
            DemoMolecule(
                target_id="NCBI:29126",
                molecule_chembl_id="CHEMBL_DEMO_PDL1",
                scope_label=(
                    "known immune-checkpoint modality exemplar; not a "
                    "small-molecule claim"
                ),
                qed=0.30,
            ),
            DemoMolecule(
                target_id="NCBI:1956",
                molecule_chembl_id="CHEMBL_DEMO_EGFR",
                scope_label="known EGFR-targeting active; research triage only",
                qed=0.55,
            ),
        ),
        extraction_precision=0.641,
        extraction_recall=0.909,
    ),
    DemoDiseaseFixture(
        key="endometriosis",
        canonical_name="endometriosis",
        disease_id="EFO:0001065",
        ontology="EFO",
        aliases=("endometriosis",),
        publications=(
            DemoPublication(
                pmid="12650711",
                doi="10.1016/s0960-0760(02)00260-1",
                title=(
                    "Endometriosis: the pathophysiology as an "
                    "estrogen-dependent disease"
                ),
                citation_count=920,
            ),
            DemoPublication(
                pmid="8755660",
                doi="10.1172/JCI118815",
                title=(
                    "Vascular endothelial growth factor is produced by "
                    "peritoneal fluid macrophages in endometriosis and is "
                    "regulated by ovarian steroids"
                ),
                citation_count=1050,
            ),
            DemoPublication(
                pmid="18053993",
                doi="10.1016/j.fertnstert.2007.07.1332",
                title=(
                    "Expression of cyclooxygenase-2 and vascular endothelial "
                    "growth factor in ovarian endometriotic cysts and their "
                    "relationship with angiogenesis"
                ),
                citation_count=430,
            ),
            DemoPublication(
                pmid="1281760",
                doi="10.1016/0009-8981(92)90204-4",
                title=(
                    "IL6 and acute phase plasma proteins in peritoneal fluid "
                    "of women with endometriosis"
                ),
                citation_count=260,
            ),
        ),
        targets=(
            DemoTarget("ESR1", "NCBI:2099", "robust", 0.82, 0.58, 0.62),
            DemoTarget("PGR", "NCBI:5241", "plausible", 0.78, 0.48, 0.58),
            DemoTarget("VEGFA", "NCBI:7422", "plausible", 0.74, 0.42, 0.66),
            DemoTarget("PTGS2", "NCBI:5743", "plausible", 0.70, 0.35, 0.70),
            DemoTarget("IL6", "NCBI:3569", "plausible", 0.66, 0.32, 0.62),
        ),
        molecules=(
            DemoMolecule(
                target_id="NCBI:2099",
                molecule_chembl_id="CHEMBL_DEMO_ESR1",
                scope_label="known estrogen-receptor active; research triage only",
                qed=0.47,
            ),
            DemoMolecule(
                target_id="NCBI:5743",
                molecule_chembl_id="CHEMBL_DEMO_COX2",
                scope_label="known COX-2 active class exemplar; research triage only",
                qed=0.63,
            ),
            DemoMolecule(
                target_id="NCBI:3569",
                molecule_chembl_id="CHEMBL_DEMO_IL6",
                scope_label=(
                    "known IL-6 pathway modality exemplar; not a small-molecule claim"
                ),
                qed=0.28,
            ),
        ),
        extraction_precision=0.612,
        extraction_recall=0.889,
    ),
)


def _normalize_demo_key(value: str) -> str:
    return " ".join(value.strip().lower().replace("-", " ").split())


DEMO_FIXTURES_BY_ALIAS = {
    _normalize_demo_key(alias): fixture
    for fixture in DEMO_FIXTURES
    for alias in (fixture.canonical_name, fixture.key, *fixture.aliases)
}


def _fixture_for_disease(disease: str) -> DemoDiseaseFixture:
    return DEMO_FIXTURES_BY_ALIAS.get(_normalize_demo_key(disease), IPF_FIXTURE)


def _demo_publications(fixture: DemoDiseaseFixture) -> list[Publication]:
    return [
        Publication(
            canonical_id=f"pmid:{publication.pmid}",
            pmid=publication.pmid,
            doi=publication.doi,
            title=publication.title,
            sources=["demo-fixture", fixture.key],
            citation_count=publication.citation_count,
        )
        for publication in fixture.publications
    ]


def _target_score(
    *,
    symbol: str,
    target_id: str,
    tier: str,
    composite: float,
    genetic: float,
    druggability: float,
) -> TargetScore:
    centrality = min(composite + 0.05, 1.0)
    ot_association = min(composite + 0.03, 1.0)
    novelty = max(0.2, 1.0 - composite / 2)
    safety_penalty = 0.1 if tier == "robust" else 0.18
    return TargetScore(
        target_symbol=symbol,
        target_id=target_id,
        centrality=round(centrality, 3),
        ot_association=round(ot_association, 3),
        druggability=druggability,
        genetic_evidence=genetic,
        novelty=round(novelty, 3),
        safety_penalty=safety_penalty,
        composite_score=composite,
        evidence_tier=tier,
        component_breakdown={
            "centrality": round(centrality, 3),
            "ot_association": round(ot_association, 3),
            "druggability": druggability,
            "genetic_evidence": genetic,
            "novelty": round(novelty, 3),
            "safety_penalty": safety_penalty,
        },
    )


def create_demo_tools() -> list[Tool]:
    """Create deterministic no-live-API tools for CI and compose demos."""

    def retrieve(state: AgentState) -> AgentState:
        fixture = _fixture_for_disease(state.disease_query)
        publications = _demo_publications(fixture)
        source_count = len(publications)
        state.corpus = Corpus(
            disease_query=state.disease_query,
            publications=publications,
            per_source_counts={
                "pubmed": source_count,
                "europepmc": source_count,
                "openalex": source_count,
                "pubtator3": source_count,
            },
            retrieved_at=datetime.now(UTC).isoformat(),
        )
        state.report_json = {
            **state.report_json,
            "demo_fixture": fixture.canonical_name,
            "demo_fixture_scope": (
                "deterministic local demo fixture; not a live biomedical claim"
            ),
        }
        return state

    def extract(state: AgentState) -> AgentState:
        fixture = _fixture_for_disease(state.disease_query)
        pmids = (
            [publication.pmid for publication in state.corpus.publications]
            if state.corpus
            else []
        )
        source_pmids = [pmid for pmid in pmids if pmid]
        state.entities = [
            Entity(
                text=fixture.canonical_name,
                entity_type=EntityType.DISEASE,
                normalized_id=fixture.disease_id,
                ontology=fixture.ontology,
                source_pmids=source_pmids,
                extractor="demo_fixture",
                confidence=1.0,
            ),
            *[
                Entity(
                    text=symbol,
                    entity_type=EntityType.GENE,
                    normalized_id=target_id,
                    ontology="NCBI Gene",
                    source_pmids=source_pmids,
                    extractor="demo_fixture",
                    confidence=0.95,
                )
                for target in fixture.targets
                for symbol, target_id in ((target.symbol, target.target_id),)
            ],
        ]
        state.relations = []
        return state

    def build_kg(state: AgentState) -> AgentState:
        fixture = _fixture_for_disease(state.disease_query)
        state.kg_built = True
        state.report_json = {
            **state.report_json,
            "kg_nodes": fixture.kg_node_count,
            "kg_relations": fixture.kg_relation_count,
        }
        return state

    def score_evidence(state: AgentState) -> AgentState:
        fixture = _fixture_for_disease(state.disease_query)
        state.report_json = {
            **state.report_json,
            "evidence_scored": True,
            "extraction_precision_vs_pubtator3": fixture.extraction_precision,
            "extraction_recall_vs_pubtator3": fixture.extraction_recall,
        }
        return state

    def rank_targets(state: AgentState) -> AgentState:
        fixture = _fixture_for_disease(state.disease_query)
        state.target_scores = [
            _target_score(
                symbol=target.symbol,
                target_id=target.target_id,
                tier=target.tier,
                composite=target.composite,
                genetic=target.genetic,
                druggability=target.druggability,
            )
            for target in fixture.targets
        ]
        return state

    def triage(state: AgentState) -> AgentState:
        fixture = _fixture_for_disease(state.disease_query)
        triaged: dict[str, list[dict[str, object]]] = {}
        for molecule in fixture.molecules:
            triaged.setdefault(molecule.target_id, []).append(
                {
                    "molecule_chembl_id": molecule.molecule_chembl_id,
                    "scope_label": molecule.scope_label,
                    "qed": molecule.qed,
                }
            )
        state.triaged_molecules = triaged
        return state

    return [
        RetrieveTool(runner=retrieve),
        ExtractTool(runner=extract),
        BuildKGTool(runner=build_kg),
        EvidenceTool(runner=score_evidence),
        RankTool(runner=rank_targets),
        TriageTool(runner=triage, continue_on_error=True),
        ReportTool(),
        VerifyCitationsTool(),
    ]


class JobManager:
    """Single-process async job manager for FastAPI."""

    def __init__(
        self,
        *,
        tools: Sequence[Tool] | None = None,
        checkpoint_dir: str | Path | None = None,
    ) -> None:
        self.tools = list(tools or create_demo_tools())
        self.checkpoint_dir = Path(
            checkpoint_dir
            or os.getenv("ADDA_CHECKPOINT_DIR")
            or Path(tempfile.gettempdir()) / "adda-checkpoints"
        )
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, JobRecord] = {}

    def submit(self, disease: str, background_tasks: BackgroundTasks) -> JobRecord:
        """Create a job and schedule execution."""

        job_id = str(uuid.uuid4())
        record = JobRecord(job_id=job_id, disease=disease)
        record.append_event({"event": "queued", "job_id": job_id, "disease": disease})
        self.jobs[job_id] = record
        background_tasks.add_task(self.run_job, job_id)
        return record

    def get(self, job_id: str) -> JobRecord:
        """Return one job record or 404."""

        record = self.jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return record

    def run_job(self, job_id: str) -> None:
        """Run one job synchronously inside FastAPI background execution."""

        record = self.jobs[job_id]
        record.status = JobState.RUNNING
        record.updated_at = datetime.now(UTC).isoformat()
        orchestrator = CustomOrchestrator(
            self.tools,
            self.checkpoint_dir / job_id,
            wait_multiplier=0.05,
        )
        try:
            for event in orchestrator.stream(record.disease):
                record.append_event(event)
                if event["event"] == "complete":
                    record.result = AgentState.model_validate(event["state"])
            record.status = JobState.SUCCEEDED
        except Exception as exc:  # pragma: no cover - defensive API boundary
            record.status = JobState.FAILED
            record.error = str(exc)
            record.append_event(
                {"event": "failed", "job_id": job_id, "error": record.error}
            )
        finally:
            record.updated_at = datetime.now(UTC).isoformat()


def _serialize_sse(event: dict[str, Any]) -> dict[str, str]:
    event_name = str(event.get("event", "message"))
    return {"event": event_name, "data": json.dumps(event, default=str)}


async def _stream_job(record: JobRecord) -> AsyncIterator[dict[str, str]]:
    index = 0
    while True:
        while index < len(record.events):
            yield _serialize_sse(record.events[index])
            index += 1
        if record.status in {JobState.SUCCEEDED, JobState.FAILED}:
            break
        await asyncio.sleep(0.05)


async def _check_ollama() -> dict[str, Any]:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            response = await client.get(f"{host}/api/tags")
        return {"ok": response.status_code < 500, "url": host}
    except Exception as exc:
        return {"ok": False, "url": host, "error": str(exc)}


def _check_neo4j_sync() -> dict[str, Any]:
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "addadev123")
    try:
        driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            connection_timeout=1,
        )
        try:
            driver.verify_connectivity()
        finally:
            driver.close()
        return {"ok": True, "uri": uri}
    except Exception as exc:
        return {"ok": False, "uri": uri, "error": str(exc)}


async def _check_neo4j() -> dict[str, Any]:
    return await asyncio.to_thread(_check_neo4j_sync)


def create_app(job_manager: JobManager | None = None) -> FastAPI:
    """Create the FastAPI app."""

    manager = job_manager or JobManager()
    app = FastAPI(title="autonomous-drug-discovery-agent", version="1.0")
    static_dir = Path(__file__).with_name("static")
    app.mount("/assets", StaticFiles(directory=static_dir), name="assets")

    @app.get("/", include_in_schema=False)
    async def browser_app() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.post("/jobs", response_model=JobSubmitResponse)
    async def submit_job(
        payload: JobSubmit,
        background_tasks: BackgroundTasks,
    ) -> JobSubmitResponse:
        record = manager.submit(payload.disease, background_tasks)
        return JobSubmitResponse(job_id=record.job_id, status=record.status)

    @app.get("/jobs/{job_id}/stream")
    async def stream_progress(job_id: str) -> EventSourceResponse:
        record = manager.get(job_id)
        return EventSourceResponse(_stream_job(record))

    @app.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
    async def job_status(job_id: str) -> JobStatusResponse:
        return manager.get(job_id).to_status()

    @app.get("/jobs/{job_id}/result")
    async def job_result(
        job_id: str,
        format: ReportFormat = RESULT_FORMAT_QUERY,
    ) -> Response:
        record = manager.get(job_id)
        if record.status != JobState.SUCCEEDED or record.result is None:
            raise HTTPException(status_code=409, detail="job has not completed")
        state = record.result
        if format is ReportFormat.MARKDOWN:
            return PlainTextResponse(state.report_markdown or "")
        if format is ReportFormat.HTML:
            return HTMLResponse(state.report_html or "")
        if format is ReportFormat.PDF:
            return Response(
                state.report_pdf or b"",
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="{job_id}.pdf"'},
            )
        payload = {
            "job_id": job_id,
            "status": record.status,
            "report": state.report_json,
            "markdown": state.report_markdown,
            "html": state.report_html,
            "pdf_base64": base64.b64encode(state.report_pdf or b"").decode("ascii"),
        }
        return JSONResponse(payload)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        neo4j, ollama = await asyncio.gather(_check_neo4j(), _check_ollama())
        components = {"api": {"ok": True}, "neo4j": neo4j, "ollama": ollama}
        ok = all(component["ok"] for component in components.values())
        return {"status": "ok" if ok else "degraded", "components": components}

    return app


app = create_app()
