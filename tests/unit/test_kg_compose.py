from __future__ import annotations

from pathlib import Path

import yaml


def test_compose_neo4j_enables_apoc_and_gds_plugins() -> None:
    compose = yaml.safe_load(
        Path("docker/docker-compose.yml").read_text(encoding="utf-8")
    )
    neo4j = compose["services"]["neo4j"]
    environment = neo4j["environment"]

    assert neo4j["image"] == "neo4j:5-community"
    assert environment["NEO4J_AUTH"] == "neo4j/addadev123"
    assert "apoc" in environment["NEO4J_PLUGINS"]
    assert "graph-data-science" in environment["NEO4J_PLUGINS"]
    assert environment["NEO4J_dbms_security_procedures_unrestricted"] == "apoc.*,gds.*"
    assert "neo4j_data:/data" in neo4j["volumes"]
