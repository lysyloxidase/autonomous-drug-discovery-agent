"""RDKit triage for known active ChEMBL molecules.

This module labels and prioritizes known actives. It does not perform de novo
generation, virtual screening, docking, or clinical recommendation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, cast

from pydantic import BaseModel, Field
from rdkit import Chem, DataStructs
from rdkit.Chem import (
    QED,
    Crippen,
    Descriptors,
    rdFingerprintGenerator,
    rdMolDescriptors,
)
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams
from rdkit.Chem.Scaffolds import MurckoScaffold

SCOPE_LABEL = "known actives only; not de novo design; not docking"


class MoleculeProperties(BaseModel):
    """Computed RDKit molecule properties."""

    canonical_smiles: str
    molecular_weight: float
    mw: float
    logp: float
    hbd: int
    hba: int
    tpsa: float
    rotatable_bonds: int
    qed: float


class RuleOfFiveResult(BaseModel):
    """Lipinski and Veber rule checks."""

    lipinski_mw: bool
    lipinski_logp: bool
    lipinski_hbd: bool
    lipinski_hba: bool
    lipinski_violations: int
    passes_lipinski: bool
    veber_rotatable_bonds: bool
    veber_tpsa: bool
    passes_veber: bool


class TriageResult(BaseModel):
    """Known active molecule triage output."""

    molecule_chembl_id: str | None = None
    canonical_smiles: str
    properties: MoleculeProperties
    rules: RuleOfFiveResult
    structural_alerts: list[str]
    murcko_scaffold: str
    scope_label: str = SCOPE_LABEL
    source: str = "chembl_known_active"
    pchembl_value: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScaffoldCluster(BaseModel):
    """Bemis-Murcko scaffold cluster for known actives."""

    scaffold: str
    molecule_chembl_ids: list[str]
    molecules: list[TriageResult]


def _build_alert_catalog() -> FilterCatalog:
    params = FilterCatalogParams()
    params.AddCatalog(FilterCatalogParams.FilterCatalogs.BRENK)
    params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS_A)
    params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS_B)
    params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS_C)
    return FilterCatalog(params)


def _mol_from_smiles(smiles: str) -> Chem.Mol:
    mol: Any = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"invalid SMILES: {smiles}")
    return cast(Chem.Mol, mol)


def _smiles_from_record(record: Mapping[str, Any]) -> str:
    for key in ("canonical_smiles", "smiles"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise ValueError("molecule record must include canonical_smiles or smiles")


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class MoleculeTriage:
    """RDKit-based triage and clustering for known active molecules."""

    def __init__(self, *, fingerprint_size: int = 2048) -> None:
        self.alert_catalog = _build_alert_catalog()
        self.fingerprint_generator = rdFingerprintGenerator.GetMorganGenerator(
            radius=2,
            fpSize=fingerprint_size,
        )

    def properties(self, smiles: str) -> MoleculeProperties:
        """Compute core drug-likeness descriptors."""

        mol = _mol_from_smiles(smiles)
        canonical = Chem.MolToSmiles(mol)
        descriptors = cast(Any, Descriptors)
        crippen = cast(Any, Crippen)
        molecular_weight = round(float(descriptors.MolWt(mol)), 6)
        return MoleculeProperties(
            canonical_smiles=canonical,
            molecular_weight=molecular_weight,
            mw=molecular_weight,
            logp=round(float(crippen.MolLogP(mol)), 6),
            hbd=int(rdMolDescriptors.CalcNumHBD(mol)),
            hba=int(rdMolDescriptors.CalcNumHBA(mol)),
            tpsa=round(float(rdMolDescriptors.CalcTPSA(mol)), 6),
            rotatable_bonds=int(rdMolDescriptors.CalcNumRotatableBonds(mol)),
            qed=round(float(QED.qed(mol)), 6),
        )

    def rules(self, properties: MoleculeProperties) -> RuleOfFiveResult:
        """Evaluate Lipinski Ro5 and Veber filters."""

        lipinski_checks = {
            "lipinski_mw": properties.molecular_weight <= 500,
            "lipinski_logp": properties.logp <= 5,
            "lipinski_hbd": properties.hbd <= 5,
            "lipinski_hba": properties.hba <= 10,
        }
        violations = sum(not passed for passed in lipinski_checks.values())
        veber_rotatable = properties.rotatable_bonds <= 10
        veber_tpsa = properties.tpsa <= 140
        return RuleOfFiveResult(
            **lipinski_checks,
            lipinski_violations=violations,
            passes_lipinski=violations == 0,
            veber_rotatable_bonds=veber_rotatable,
            veber_tpsa=veber_tpsa,
            passes_veber=veber_rotatable and veber_tpsa,
        )

    def structural_alerts(self, smiles: str) -> list[str]:
        """Return Brenk and PAINS alert descriptions."""

        mol = _mol_from_smiles(smiles)
        matches = self.alert_catalog.GetMatches(mol)
        return sorted({str(match.GetDescription()) for match in matches})

    def fingerprint(self, smiles: str) -> Any:
        """Return an RDKit Morgan fingerprint bit vector."""

        return self.fingerprint_generator.GetFingerprint(_mol_from_smiles(smiles))

    def tanimoto_similarity(self, smiles_a: str, smiles_b: str) -> float:
        """Compute Morgan-fingerprint Tanimoto similarity."""

        return round(
            float(
                DataStructs.TanimotoSimilarity(
                    self.fingerprint(smiles_a),
                    self.fingerprint(smiles_b),
                )
            ),
            6,
        )

    def murcko_scaffold(self, smiles: str) -> str:
        """Return the Bemis-Murcko scaffold SMILES."""

        mol = _mol_from_smiles(smiles)
        scaffold = MurckoScaffold.GetScaffoldForMol(mol)
        return Chem.MolToSmiles(scaffold)

    def triage_molecule(self, record: Mapping[str, Any]) -> TriageResult:
        """Compute known-active molecule triage output for one ChEMBL row."""

        smiles = _smiles_from_record(record)
        properties = self.properties(smiles)
        molecule_id = record.get("molecule_chembl_id")
        pchembl = _float_or_none(record.get("pchembl_value"))
        return TriageResult(
            molecule_chembl_id=molecule_id if isinstance(molecule_id, str) else None,
            canonical_smiles=properties.canonical_smiles,
            properties=properties,
            rules=self.rules(properties),
            structural_alerts=self.structural_alerts(smiles),
            murcko_scaffold=self.murcko_scaffold(smiles),
            pchembl_value=pchembl,
            metadata={
                key: value
                for key, value in record.items()
                if key not in {"canonical_smiles", "smiles"}
            },
        )

    def triage_actives(
        self,
        records: Sequence[Mapping[str, Any]],
    ) -> list[TriageResult]:
        """Triage known active molecules and sort by pChEMBL/QED."""

        results = [self.triage_molecule(record) for record in records]
        return sorted(
            results,
            key=lambda item: (
                item.pchembl_value if item.pchembl_value is not None else -1.0,
                item.properties.qed,
                item.molecule_chembl_id or "",
            ),
            reverse=True,
        )

    def cluster_by_scaffold(
        self,
        records: Sequence[Mapping[str, Any] | TriageResult],
    ) -> list[ScaffoldCluster]:
        """Cluster known actives by Bemis-Murcko scaffold."""

        grouped: dict[str, list[TriageResult]] = defaultdict(list)
        for record in records:
            result = (
                record
                if isinstance(record, TriageResult)
                else self.triage_molecule(record)
            )
            grouped[result.murcko_scaffold].append(result)
        return [
            ScaffoldCluster(
                scaffold=scaffold,
                molecule_chembl_ids=[
                    molecule.molecule_chembl_id
                    for molecule in molecules
                    if molecule.molecule_chembl_id
                ],
                molecules=molecules,
            )
            for scaffold, molecules in sorted(
                grouped.items(),
                key=lambda item: (item[0], len(item[1])),
            )
        ]
