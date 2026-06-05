from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from adda.molecules.chembl import ACTIVITY_FIELDS, ChEMBLClient


class FakeResource:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.filters: list[dict[str, Any]] = []
        self.only_fields: list[str] | None = None

    def filter(self, **kwargs: Any) -> FakeResource:
        self.filters.append(kwargs)
        return self

    def only(self, fields: Iterable[str]) -> list[dict[str, Any]]:
        self.only_fields = list(fields)
        return self.rows


class FakeChEMBL:
    def __init__(self) -> None:
        self.activity = FakeResource(
            [
                {
                    "activity_id": 1,
                    "assay_chembl_id": "CHEMBL_A1",
                    "assay_type": "B",
                    "canonical_smiles": "CCO",
                    "molecule_chembl_id": "CHEMBL_M1",
                    "pchembl_value": "6.2",
                    "target_chembl_id": "CHEMBL_T1",
                },
                {
                    "assay_type": "B",
                    "molecule_chembl_id": "CHEMBL_TOO_WEAK",
                    "pchembl_value": "4.9",
                    "target_chembl_id": "CHEMBL_T1",
                },
                {
                    "assay_type": "F",
                    "molecule_chembl_id": "CHEMBL_FUNCTIONAL",
                    "pchembl_value": "7.0",
                    "target_chembl_id": "CHEMBL_T1",
                },
            ]
        )
        self.mechanism = FakeResource(
            [
                {
                    "molecule_chembl_id": "CHEMBL_M1",
                    "mechanism_of_action": "EGFR inhibitor",
                    "target_chembl_id": "CHEMBL_T1",
                    "action_type": "INHIBITOR",
                    "direct_interaction": True,
                    "disease_efficacy": True,
                    "max_phase": 4,
                    "source": "ChEMBL",
                }
            ]
        )


def test_actives_for_target_filters_binding_assays_and_min_pchembl() -> None:
    fake = FakeChEMBL()
    client = ChEMBLClient(client=fake)

    actives = client.actives_for_target("CHEMBL_T1", min_pchembl=5.0)

    assert fake.activity.filters[0] == {
        "target_chembl_id": "CHEMBL_T1",
        "pchembl_value__gte": 5.0,
        "assay_type": "B",
    }
    assert fake.activity.only_fields == ACTIVITY_FIELDS
    assert [active.molecule_chembl_id for active in actives] == ["CHEMBL_M1"]
    assert actives[0].pchembl_value == 6.2


def test_mechanism_returns_validated_mechanism_rows() -> None:
    client = ChEMBLClient(client=FakeChEMBL())

    mechanisms = client.mechanism("CHEMBL_M1")

    assert mechanisms[0].mechanism_of_action == "EGFR inhibitor"
    assert mechanisms[0].target_chembl_id == "CHEMBL_T1"
    assert mechanisms[0].raw["action_type"] == "INHIBITOR"
