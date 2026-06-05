"""Batch-load Phase 2 entities and relations into Neo4j via APOC."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from neo4j import GraphDatabase

from adda.extraction.models import Entity, Relation
from adda.kg.schema import (
    DISEASE_GENE_PROVENANCE_QUERY,
    MISSING_PROVENANCE_QUERY,
    NODE_CONSTRAINTS,
    PLUGIN_CHECK_QUERY,
    EdgeProvenance,
    KGEdge,
    KGNode,
    entity_to_node,
    mention_edges,
    publication_node,
    relation_to_edge,
)

APOC_NODE_LOAD_QUERY = """
CALL apoc.periodic.iterate(
  'UNWIND $rows AS row RETURN row',
  'CALL apoc.merge.node([row.label], {id: row.id}, row.props, row.props)
   YIELD node RETURN count(node)',
  {batchSize: $batch_size, params: {rows: $rows}, parallel: false}
)
YIELD batches, total
RETURN batches, total
"""

APOC_RELATION_LOAD_QUERY = """
CALL apoc.periodic.iterate(
  'UNWIND $rows AS row RETURN row',
  'MATCH (source {id: row.source_id})
   WHERE row.source_label IN labels(source)
   MATCH (target {id: row.target_id})
   WHERE row.target_label IN labels(target)
   CALL apoc.merge.relationship(source, row.type, {}, row.props, target, row.props)
   YIELD rel RETURN count(rel)',
  {batchSize: $batch_size, params: {rows: $rows}, parallel: false}
)
YIELD batches, total
RETURN batches, total
"""


class KGLoader:
    """Neo4j APOC batch loader with idempotent node and edge MERGE semantics."""

    def __init__(
        self,
        uri: str,
        auth: tuple[str, str],
        *,
        driver: Any | None = None,
        batch_size: int = 1_000,
    ) -> None:
        self.driver: Any = driver or GraphDatabase.driver(uri, auth=auth)
        self.batch_size = batch_size

    def close(self) -> None:
        """Close the Neo4j driver."""

        close = getattr(self.driver, "close", None)
        if callable(close):
            close()

    def create_constraints(self) -> None:
        """Create unique business-key constraints for every schema node label."""

        for query in NODE_CONSTRAINTS:
            self._execute(query)

    def check_plugins(self) -> dict[str, Any]:
        """Return APOC and GDS plugin versions from Neo4j."""

        records = self._execute(PLUGIN_CHECK_QUERY)
        if not records:
            return {}
        return dict(records[0])

    def merge_nodes(self, entities: Sequence[Entity | KGNode]) -> None:
        """Merge entity and publication nodes idempotently."""

        nodes: list[KGNode] = []
        for item in entities:
            if isinstance(item, KGNode):
                nodes.append(item)
                continue
            node = entity_to_node(item)
            if node:
                nodes.append(node)
            nodes.extend(publication_node(pmid) for pmid in item.source_pmids)
        self._load_nodes(nodes)

    def merge_relations(self, relations: Sequence[Relation | KGEdge]) -> None:
        """Merge schema-valid relations plus Publication-[:MENTIONS] edges."""

        edges: list[KGEdge] = []
        for item in relations:
            if isinstance(item, KGEdge):
                edges.append(item)
                continue
            edge = relation_to_edge(item)
            if edge:
                edges.append(edge)
            edges.extend(mention_edges(item.subject))
            edges.extend(mention_edges(item.object))
        self._load_edges(edges)

    def attach_provenance(self, edge: KGEdge, provenance: EdgeProvenance) -> None:
        """Update provenance for one already-mapped edge."""

        self._load_edges([edge.model_copy(update={"provenance": provenance})])

    def count_edges_missing_provenance(self) -> int:
        """Return how many relationships lack required provenance properties."""

        records = self._execute(MISSING_PROVENANCE_QUERY)
        if not records:
            return 0
        value = dict(records[0]).get("missing_count", 0)
        return int(value) if isinstance(value, int) else 0

    def disease_gene_edges(self) -> list[dict[str, Any]]:
        """Run the canonical disease-gene provenance-bearing query."""

        return [dict(record) for record in self._execute(DISEASE_GENE_PROVENANCE_QUERY)]

    def _load_nodes(self, nodes: Sequence[KGNode]) -> None:
        rows = [
            node.to_loader_row()
            for node in {
                (node.label, node.id): node for node in nodes if node.id and node.name
            }.values()
        ]
        if rows:
            self._execute(
                APOC_NODE_LOAD_QUERY,
                rows=rows,
                batch_size=self.batch_size,
            )

    def _load_edges(self, edges: Sequence[KGEdge]) -> None:
        deduped = {
            (
                edge.source_label,
                edge.source_id,
                edge.relation_type,
                edge.target_label,
                edge.target_id,
            ): edge
            for edge in edges
            if edge.source_id and edge.target_id
        }
        rows = [edge.to_loader_row() for edge in deduped.values()]
        if rows:
            self._execute(
                APOC_RELATION_LOAD_QUERY,
                rows=rows,
                batch_size=self.batch_size,
            )

    def _execute(self, query: str, **parameters: Any) -> list[Any]:
        result = self.driver.execute_query(query, parameters_=parameters)
        records = result[0] if isinstance(result, tuple) else result
        if records is None:
            return []
        return list(records)
