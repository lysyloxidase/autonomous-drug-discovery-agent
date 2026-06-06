from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from adda.api.app import JobManager, JobRecord, create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(JobManager(checkpoint_dir=tmp_path))
    return TestClient(app)


def submit_job(
    client: TestClient, disease: str = "idiopathic pulmonary fibrosis"
) -> str:
    response = client.post("/jobs", json={"disease": disease})
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"]
    return str(payload["job_id"])


def test_submit_status_stream_and_result_formats(client: TestClient) -> None:
    job_id = submit_job(client)

    status = client.get(f"/jobs/{job_id}/status")
    assert status.status_code == 200
    assert status.json()["status"] == "succeeded"
    assert status.json()["citation_accuracy"] == 1.0

    with client.stream("GET", f"/jobs/{job_id}/stream") as response:
        stream_text = response.read().decode()

    assert response.status_code == 200
    assert "step_started" in stream_text
    assert "verify_citations" in stream_text
    assert "complete" in stream_text

    json_result = client.get(f"/jobs/{job_id}/result?format=json")
    markdown_result = client.get(f"/jobs/{job_id}/result?format=markdown")
    html_result = client.get(f"/jobs/{job_id}/result?format=html")
    pdf_result = client.get(f"/jobs/{job_id}/result?format=pdf")

    assert json_result.status_code == 200
    assert json_result.json()["report"]["citation_accuracy"] == 1.0
    assert json_result.json()["pdf_base64"]
    assert "Target Discovery Report" in markdown_result.text
    assert "text/html" in html_result.headers["content-type"]
    assert pdf_result.content.startswith(b"%PDF")
    assert pdf_result.headers["content-type"] == "application/pdf"
    assert "triaged_molecules" in json_result.json()["report"]


@pytest.mark.parametrize(
    ("disease", "fixture", "top_target", "publication_count"),
    [
        ("glioblastoma", "glioblastoma", "EGFR", 5),
        ("TNBC", "triple-negative breast cancer", "BRCA1", 4),
        ("endometriosis", "endometriosis", "ESR1", 4),
    ],
)
def test_demo_disease_fixtures_return_rankings_and_graph(
    client: TestClient,
    disease: str,
    fixture: str,
    top_target: str,
    publication_count: int,
) -> None:
    job_id = submit_job(client, disease)

    response = client.get(f"/jobs/{job_id}/result?format=json")
    assert response.status_code == 200
    report = response.json()["report"]
    graph = report["knowledge_graph"]

    assert report["demo_fixture"] == fixture
    assert report["targets"][0]["target_symbol"] == top_target
    assert len(report["targets"]) == 5
    assert len(report["retrieved_pmids"]) == publication_count
    assert report["citation_accuracy"] == 1.0
    assert report["kg_nodes"] >= 10
    assert report["kg_relations"] >= 14
    assert any(node["label"] == top_target for node in graph["nodes"])
    assert any(edge["relation"] == "ASSOCIATED_WITH" for edge in graph["edges"])
    assert any(report["triaged_molecules"].values())


def test_result_before_completion_returns_conflict(tmp_path: Path) -> None:
    manager = JobManager(checkpoint_dir=tmp_path)
    app = create_app(manager)
    client = TestClient(app)
    manager.jobs["queued-job"] = JobRecord(
        job_id="queued-job",
        disease="glioblastoma",
    )

    response = client.get("/jobs/queued-job/result")

    assert response.status_code == 409


def test_missing_job_returns_404(client: TestClient) -> None:
    response = client.get("/jobs/not-a-job/status")

    assert response.status_code == 404


def test_health_reports_component_statuses(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_neo4j() -> dict[str, Any]:
        return {"ok": True, "uri": "bolt://neo4j:7687"}

    async def fake_ollama() -> dict[str, Any]:
        return {"ok": True, "url": "http://ollama:11434"}

    api_app = importlib.import_module("adda.api.app")
    monkeypatch.setattr(api_app, "_check_neo4j", fake_neo4j)
    monkeypatch.setattr(api_app, "_check_ollama", fake_ollama)
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["components"]["neo4j"]["ok"] is True
    assert response.json()["components"]["ollama"]["ok"] is True


def test_browser_app_serves_target_discovery_ui(client: TestClient) -> None:
    response = client.get("/")
    script = client.get("/assets/app.js")
    styles = client.get("/assets/styles.css")

    assert response.status_code == 200
    assert "Therapeutic target research console" in response.text
    assert "Knowledge graph" in response.text
    assert "glioblastoma" in response.text
    assert "endometriosis" in response.text
    assert "/assets/app.js" in response.text
    assert script.status_code == 200
    assert "renderKnowledgeGraph" in script.text
    assert "renderEvidence" in script.text
    assert styles.status_code == 200
    assert ".graph-panel" in styles.text
    assert ".insight-grid" in styles.text
