from __future__ import annotations

import math
from pathlib import Path

from adda.molecules.triage import SCOPE_LABEL, MoleculeTriage, TriageResult

ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
SALICYLIC_ACID = "O=C(O)c1ccccc1O"
CAFFEINE = "Cn1cnc2c1c(=O)n(C)c(=O)n2C"


def test_rdkit_properties_lipinski_veber_and_qed_for_known_molecule() -> None:
    triage = MoleculeTriage()

    properties = triage.properties(ASPIRIN)
    rules = triage.rules(properties)

    assert math.isclose(properties.molecular_weight, 180.159, rel_tol=0.001)
    assert math.isclose(properties.logp, 1.3101, rel_tol=0.001)
    assert properties.hbd == 1
    assert properties.hba == 3
    assert math.isclose(properties.tpsa, 63.6, rel_tol=0.001)
    assert properties.rotatable_bonds == 2
    assert 0.5 < properties.qed < 0.6
    assert rules.passes_lipinski is True
    assert rules.lipinski_violations == 0
    assert rules.passes_veber is True


def test_brenk_pains_alerts_are_reported() -> None:
    alerts = MoleculeTriage().structural_alerts(ASPIRIN)

    assert "phenol_ester" in alerts


def test_fingerprint_similarity_and_murcko_scaffold() -> None:
    triage = MoleculeTriage()

    assert triage.tanimoto_similarity(ASPIRIN, ASPIRIN) == 1.0
    assert triage.tanimoto_similarity(ASPIRIN, CAFFEINE) < 1.0
    assert triage.murcko_scaffold(ASPIRIN) == "c1ccccc1"


def test_triage_result_labels_known_actives_scope() -> None:
    result = MoleculeTriage().triage_molecule(
        {
            "molecule_chembl_id": "CHEMBL25",
            "canonical_smiles": ASPIRIN,
            "pchembl_value": 6.7,
            "assay_chembl_id": "CHEMBL_A1",
        }
    )

    assert isinstance(result, TriageResult)
    assert result.molecule_chembl_id == "CHEMBL25"
    assert result.pchembl_value == 6.7
    assert result.source == "chembl_known_active"
    assert result.scope_label == SCOPE_LABEL
    assert "known actives" in result.scope_label
    assert "not de novo" in result.scope_label
    assert "not docking" in result.scope_label
    assert result.metadata["assay_chembl_id"] == "CHEMBL_A1"


def test_scaffold_clustering_groups_known_actives() -> None:
    clusters = MoleculeTriage().cluster_by_scaffold(
        [
            {"molecule_chembl_id": "ASP", "canonical_smiles": ASPIRIN},
            {"molecule_chembl_id": "SAL", "canonical_smiles": SALICYLIC_ACID},
            {"molecule_chembl_id": "CAF", "canonical_smiles": CAFFEINE},
        ]
    )

    by_scaffold = {cluster.scaffold: cluster for cluster in clusters}

    assert set(by_scaffold["c1ccccc1"].molecule_chembl_ids) == {"ASP", "SAL"}
    assert "CAF" in {
        molecule_id
        for cluster in clusters
        for molecule_id in cluster.molecule_chembl_ids
    }


def test_drugbank_is_not_bundled_as_dependency_or_data() -> None:
    pyproject = Path("pyproject.toml").read_text()
    assert "drugbank" not in pyproject.lower()

    data_roots = [Path("data"), Path("src/adda/data"), Path("tests/fixtures")]
    bundled_paths = [
        path
        for root in data_roots
        if root.exists()
        for path in root.rglob("*")
        if "drugbank" in path.name.lower()
    ]
    assert bundled_paths == []
