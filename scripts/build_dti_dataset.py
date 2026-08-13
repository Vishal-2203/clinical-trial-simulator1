"""
ChEMBL 37 DTI Dataset Builder
Extracts drug-target interaction triples for training the Novel Pathogen Predictor.

Output: data/training/chembl_dti_training.parquet
  Columns: smiles | protein_sequence | ic50_nM | pchembl | target_name | organism | assay_type
"""

import sqlite3
import json
import os
import sys
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "chembl_37", "chembl_37_sqlite", "chembl_37.db")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "training", "chembl_dti_training.parquet")

def build_dti_dataset(limit: int = 500_000) -> pd.DataFrame:
    """
    Queries ChEMBL for high-quality drug-protein-IC50 triples.
    Filters:
      - standard_type in (IC50, Ki, Kd, EC50)
      - standard_units = nM
      - standard_relation = '='
      - pchembl_value is not null (quality filter, pChEMBL >= 5 = 10 uM cutoff)
      - protein sequence available from target_components
    """
    print(f"Connecting to ChEMBL: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)

    print("Querying drug-target-IC50 triples (this may take 2-5 minutes)...")
    query = """
    SELECT
        cs.canonical_smiles            AS smiles,
        md.pref_name                   AS drug_name,
        md.chembl_id                   AS drug_chembl_id,
        act.standard_value             AS ic50_nM,
        act.standard_type              AS assay_type,
        act.pchembl_value              AS pchembl,
        td.pref_name                   AS target_name,
        td.target_type                 AS target_type,
        td.chembl_id                   AS target_chembl_id,
        td.organism                    AS organism,
        cs2.sequence                   AS protein_sequence
    FROM activities act
    JOIN molecule_dictionary md ON act.molregno = md.molregno
    JOIN compound_structures cs ON md.molregno = cs.molregno
    JOIN assays ass ON act.assay_id = ass.assay_id
    JOIN target_dictionary td ON ass.tid = td.tid
    LEFT JOIN target_components tc ON td.tid = tc.tid
    LEFT JOIN component_sequences cs2 ON tc.component_id = cs2.component_id
    WHERE act.standard_type IN ('IC50', 'Ki', 'Kd', 'EC50')
      AND act.standard_units = 'nM'
      AND act.standard_relation = '='
      AND act.pchembl_value IS NOT NULL
      AND act.pchembl_value >= 4.0
      AND td.target_type = 'SINGLE PROTEIN'
      AND cs.canonical_smiles IS NOT NULL
      AND cs2.sequence IS NOT NULL
    ORDER BY act.pchembl_value DESC
    LIMIT ?
    """

    df = pd.read_sql_query(query, conn, params=(limit,))
    conn.close()

    print(f"Retrieved {len(df)} drug-target pairs")
    print(f"  Unique drugs: {df['drug_chembl_id'].nunique()}")
    print(f"  Unique targets: {df['target_chembl_id'].nunique()}")
    print(f"  pChEMBL range: {df['pchembl'].min():.1f} - {df['pchembl'].max():.1f}")

    # Clean up
    df = df.dropna(subset=['smiles', 'protein_sequence', 'ic50_nM'])
    df = df[df['protein_sequence'].str.len().between(20, 2000)]  # Reasonable protein lengths
    df = df[df['smiles'].str.len().between(5, 500)]              # Reasonable SMILES lengths
    df['ic50_nM'] = pd.to_numeric(df['ic50_nM'], errors='coerce')
    df = df.dropna(subset=['ic50_nM'])
    df = df[df['ic50_nM'] > 0]

    # Normalize label: pIC50 = -log10(IC50 in Molar) → already in pchembl column
    # Also keep a 0-1 normalized efficacy for model training
    # pChEMBL 4 = 10uM (low), 9+ = 1nM (very potent)
    df['efficacy_score'] = (df['pchembl'] - 4.0) / 6.0  # 0 at 10uM, 1 at 10pM
    df['efficacy_score'] = df['efficacy_score'].clip(0, 1)

    print(f"\nFinal dataset size: {len(df)} high-quality triples")
    return df


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    df = build_dti_dataset(limit=600_000)
    df.to_parquet(OUTPUT_PATH, index=False)
    print(f"\nSaved to: {OUTPUT_PATH}")
    print(df.head(3).to_string())


if __name__ == "__main__":
    main()
