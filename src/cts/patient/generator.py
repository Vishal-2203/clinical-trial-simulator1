from __future__ import annotations

import random

from cts.environment.models import DiseaseType
from cts.patient.models import PatientProfile, PatientTrialState


def generate_synthetic_patients(count: int, seed: int = 17, disease: DiseaseType = DiseaseType.TYPE2_DIABETES) -> list[PatientTrialState]:
    rng = random.Random(seed)
    states: list[PatientTrialState] = []
    for idx in range(count):
        age = rng.randint(10, 85)
        sex = "female" if rng.random() < 0.5 else "male"
        
        # Determine age group
        if age < 18:
            age_group = "pediatric"
        elif age > 65:
            age_group = "elderly"
        else:
            age_group = "adult"
            
        # Comorbidities scale with age
        comorb_chance = 0.4 if age_group == "elderly" else (0.2 if age_group == "adult" else 0.05)
        comorbidities = [c for c in ["hypertension", "ckd", "obesity", "prior_dengue"] if rng.random() < comorb_chance]
        
        # Vitals depend on the disease and age group
        vitals = {"hr": rng.uniform(65.0, 85.0)}
        if disease == DiseaseType.TYPE2_DIABETES:
            vitals["glucose"] = rng.uniform(140.0, 240.0)
            vitals["sbp"] = rng.uniform(110.0, 140.0)
            vitals["dbp"] = rng.uniform(70.0, 90.0)
        elif disease == DiseaseType.HYPERTENSION:
            vitals["glucose"] = rng.uniform(80.0, 120.0)
            vitals["sbp"] = rng.uniform(135.0, 175.0)
            vitals["dbp"] = rng.uniform(85.0, 110.0)
        elif disease == DiseaseType.DENGUE:
            vitals["platelets"] = rng.uniform(100000.0, 130000.0)
            vitals["glucose"] = rng.uniform(80.0, 120.0)
            vitals["sbp"] = rng.uniform(110.0, 130.0)
            vitals["dbp"] = rng.uniform(70.0, 85.0)
        else: # NSCLC
            vitals["tumor_size"] = rng.uniform(3.0, 10.0)
            vitals["glucose"] = rng.uniform(80.0, 120.0)
            vitals["sbp"] = rng.uniform(110.0, 130.0)
            vitals["dbp"] = rng.uniform(70.0, 85.0)

        profile = PatientProfile(
            patient_id=f"syn-{seed}-{idx}",
            age=age,
            sex=sex,
            disease=disease,
            disease_stage=rng.choice(["mild", "moderate", "severe"]),
            age_group=age_group,
            comorbidities=comorbidities,
            baseline_labs={"alt": rng.uniform(10.0, 45.0), "ast": rng.uniform(10.0, 45.0)},
            vitals=vitals,
            concomitant_medications=[m for m in ["metformin", "ace_inhibitor", "statin"] if rng.random() < 0.3],
            biomarkers={"marker_a": rng.uniform(0.0, 1.0), "marker_b": rng.uniform(0.0, 1.0)},
            genotype={"cyp2d6": rng.choice(["normal", "poor", "rapid"]), "brca1": "negative"},
            inclusion_exclusion_flags={"eligible": True, "requires_manual_review": False},
        )
        states.append(PatientTrialState(
            profile=profile,
            assigned_arm=rng.choice(["control", "active_a", "active_b"]),
            lab_history=[profile.baseline_labs],
            vitals_history=[profile.vitals]
        ))
    return states

