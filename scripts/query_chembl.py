"""
ChEMBL Database Query Script
Extracts real pharmacological parameters for:
  - Type 2 Diabetes (Metformin, Semaglutide/GLP-1 agonists)
  - Hypertension (Lisinopril, Amlodipine)
  - NSCLC (Osimertinib)
  - Dengue (Antiviral compounds)

Outputs a JSON file to data/snapshots/chembl_drug_params.json
that the simulator can load to calibrate its PK/PD models.
"""

import sqlite3
import json
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "chembl_37", "chembl_37_sqlite", "chembl_37.db")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "snapshots", "chembl_drug_params.json")

TARGET_DRUGS = {
    "metformin": {
        "disease": "type2_diabetes",
        "component": "a",
        "chembl_name": "METFORMIN",
        "description": "Biguanide - AMPK activation, lowers hepatic glucose output"
    },
    "semaglutide": {
        "disease": "type2_diabetes",
        "component": "b",
        "chembl_name": "SEMAGLUTIDE",
        "description": "GLP-1 Receptor Agonist - stimulates insulin secretion"
    },
    "lisinopril": {
        "disease": "hypertension",
        "component": "a",
        "chembl_name": "LISINOPRIL",
        "description": "ACE Inhibitor - blocks RAAS pathway to lower blood pressure"
    },
    "amlodipine": {
        "disease": "hypertension",
        "component": "b",
        "chembl_name": "AMLODIPINE",
        "description": "L-type Calcium Channel Blocker - relaxes arterial smooth muscle"
    },
    "osimertinib": {
        "disease": "nsclc",
        "component": "a",
        "chembl_name": "OSIMERTINIB",
        "description": "EGFR Tyrosine Kinase Inhibitor - targets mutant EGFR T790M in NSCLC"
    },
    "tecovirimat": {
        "disease": "dengue",
        "component": "b",
        "chembl_name": "TECOVIRIMAT",
        "description": "Viral envelope protein inhibitor - blocks orthopoxvirus/dengue viral egress"
    },
}

def get_drug_info(conn, drug_name: str) -> dict:
    """Pull IC50/EC50 binding data, molecular weight, and AlogP for a drug."""
    cursor = conn.cursor()

    # Step 1: Find the compound by preferred name
    cursor.execute("""
        SELECT md.chembl_id, md.pref_name, cp.mw_freebase, cp.alogp, cp.psa, cp.hba, cp.hbd
        FROM molecule_dictionary md
        LEFT JOIN compound_properties cp ON md.molregno = cp.molregno
        WHERE UPPER(md.pref_name) = ?
        LIMIT 1
    """, (drug_name.upper(),))
    row = cursor.fetchone()

    if not row:
        # Fuzzy fallback search by synonyms
        cursor.execute("""
            SELECT md.chembl_id, md.pref_name, cp.mw_freebase, cp.alogp, cp.psa, cp.hba, cp.hbd
            FROM molecule_dictionary md
            LEFT JOIN compound_properties cp ON md.molregno = cp.molregno
            JOIN molecule_synonyms ms ON md.molregno = ms.molregno
            WHERE UPPER(ms.synonyms) LIKE ?
            LIMIT 1
        """, (f"%{drug_name.upper()}%",))
        row = cursor.fetchone()

    if not row:
        print(f"  [WARN] '{drug_name}' not found in ChEMBL.")
        return {}

    chembl_id, pref_name, mw, alogp, psa, hba, hbd = row
    print(f"  Found: {pref_name} ({chembl_id}) MW={mw}, AlogP={alogp}")

    # Step 2: Get mean IC50/EC50 values from bioactivity assays
    cursor.execute("""
        SELECT act.standard_type, AVG(act.standard_value), COUNT(*) as n
        FROM activities act
        JOIN molecule_dictionary md ON act.molregno = md.molregno
        WHERE md.chembl_id = ?
          AND act.standard_type IN ('IC50', 'EC50', 'Ki', 'Kd')
          AND act.standard_units = 'nM'
          AND act.standard_relation = '='
        GROUP BY act.standard_type
        ORDER BY n DESC
        LIMIT 5
    """, (chembl_id,))
    binding_rows = cursor.fetchall()

    binding = {}
    for btype, avg_val, n in binding_rows:
        binding[btype] = {"mean_nM": round(avg_val, 2) if avg_val else None, "n_assays": n}

    # Step 3: Get the main target (first high-confidence binding target)
    cursor.execute("""
        SELECT td.pref_name, td.target_type, dm.action_type
        FROM drug_mechanism dm
        JOIN molecule_dictionary md ON dm.molregno = md.molregno
        JOIN target_dictionary td ON dm.tid = td.tid
        WHERE md.chembl_id = ?
        LIMIT 3
    """, (chembl_id,))
    target_rows = cursor.fetchall()
    targets = [{"target": t[0], "type": t[1], "action": t[2]} for t in target_rows]

    return {
        "chembl_id": chembl_id,
        "pref_name": pref_name,
        "molecular_weight": mw,
        "alogp": alogp,
        "psa": psa,
        "hba": hba,
        "hbd": hbd,
        "binding_affinities": binding,
        "mechanism_targets": targets,
    }

def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: ChEMBL database not found at: {DB_PATH}")
        print("Please extract chembl_37_sqlite.tar.gz first.")
        sys.exit(1)

    print(f"Connecting to ChEMBL database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)

    results = {}
    for drug_key, meta in TARGET_DRUGS.items():
        print(f"\nQuerying: {drug_key} ({meta['disease']})")
        info = get_drug_info(conn, drug_key)
        if info:
            results[drug_key] = {
                **meta,
                **info,
            }
        else:
            results[drug_key] = {**meta, "error": "not found in ChEMBL"}

    conn.close()

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✓ Saved ChEMBL drug parameters to: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
