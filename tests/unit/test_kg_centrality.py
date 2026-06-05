from __future__ import annotations

from typing import Any

import pandas as pd

from adda.kg.centrality import CentralityEngine, normalize_scores


class FakeGDS:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run_cypher(self, query: str, *, params: dict[str, Any]) -> pd.DataFrame:
        self.calls.append((query, params))
        if "pageRank" in query:
            return pd.DataFrame([{"id": "7157", "labels": ["Gene"], "score": 4.0}])
        if "degree" in query:
            return pd.DataFrame(
                [
                    {"id": "7157", "labels": ["Gene"], "score": 10.0},
                    {"id": "1956", "labels": ["Gene"], "score": 5.0},
                ]
            )
        if "betweenness" in query:
            return pd.DataFrame(
                [
                    {"id": "7157", "labels": ["Gene"], "score": 0.0},
                    {"id": "1956", "labels": ["Gene"], "score": 2.0},
                ]
            )
        return pd.DataFrame()


def test_project_disease_neighborhood_uses_gds_projection() -> None:
    gds = FakeGDS()
    engine = CentralityEngine(gds)  # type: ignore[arg-type]

    graph_name = engine.project_disease_neighborhood("MESH:D005909")

    assert graph_name == "adda_disease_mesh_d005909"
    assert len(gds.calls) == 2
    assert "gds.graph.project.cypher" in gds.calls[1][0]
    assert gds.calls[1][1]["disease_id"] == "MESH:D005909"


def test_pagerank_degree_and_betweenness_return_normalized_dataframes() -> None:
    gds = FakeGDS()
    engine = CentralityEngine(gds)  # type: ignore[arg-type]

    pagerank = engine.pagerank("graph")
    degree = engine.degree("graph")
    betweenness = engine.betweenness("graph")

    assert isinstance(pagerank, pd.DataFrame)
    assert pagerank["normalized_score"].tolist() == [1.0]
    assert degree["normalized_score"].tolist() == [1.0, 0.0]
    assert betweenness["normalized_score"].tolist() == [0.0, 1.0]


def test_normalize_scores_handles_empty_and_equal_scores() -> None:
    empty = normalize_scores(pd.DataFrame({"id": [], "score": []}))
    equal = normalize_scores(pd.DataFrame([{"id": "a", "score": 3.0}]))

    assert empty.empty
    assert "normalized_score" in empty.columns
    assert equal["normalized_score"].tolist() == [1.0]
