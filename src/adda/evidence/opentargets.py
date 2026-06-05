"""Open Targets Platform GraphQL client.

Open Targets is the target-disease evidence grounding source for Phase 4.
The GraphQL API returns association scores, datatype scores, known-drug signal,
and target tractability buckets.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import BaseModel, Field

from adda.cache import cached

DATATYPE_ALIASES: dict[str, str] = {
    "geneticAssociations": "genetic_association",
    "genetic_association": "genetic_association",
    "somaticMutations": "somatic_mutation",
    "somatic_mutation": "somatic_mutation",
    "knownDrugs": "known_drug",
    "known_drug": "known_drug",
    "affectedPathways": "affected_pathway",
    "affected_pathway": "affected_pathway",
    "literature": "literature",
    "rnaExpression": "rna_expression",
    "rna_expression": "rna_expression",
    "animalModels": "animal_model",
    "animal_model": "animal_model",
}


class TractabilityBucket(BaseModel):
    """One Open Targets tractability bucket."""

    label: str
    modality: str | None = None
    value: bool | float | str | None = None


class OpenTargetsAssociation(BaseModel):
    """Normalized target-disease association from Open Targets."""

    disease_id: str
    target_id: str
    target_symbol: str | None = None
    overall_score: float = Field(ge=0.0, le=1.0)
    datatype_scores: dict[str, float] = Field(default_factory=dict)
    tractability: list[TractabilityBucket] = Field(default_factory=list)
    known_drug: bool = False

    def model_dump_for_breakdown(self) -> dict[str, Any]:
        """Return a compact explainability payload."""

        return {
            "disease_id": self.disease_id,
            "target_id": self.target_id,
            "target_symbol": self.target_symbol,
            "overall_score": self.overall_score,
            "datatype_scores": self.datatype_scores,
            "known_drug": self.known_drug,
            "tractability": [item.model_dump() for item in self.tractability],
        }


ASSOCIATIONS_QUERY = """
query diseaseAssociations($efoId: String!, $index: Int!, $size: Int!) {
  disease(efoId: $efoId) {
    id
    associatedTargets(page: {index: $index, size: $size}) {
      count
      rows {
        score
        target {
          id
          approvedSymbol
          tractability {
            label
            modality
            value
          }
        }
        datatypeScores {
          id
          score
        }
      }
    }
  }
}
"""

TRACTABILITY_QUERY = """
query targetTractability($ensemblId: String!) {
  target(ensemblId: $ensemblId) {
    id
    approvedSymbol
    tractability {
      label
      modality
      value
    }
  }
}
"""


class OpenTargetsClient:
    """Async Open Targets GraphQL client."""

    GRAPHQL = "https://api.platform.opentargets.org/api/v4/graphql"

    def __init__(
        self,
        *,
        endpoint: str = GRAPHQL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def aclose(self) -> None:
        """Close the owned HTTP client."""

        if self._owns_client:
            await self._client.aclose()

    @cached
    async def associations(
        self,
        disease_efo: str,
        *,
        size: int = 200,
    ) -> list[OpenTargetsAssociation]:
        """Return target associations for one disease or phenotype EFO ID."""

        data = await self._graphql(
            ASSOCIATIONS_QUERY,
            {"efoId": disease_efo, "index": 0, "size": size},
        )
        disease = _as_mapping(data.get("disease"))
        associated_targets = _as_mapping(disease.get("associatedTargets"))
        rows = associated_targets.get("rows")
        if not isinstance(rows, list):
            return []
        return [
            association
            for row in rows
            if isinstance(row, Mapping)
            if (
                association := parse_association_row(
                    row,
                    disease_id=disease_efo,
                )
            )
            is not None
        ]

    @cached
    async def tractability(self, target_ensembl: str) -> dict[str, Any]:
        """Return parsed target tractability buckets."""

        data = await self._graphql(
            TRACTABILITY_QUERY,
            {"ensemblId": target_ensembl},
        )
        target = _as_mapping(data.get("target"))
        return {
            "target_id": target.get("id")
            if isinstance(target.get("id"), str)
            else None,
            "target_symbol": target.get("approvedSymbol")
            if isinstance(target.get("approvedSymbol"), str)
            else None,
            "tractability": [
                bucket.model_dump()
                for bucket in parse_tractability(target.get("tractability"))
            ],
        }

    async def _graphql(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._client.post(
            self.endpoint,
            json={"query": query, "variables": variables},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Open Targets returned non-object JSON")
        errors = payload.get("errors")
        if errors:
            raise ValueError(f"Open Targets GraphQL errors: {errors}")
        data = payload.get("data")
        if not isinstance(data, dict):
            return {}
        return data


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _score(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, min(float(value), 1.0))
    return None


def normalize_datatype_id(datatype_id: str) -> str:
    """Normalize Open Targets datatype identifiers."""

    return DATATYPE_ALIASES.get(datatype_id, datatype_id)


def parse_datatype_scores(value: Any) -> dict[str, float]:
    """Parse per-datatype scores from Open Targets rows."""

    if isinstance(value, Mapping):
        return {
            normalize_datatype_id(str(key)): score
            for key, raw_score in value.items()
            if (score := _score(raw_score)) is not None
        }
    if not isinstance(value, list):
        return {}
    parsed: dict[str, float] = {}
    for item in value:
        mapping = _as_mapping(item)
        raw_id = mapping.get("id") or mapping.get("datatypeId") or mapping.get("type")
        score = _score(mapping.get("score"))
        if isinstance(raw_id, str) and score is not None:
            parsed[normalize_datatype_id(raw_id)] = score
    return parsed


def parse_tractability(value: Any) -> list[TractabilityBucket]:
    """Parse tractability records from target payloads."""

    if not isinstance(value, list):
        return []
    buckets: list[TractabilityBucket] = []
    for item in value:
        mapping = _as_mapping(item)
        label = mapping.get("label")
        if not isinstance(label, str):
            continue
        modality = mapping.get("modality")
        buckets.append(
            TractabilityBucket(
                label=label,
                modality=modality if isinstance(modality, str) else None,
                value=mapping.get("value"),
            )
        )
    return buckets


def parse_association_row(
    row: Mapping[str, Any],
    *,
    disease_id: str,
) -> OpenTargetsAssociation | None:
    """Normalize one associatedTargets row."""

    target = _as_mapping(row.get("target"))
    target_id = target.get("id")
    if not isinstance(target_id, str):
        return None
    overall_score = _score(row.get("score")) or 0.0
    target_symbol = target.get("approvedSymbol")
    datatype_scores = parse_datatype_scores(row.get("datatypeScores"))
    known_drug = datatype_scores.get("known_drug", 0.0) > 0.0
    return OpenTargetsAssociation(
        disease_id=disease_id,
        target_id=target_id,
        target_symbol=target_symbol if isinstance(target_symbol, str) else None,
        overall_score=overall_score,
        datatype_scores=datatype_scores,
        tractability=parse_tractability(target.get("tractability")),
        known_drug=known_drug,
    )
