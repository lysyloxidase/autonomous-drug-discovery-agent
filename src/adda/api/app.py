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
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
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

    disease: str = Field(min_length=1, examples=["idiopathic pulmonary fibrosis"])


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


def _demo_publications(disease: str) -> list[Publication]:
    return [
        Publication(
            canonical_id="pmid:21506741",
            pmid="21506741",
            doi="10.1056/NEJMoa1013660",
            title="Common MUC5B promoter variant and pulmonary fibrosis",
            sources=["demo-fixture"],
            citation_count=1200,
        ),
        Publication(
            canonical_id="pmid:33640084",
            pmid="33640084",
            title=f"Open Targets-style evidence synthesis for {disease}",
            sources=["demo-fixture"],
            citation_count=180,
        ),
        Publication(
            canonical_id="pmid:30190408",
            pmid="30190408",
            title="Fibrosis target biology and translational validation",
            sources=["demo-fixture"],
            citation_count=420,
        ),
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
        publications = _demo_publications(state.disease_query)
        state.corpus = Corpus(
            disease_query=state.disease_query,
            publications=publications,
            per_source_counts={
                "pubmed": 3,
                "europepmc": 3,
                "openalex": 3,
                "pubtator3": 3,
            },
            retrieved_at=datetime.now(UTC).isoformat(),
        )
        return state

    def extract(state: AgentState) -> AgentState:
        pmids = (
            [publication.pmid for publication in state.corpus.publications]
            if state.corpus
            else []
        )
        source_pmids = [pmid for pmid in pmids if pmid]
        state.entities = [
            Entity(
                text="idiopathic pulmonary fibrosis",
                entity_type=EntityType.DISEASE,
                normalized_id="EFO:0000768",
                ontology="EFO",
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
                for symbol, target_id in (
                    ("MUC5B", "NCBI:727897"),
                    ("TGFB1", "NCBI:7040"),
                    ("MMP7", "NCBI:4316"),
                    ("TERT", "NCBI:7015"),
                    ("SFTPC", "NCBI:6440"),
                )
            ],
        ]
        state.relations = []
        return state

    def build_kg(state: AgentState) -> AgentState:
        state.kg_built = True
        state.report_json = {
            **state.report_json,
            "kg_nodes": len(state.entities) + 1,
            "kg_relations": 5,
        }
        return state

    def score_evidence(state: AgentState) -> AgentState:
        state.report_json = {
            **state.report_json,
            "evidence_scored": True,
            "extraction_precision_vs_pubtator3": 0.667,
            "extraction_recall_vs_pubtator3": 1.0,
        }
        return state

    def rank_targets(state: AgentState) -> AgentState:
        state.target_scores = [
            _target_score(
                symbol="MUC5B",
                target_id="NCBI:727897",
                tier="robust",
                composite=0.91,
                genetic=0.95,
                druggability=0.42,
            ),
            _target_score(
                symbol="TGFB1",
                target_id="NCBI:7040",
                tier="robust",
                composite=0.86,
                genetic=0.72,
                druggability=0.58,
            ),
            _target_score(
                symbol="MMP7",
                target_id="NCBI:4316",
                tier="plausible",
                composite=0.79,
                genetic=0.52,
                druggability=0.64,
            ),
            _target_score(
                symbol="TERT",
                target_id="NCBI:7015",
                tier="plausible",
                composite=0.74,
                genetic=0.76,
                druggability=0.3,
            ),
            _target_score(
                symbol="SFTPC",
                target_id="NCBI:6440",
                tier="plausible",
                composite=0.69,
                genetic=0.68,
                druggability=0.34,
            ),
        ]
        return state

    def triage(state: AgentState) -> AgentState:
        state.triaged_molecules = {
            "NCBI:7040": [
                {
                    "molecule_chembl_id": "CHEMBL_DEMO_TGFB1",
                    "scope_label": (
                        "known actives only; not de novo design; not docking"
                    ),
                    "qed": 0.42,
                }
            ]
        }
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
