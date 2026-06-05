# Target Ranking And Molecule Triage

Phase 5 ranks target candidates with a transparent weighted score. Inputs are
kept visible in the output:

- `centrality`
- `ot_association`
- `druggability`
- `genetic_evidence`
- `novelty`
- `safety_penalty`

`TargetRanker` accepts user-adjustable weights and returns sorted `TargetScore`
records with a `component_breakdown` containing raw and weighted components.
Known-target benchmark helpers compare top-k recovery against reference sources
such as Open Targets, Pharos/TCRD, and DGIdb.

The molecule layer uses ChEMBL and RDKit only for known actives. ChEMBL activity
queries filter to binding assays (`assay_type="B"`) with `pchembl_value >= 5`.
RDKit triage computes molecular weight, logP, HBD/HBA, TPSA, rotatable bonds,
Lipinski Ro5, Veber, QED, Brenk/PAINS structural alerts, Morgan-fingerprint
Tanimoto similarity, and Bemis-Murcko scaffold clusters.

Every molecule triage result carries the scope label:
`known actives only; not de novo design; not docking`.

DrugBank is not bundled or queried by this open implementation.
