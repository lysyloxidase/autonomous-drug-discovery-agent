from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_docker_compose_one_command_stack_declares_required_services() -> None:
    compose = yaml.safe_load(read("docker/docker-compose.yml"))
    services = compose["services"]

    assert {"neo4j", "ollama", "redis", "api"} <= set(services)
    assert services["api"]["ports"] == ["${ADDA_API_PORT:-8001}:8000"]
    assert services["api"]["build"]["dockerfile"] == "docker/Dockerfile"
    assert services["api"]["environment"]["NEO4J_URI"] == "bolt://neo4j:7687"
    assert services["api"]["environment"]["OLLAMA_HOST"] == "http://ollama:11434"
    assert (
        services["api"]["environment"]["ADDA_PULL_OLLAMA"] == "${ADDA_PULL_OLLAMA:-1}"
    )
    assert services["api"]["environment"]["REDIS_URL"] == "redis://redis:6379/0"
    assert services["ollama"]["volumes"] == ["ollama_data:/root/.ollama"]
    assert services["neo4j"]["ports"] == [
        "${ADDA_NEO4J_HTTP_PORT:-7475}:7474",
        "${ADDA_NEO4J_BOLT_PORT:-7688}:7687",
    ]
    assert services["ollama"]["ports"] == ["${ADDA_OLLAMA_PORT:-11435}:11434"]
    assert services["redis"]["ports"] == ["${ADDA_REDIS_PORT:-6380}:6379"]
    assert "ollama_data" in compose["volumes"]
    assert "neo4j_data" in compose["volumes"]


def test_dockerfile_and_entrypoint_run_fastapi_and_pull_ollama_model() -> None:
    dockerfile = read("docker/Dockerfile")
    entrypoint = read("docker/entrypoint.sh")

    assert "uvicorn" in dockerfile
    assert "adda.api.app:app" in dockerfile
    assert '"/entrypoint.sh"' in dockerfile
    assert "/api/pull" in entrypoint
    assert "OLLAMA_MODEL" in entrypoint


def test_ci_uses_cassettes_by_default_and_live_api_is_opt_in_only() -> None:
    workflow = yaml.safe_load(read(".github/workflows/ci.yml"))

    assert "push" in workflow[True]
    assert "pull_request" in workflow[True]
    assert "workflow_dispatch" in workflow[True]
    assert "lint-type-test" in workflow["jobs"]
    lint_steps = workflow["jobs"]["lint-type-test"]["steps"]
    run_commands = "\n".join(step.get("run", "") for step in lint_steps)
    assert "uv sync --frozen" in run_commands
    assert "ruff check" in run_commands
    assert "pyright" in run_commands
    assert "pytest --cov=adda --cov-fail-under=85" in run_commands
    assert "docker-build" in workflow["jobs"]
    assert "docker build -f docker/Dockerfile -t adda:ci ." in str(workflow)
    assert workflow["jobs"]["live-integration"]["if"] == (
        "github.event_name == 'workflow_dispatch'"
    )


def test_readme_contains_final_release_credibility_sections() -> None:
    readme = read("README.md")

    required = [
        "Quickstart (one command)",
        "[DEMO GIF HERE]",
        "Results table",
        "What is real vs mocked",
        "Architecture",
        "Agentic vs orchestrated",
        "Research-hypothesis-generating only",
        "NOT clinical advice",
        "Citation accuracy",
        "plan->retrieve->extract->build_kg->score_evidence",
    ]
    for text in required:
        assert text in readme


def test_caveats_and_changelog_are_release_ready() -> None:
    caveats = read("docs/caveats.md")
    changelog = read("CHANGELOG.md")
    numbered_caveats = [
        line for line in caveats.splitlines() if line and line[0].isdigit()
    ]

    assert len(numbered_caveats) >= 14
    assert "v1.0.0" in changelog or "[1.0.0]" in changelog
    assert "Phase 7" in changelog


def test_makefile_has_requested_demo_and_docker_targets() -> None:
    makefile = read("Makefile")

    assert "docker compose -f docker/docker-compose.yml up" in makefile
    assert (
        'uv run python -m adda.cli run --disease "idiopathic pulmonary fibrosis"'
        in makefile
    )
    assert "uv run mkdocs serve" in makefile
    assert "uv run pytest --cov=adda" in makefile
