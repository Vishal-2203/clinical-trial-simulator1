"""
Apply ChEMBL Drug Parameters to Disease Priors

This script reads chembl_drug_params.json and uses the real IC50/EC50 values
to calibrate the efficacy weights and toxicity weights in disease_priors_v2.json.

Key formula:
  - Lower IC50 (nM) → higher binding affinity → higher efficacy_weight
  - Higher AlogP → better membrane permeability → faster absorption
  - We normalize IC50 values to [0, 1] using a log-scale sigmoid
"""

import json
import math
import os

CHEMBL_PARAMS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "snapshots", "chembl_drug_params.json")
PRIORS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "snapshots", "disease_priors_v2.json")

def sigmoid_normalize_ic50(ic50_nM: float) -> float:
    """
    Converts IC50 (in nanoMolar) to an efficacy weight in [0, 1].
    Very low IC50 (e.g., 0.1 nM) → weight near 0.95 (very potent)
    Very high IC50 (e.g., 1e9 nM) → weight near 0.05 (very weak)
    """
    if ic50_nM is None or ic50_nM <= 0:
        return 0.3  # default moderate
    log_ic50 = math.log10(ic50_nM)
    # Sigmoid centered at log10(10000) = 4 (10 micromolar, typical drug threshold)
    return round(max(0.05, min(0.95, 1.0 - (1 / (1 + math.exp(-(log_ic50 - 4)))))), 3)

def alogp_to_toxicity(alogp: float) -> float:
    """
    Higher AlogP → more lipophilic → higher membrane penetration
    but also higher tendency for off-target toxicity.
    AlogP < 0: hydrophilic, low toxicity
    AlogP 2-5: optimal drug-like range
    AlogP > 5: potentially toxic
    """
    if alogp is None:
        return 0.15  # default
    if alogp < 0:
        return 0.05
    elif alogp <= 2:
        return 0.10 + (alogp / 2) * 0.05
    elif alogp <= 5:
        return 0.15 + ((alogp - 2) / 3) * 0.15
    else:
        return min(0.60, 0.30 + (alogp - 5) * 0.08)

def main():
    with open(CHEMBL_PARAMS_PATH) as f:
        chembl_params = json.load(f)

    with open(PRIORS_PATH) as f:
        priors = json.load(f)

    # Map from disease+component to priors key
    disease_component_map = {
        ("type2_diabetes", "a"): ("type2_diabetes", "biguanide"),
        ("type2_diabetes", "b"): ("type2_diabetes", "glp1_agonist"),
        ("hypertension", "a"):   ("hypertension", "ace_inhibitor"),
        ("hypertension", "b"):   ("hypertension", "calcium_blocker"),
        ("nsclc", "a"):           ("nsclc", "egfr_inhibitor"),
        ("dengue", "b"):          ("dengue", "antiviral"),
    }

    print("Applying ChEMBL parameters to disease_priors_v2.json...\n")

    for drug_key, drug_data in chembl_params.items():
        disease = drug_data.get("disease")
        component = drug_data.get("component")
        alogp = drug_data.get("alogp")
        binding = drug_data.get("binding_affinities", {})

        # Best IC50/EC50 for efficacy: prefer Ki > IC50 > EC50 (tightest binding)
        best_ic50 = None
        for btype in ["Ki", "IC50", "EC50"]:
            if btype in binding and binding[btype]["mean_nM"]:
                best_ic50 = binding[btype]["mean_nM"]
                break

        efficacy_weight = sigmoid_normalize_ic50(best_ic50)
        toxicity_weight = alogp_to_toxicity(alogp)

        key = (disease, component)
        if key in disease_component_map:
            disease_key, comp_key = disease_component_map[key]
            if disease_key in priors and comp_key in priors[disease_key].get("components", {}):
                old_eff = priors[disease_key]["components"][comp_key]["efficacy_weight"]
                old_tox = priors[disease_key]["components"][comp_key]["toxicity_weight"]
                priors[disease_key]["components"][comp_key]["efficacy_weight"] = efficacy_weight
                priors[disease_key]["components"][comp_key]["toxicity_weight"] = toxicity_weight
                priors[disease_key]["components"][comp_key]["chembl_ic50_nM"] = best_ic50
                priors[disease_key]["components"][comp_key]["chembl_alogp"] = alogp
                print(f"  [{disease}] {comp_key}: efficacy {old_eff:.2f} -> {efficacy_weight:.3f}  |  toxicity {old_tox:.2f} -> {toxicity_weight:.3f}  (IC50={best_ic50:.1f}nM, AlogP={alogp})")
            else:
                print(f"  [SKIP] {disease_key}/{comp_key} not found in priors.")
        else:
            print(f"  [SKIP] No mapping for ({disease}, component={component})")

    with open(PRIORS_PATH, "w") as f:
        json.dump(priors, f, indent=2)

    print(f"\nSaved calibrated priors to: {PRIORS_PATH}")

if __name__ == "__main__":
    main()
