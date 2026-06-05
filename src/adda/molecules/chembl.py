"""ChEMBL known-active lookup for target molecule triage.

This client intentionally uses public ChEMBL records only. DrugBank is not
bundled or queried because it has different licensing constraints.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from importlib import import_module
from typing import Any, cast

from pydantic import BaseModel, Field

ACTIVITY_FIELDS = [
    "activity_id",
    "assay_chembl_id",
    "assay_type",
    "canonical_smiles",
    "molecule_chembl_id",
    "pchembl_value",
    "standard_type",
    "standard_units",
    "standard_value",
    "target_chembl_id",
]

MECHANISM_FIELDS = [
    "action_type",
    "direct_interaction",
    "disease_efficacy",
    "max_phase",
    "mechanism_of_action",
    "molecule_chembl_id",
    "source",
    "target_chembl_id",
]


class ChEMBLActivity(BaseModel):
    """Known bioactive ChEMBL molecule-target assay row."""

    molecule_chembl_id: str
    target_chembl_id: str
    assay_chembl_id: str | None = None
    assay_type: str
    pchembl_value: float = Field(ge=0.0)
    canonical_smiles: str | None = None
    standard_type: str | None = None
    standard_value: str | float | None = None
    standard_units: str | None = None
    activity_id: int | str | None = None


class ChEMBLMechanism(BaseModel):
    """Mechanism-of-action row from ChEMBL."""

    molecule_chembl_id: str
    mechanism_of_action: str | None = None
    target_chembl_id: str | None = None
    action_type: str | None = None
    direct_interaction: bool | None = None
    disease_efficacy: bool | None = None
    max_phase: int | None = None
    source: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


def _row_to_dict(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Convert ChEMBL client rows and fake test rows into plain dictionaries."""

    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "items"):
        return dict(row.items())
    if hasattr(row, "__dict__"):
        return {
            str(key): value
            for key, value in vars(row).items()
            if not str(key).startswith("_")
        }
    raise TypeError(f"unsupported ChEMBL row type: {type(row)!r}")


def _iter_rows(rows: Iterable[Mapping[str, Any] | Any]) -> list[dict[str, Any]]:
    return [_row_to_dict(row) for row in rows]


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_default_client() -> Any:
    module = cast(Any, import_module("chembl_webresource_client.new_client"))
    return module.new_client


class ChEMBLClient:
    """Thin ChEMBL Web Resource Client wrapper for known actives."""

    def __init__(self, client: Any | None = None) -> None:
        self.client: Any = client if client is not None else _load_default_client()

    def actives_for_target(
        self,
        chembl_target_id: str,
        *,
        min_pchembl: float = 5.0,
    ) -> list[ChEMBLActivity]:
        """Return known biochemical actives for a ChEMBL target.

        The ChEMBL query is deliberately scoped to pChEMBL >= ``min_pchembl``
        and binding assays (``assay_type='B'``). Returned rows are validated
        again locally so test doubles and client quirks cannot loosen the
        activity threshold.
        """

        rows = self.client.activity.filter(
            target_chembl_id=chembl_target_id,
            pchembl_value__gte=min_pchembl,
            assay_type="B",
        ).only(ACTIVITY_FIELDS)
        activities: list[ChEMBLActivity] = []
        for row in _iter_rows(rows):
            pchembl = _float_or_none(row.get("pchembl_value"))
            if pchembl is None or pchembl < min_pchembl:
                continue
            if row.get("assay_type") != "B":
                continue
            molecule_id = row.get("molecule_chembl_id")
            target_id = row.get("target_chembl_id") or chembl_target_id
            if not isinstance(molecule_id, str) or not isinstance(target_id, str):
                continue
            activities.append(
                ChEMBLActivity(
                    molecule_chembl_id=molecule_id,
                    target_chembl_id=target_id,
                    assay_chembl_id=row.get("assay_chembl_id")
                    if isinstance(row.get("assay_chembl_id"), str)
                    else None,
                    assay_type="B",
                    pchembl_value=pchembl,
                    canonical_smiles=row.get("canonical_smiles")
                    if isinstance(row.get("canonical_smiles"), str)
                    else None,
                    standard_type=row.get("standard_type")
                    if isinstance(row.get("standard_type"), str)
                    else None,
                    standard_value=row.get("standard_value"),
                    standard_units=row.get("standard_units")
                    if isinstance(row.get("standard_units"), str)
                    else None,
                    activity_id=row.get("activity_id")
                    if isinstance(row.get("activity_id"), (int, str))
                    else None,
                )
            )
        return activities

    def mechanism(self, molecule_chembl_id: str) -> list[ChEMBLMechanism]:
        """Return ChEMBL mechanism rows for a molecule."""

        rows = self.client.mechanism.filter(molecule_chembl_id=molecule_chembl_id).only(
            MECHANISM_FIELDS
        )
        mechanisms: list[ChEMBLMechanism] = []
        for row in _iter_rows(rows):
            mechanisms.append(
                ChEMBLMechanism(
                    molecule_chembl_id=molecule_chembl_id,
                    mechanism_of_action=row.get("mechanism_of_action")
                    if isinstance(row.get("mechanism_of_action"), str)
                    else None,
                    target_chembl_id=row.get("target_chembl_id")
                    if isinstance(row.get("target_chembl_id"), str)
                    else None,
                    action_type=row.get("action_type")
                    if isinstance(row.get("action_type"), str)
                    else None,
                    direct_interaction=row.get("direct_interaction")
                    if isinstance(row.get("direct_interaction"), bool)
                    else None,
                    disease_efficacy=row.get("disease_efficacy")
                    if isinstance(row.get("disease_efficacy"), bool)
                    else None,
                    max_phase=row.get("max_phase")
                    if isinstance(row.get("max_phase"), int)
                    else None,
                    source=row.get("source")
                    if isinstance(row.get("source"), str)
                    else None,
                    raw=row,
                )
            )
        return mechanisms
