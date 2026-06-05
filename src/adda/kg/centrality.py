"""Graph Data Science centrality for target ranking."""

from __future__ import annotations

import re

import pandas as pd
from graphdatascience import GraphDataScience

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def normalize_scores(
    frame: pd.DataFrame,
    *,
    score_column: str = "score",
) -> pd.DataFrame:
    """Add a 0-1 normalized score column to a centrality DataFrame."""

    if frame.empty:
        result = frame.copy()
        result["normalized_score"] = []
        return result
    result = frame.copy()
    min_score = float(result[score_column].min())
    max_score = float(result[score_column].max())
    if max_score == min_score:
        result["normalized_score"] = 1.0
        return result
    result["normalized_score"] = (result[score_column].astype(float) - min_score) / (
        max_score - min_score
    )
    return result


class CentralityEngine:
    """Run GDS centrality algorithms over disease neighborhood projections."""

    def __init__(self, gds: GraphDataScience) -> None:
        self.gds = gds

    def project_disease_neighborhood(self, disease_id: str) -> str:
        """Project a disease ego network and return the graph name."""

        graph_name = self._graph_name(disease_id)
        self.gds.run_cypher(
            """
            MATCH (d:Disease {id: $disease_id})
            OPTIONAL MATCH path = (d)-[*1..2]-(n)
            WITH d, collect(DISTINCT n) AS neighbors
            WITH [d] + neighbors AS nodes
            UNWIND nodes AS node
            WITH collect(DISTINCT id(node)) AS node_ids
            CALL gds.graph.drop($graph_name, false) YIELD graphName
            RETURN graphName
            """,
            params={"disease_id": disease_id, "graph_name": graph_name},
        )
        self.gds.run_cypher(
            """
            MATCH (d:Disease {id: $disease_id})
            OPTIONAL MATCH path = (d)-[*1..2]-(n)
            WITH d, collect(DISTINCT n) AS neighbors
            WITH [d] + neighbors AS nodes
            UNWIND nodes AS node
            WITH collect(DISTINCT id(node)) AS node_ids
            CALL gds.graph.project.cypher(
              $graph_name,
              'MATCH (n)
               WHERE id(n) IN $node_ids
               RETURN id(n) AS id, labels(n) AS labels',
              'MATCH (n)-[r]-(m)
               WHERE id(n) IN $node_ids AND id(m) IN $node_ids
               RETURN id(n) AS source, id(m) AS target',
              {parameters: {node_ids: node_ids}}
            )
            YIELD graphName
            RETURN graphName
            """,
            params={"disease_id": disease_id, "graph_name": graph_name},
        )
        return graph_name

    def pagerank(self, graph_name: str) -> pd.DataFrame:
        """Run PageRank and return normalized scores."""

        return self._run_algorithm(
            """
            CALL gds.pageRank.stream($graph_name)
            YIELD nodeId, score
            RETURN gds.util.asNode(nodeId).id AS id,
                   labels(gds.util.asNode(nodeId)) AS labels,
                   score AS score
            ORDER BY score DESC
            """,
            graph_name,
        )

    def degree(self, graph_name: str) -> pd.DataFrame:
        """Run degree centrality and return normalized scores."""

        return self._run_algorithm(
            """
            CALL gds.degree.stream($graph_name)
            YIELD nodeId, score
            RETURN gds.util.asNode(nodeId).id AS id,
                   labels(gds.util.asNode(nodeId)) AS labels,
                   score AS score
            ORDER BY score DESC
            """,
            graph_name,
        )

    def betweenness(self, graph_name: str) -> pd.DataFrame:
        """Run betweenness centrality and return normalized scores."""

        return self._run_algorithm(
            """
            CALL gds.betweenness.stream($graph_name)
            YIELD nodeId, score
            RETURN gds.util.asNode(nodeId).id AS id,
                   labels(gds.util.asNode(nodeId)) AS labels,
                   score AS score
            ORDER BY score DESC
            """,
            graph_name,
        )

    def _run_algorithm(self, query: str, graph_name: str) -> pd.DataFrame:
        frame = self.gds.run_cypher(query, params={"graph_name": graph_name})
        return normalize_scores(frame)

    def _graph_name(self, disease_id: str) -> str:
        normalized = _SAFE_NAME_RE.sub("_", disease_id).strip("_").lower()
        return f"adda_disease_{normalized or 'unknown'}"
