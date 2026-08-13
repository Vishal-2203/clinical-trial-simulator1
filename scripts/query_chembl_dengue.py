"""
Query ChEMBL for Dengue-specific compounds:
- NS5 RNA polymerase inhibitors
- NS3 protease/helicase inhibitors
- Envelope protein binders

This fills the dengue component_a slot with a real antiviral candidate.
"""

import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "chembl_37", "chembl_37_sqlite", "chembl_37.db")
PRIORS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "snapshots", "disease_priors_v2.json")

def query_dengue_compounds(conn, limit=5):
    """Find the top compounds active against Dengue virus targets."""
    cursor = conn.cursor()

    # Search by assay description mentioning Dengue
    cursor.execute("""
        SELECT DISTINCT
            md.chembl_id,
            md.pref_name,
            cp.mw_freebase,
            cp.alogp,
            AVG(act.standard_value) as avg_ic50,
            COUNT(*) as n,
            td.pref_name as target
        FROM activities act
        JOIN molecule_dictionary md ON act.molregno = md.molregno
        JOIN assays ass ON act.assay_id = ass.assay_id
        JOIN target_dictionary td ON ass.tid = td.tid
        LEFT JOIN compound_properties cp ON md.molregno = cp.molregno
        WHERE (
            UPPER(td.pref_name) LIKE '%DENGUE%'
            OR UPPER(ass.description) LIKE '%DENGUE%'
            OR UPPER(ass.description) LIKE '%DENV%'
        )
        AND act.standard_type = 'IC50'
        AND act.standard_units = 'nM'
        AND act.standard_relation = '='
        AND md.pref_name IS NOT NULL
        GROUP BY md.chembl_id
        HAVING avg_ic50 < 1000
        ORDER BY avg_ic50 ASC
        LIMIT ?
    """, (limit,))
    return cursor.fetchall()

def main():
    print("Querying ChEMBL for Dengue compounds...")
    conn = sqlite3.connect(DB_PATH)
    rows = query_dengue_compounds(conn, limit=10)

    print(f"\nTop {len(rows)} Dengue compounds (IC50 < 1000 nM):")
    print(f"{'ChEMBL ID':<15} {'Name':<30} {'MW':>8} {'AlogP':>7} {'IC50 (nM)':>12} {'Target'}")
    print("-" * 100)

    dengue_drugs = []
    for row in rows:
        chembl_id, name, mw, alogp, avg_ic50, n, target = row
        print(f"{chembl_id:<15} {str(name):<30} {str(mw or 'N/A'):>8} {str(alogp or 'N/A'):>7} {avg_ic50:>12.1f} {target}")
        dengue_drugs.append({
            "chembl_id": chembl_id,
            "name": name,
            "mw": mw,
            "alogp": alogp,
            "ic50_nM": round(avg_ic50, 2),
            "target": target
        })

    conn.close()

    # Save results
    output_path = os.path.join(os.path.dirname(__file__), "..", "data", "snapshots", "dengue_compounds.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(dengue_drugs, f, indent=2)
    print(f"\nSaved to: {output_path}")

    # Update the dengue priors component_a slot with the best candidate
    if dengue_drugs:
        best = dengue_drugs[0]
        import math

        def sigmoid_normalize_ic50(ic50_nM):
            log_ic50 = math.log10(max(0.001, ic50_nM))
            return round(max(0.05, min(0.95, 1.0 - (1 / (1 + math.exp(-(log_ic50 - 4)))))), 3)

        def alogp_to_toxicity(alogp):
            if alogp is None: return 0.15
            if alogp < 0: return 0.05
            elif alogp <= 2: return 0.10 + (alogp / 2) * 0.05
            elif alogp <= 5: return 0.15 + ((alogp - 2) / 3) * 0.15
            else: return min(0.60, 0.30 + (alogp - 5) * 0.08)

        efficacy = sigmoid_normalize_ic50(best["ic50_nM"])
        toxicity = alogp_to_toxicity(best["alogp"])

        with open(PRIORS_PATH) as f:
            priors = json.load(f)

        if "dengue" in priors and "ns3_inhibitor" in priors["dengue"]["components"]:
            priors["dengue"]["components"]["ns3_inhibitor"]["efficacy_weight"] = efficacy
            priors["dengue"]["components"]["ns3_inhibitor"]["toxicity_weight"] = toxicity
            priors["dengue"]["components"]["ns3_inhibitor"]["chembl_id"] = best["chembl_id"]
            priors["dengue"]["components"]["ns3_inhibitor"]["chembl_name"] = best["name"]
            priors["dengue"]["components"]["ns3_inhibitor"]["chembl_ic50_nM"] = best["ic50_nM"]
            priors["dengue"]["components"]["ns3_inhibitor"]["chembl_alogp"] = best["alogp"]
            priors["dengue"]["components"]["ns3_inhibitor"]["target"] = best["target"]
            with open(PRIORS_PATH, "w") as f:
                json.dump(priors, f, indent=2)
            print(f"\nUpdated dengue ns3_inhibitor in disease_priors_v2.json:")
            print(f"  Best candidate: {best['name']} ({best['chembl_id']}) IC50={best['ic50_nM']}nM -> efficacy={efficacy}")
        else:
            print("[INFO] dengue.ns3_inhibitor not in priors. Run add_dengue_disease.py first.")

if __name__ == "__main__":
    main()
