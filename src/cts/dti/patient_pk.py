"""
Patient Pharmacokinetic/Pharmacodynamic Module

Computes personalized drug clearance, volume of distribution, half-life,
and bioavailability based on patient characteristics.

Based on physiological scaling rules from:
  - Dooley et al., Clin Pharmacokinet 2008
  - Johnson & Bhatt, JAMA 2020
  - FDA guidance on pediatric/geriatric dose adjustment
"""

from __future__ import annotations
import numpy as np
from dataclasses import dataclass


@dataclass
class PatientProfile:
    age: float          # years
    weight: float       # kg
    sex: str            # "male" | "female"
    gfr: float          # mL/min (kidney function; normal 60-120)
    ast: float          # IU/L (liver - alanine aminotransferase; normal < 40)
    alt: float          # IU/L (liver - aspartate aminotransferase; normal < 40)
    comorbidities: list[str]  # e.g. ["diabetes", "hypertension", "ckd"]

    @classmethod
    def healthy_adult(cls, age: float = 35, weight: float = 70) -> "PatientProfile":
        return cls(age=age, weight=weight, sex="male", gfr=90, ast=25, alt=25, comorbidities=[])


class PatientPKModule:
    """
    Computes patient-specific PK parameters and encodes them as a feature vector.

    Output feature vector (12-dim):
      [clearance_factor, vd_factor, half_life_factor, bioavail_factor,
       age_normalized, weight_normalized, gfr_normalized, liver_factor,
       renal_score, comorbidity_score, sex_factor, metabolic_rate]
    """

    def _age_clearance_factor(self, age: float) -> float:
        """Renal/hepatic clearance declines with age."""
        if age < 18:
            return 0.65
        elif age <= 45:
            return 1.0
        elif age <= 65:
            return 0.85
        elif age <= 75:
            return 0.70
        elif age <= 85:
            return 0.55
        else:
            return 0.40

    def _weight_vd_factor(self, weight: float) -> float:
        """Volume of distribution scales with body size (allometric scaling)."""
        return (weight / 70.0) ** 0.75

    def _renal_clearance_factor(self, gfr: float) -> float:
        """
        Renal function correction (Cockcroft-Gault based).
        Normal GFR: 60-120 mL/min
        """
        if gfr >= 90:
            return 1.0
        elif gfr >= 60:
            return 0.85
        elif gfr >= 30:
            return 0.60
        elif gfr >= 15:
            return 0.35
        else:
            return 0.15  # Dialysis-dependent

    def _liver_factor(self, ast: float, alt: float) -> tuple[float, float]:
        """
        Liver function affects:
          - First-pass metabolism (bioavailability increases when liver is damaged)
          - Metabolic clearance (decreases when liver is damaged)
        Returns: (bioavailability_multiplier, clearance_multiplier)
        """
        # Normal: AST < 40, ALT < 40
        liver_damage = ((ast / 40.0) + (alt / 40.0)) / 2.0  # 1.0 = normal
        if liver_damage <= 1.2:
            return 1.0, 1.0  # Normal liver
        elif liver_damage <= 2.0:
            return 1.3, 0.8  # Mild damage: higher bioavail, lower clearance
        elif liver_damage <= 3.0:
            return 1.6, 0.6  # Moderate
        else:
            return 2.0, 0.4  # Severe hepatic impairment

    def _comorbidity_score(self, comorbidities: list[str]) -> float:
        """
        Comorbidity burden score (0-1).
        High score = more systemic disease burden, reduced drug distribution.
        """
        scores = {
            "diabetes": 0.15,
            "hypertension": 0.10,
            "ckd": 0.25,
            "heart_failure": 0.30,
            "copd": 0.15,
            "liver_disease": 0.25,
            "obesity": 0.10,
            "cancer": 0.20,
            "immunocompromised": 0.20,
        }
        total = sum(scores.get(c.lower(), 0.05) for c in comorbidities)
        return min(1.0, total)

    def compute_pk_params(self, patient: PatientProfile, drug_alogp: float = 2.0, drug_mw: float = 400.0) -> dict:
        """
        Compute full PK parameter set for a patient-drug combination.
        """
        age_factor = self._age_clearance_factor(patient.age)
        vd_factor = self._weight_vd_factor(patient.weight)
        renal_factor = self._renal_clearance_factor(patient.gfr)
        bioavail_mult, hep_clearance_factor = self._liver_factor(patient.ast, patient.alt)
        comorbidity_score = self._comorbidity_score(patient.comorbidities)

        # Sex factor: males have ~15% higher metabolic clearance on average
        sex_factor = 1.0 if patient.sex.lower() == "male" else 0.87

        # Base PK parameters (population averages for an average drug)
        # These are modulated by the drug's AlogP and MW
        # High AlogP → high Vd (lipophilic), high protein binding
        # High MW → lower oral bioavailability (poor absorption)
        base_bioavail = max(0.1, min(1.0, 0.8 - (drug_mw - 300) / 2000 + (drug_alogp - 2) * 0.05))
        base_clearance = 15.0  # L/h (population average)
        base_vd = 100.0 * (1 + drug_alogp * 0.5)  # L (lipophilic → larger Vd)

        # Apply patient factors
        clearance = base_clearance * age_factor * renal_factor * hep_clearance_factor * sex_factor
        vd = base_vd * vd_factor
        bioavailability = base_bioavail * bioavail_mult
        half_life_h = 0.693 * vd / max(clearance, 0.1)

        # Tmax and Cmax (simplified)
        tmax_h = 1.5 / (1 + drug_alogp * 0.1)  # High lipophilicity → slower absorption
        cmax_relative = bioavailability / (clearance * tmax_h)

        return {
            "clearance_L_h": round(clearance, 3),
            "volume_of_distribution_L": round(vd, 1),
            "half_life_h": round(half_life_h, 2),
            "bioavailability": round(min(1.0, bioavailability), 3),
            "tmax_h": round(tmax_h, 2),
            "cmax_relative": round(cmax_relative, 4),
            "factors": {
                "age": round(age_factor, 3),
                "renal": round(renal_factor, 3),
                "hepatic_clearance": round(hep_clearance_factor, 3),
                "hepatic_bioavail": round(bioavail_mult, 3),
                "weight_vd": round(vd_factor, 3),
                "sex": round(sex_factor, 3),
                "comorbidity_burden": round(comorbidity_score, 3),
            }
        }

    def encode(self, patient: PatientProfile, drug_alogp: float = 2.0, drug_mw: float = 400.0) -> np.ndarray:
        """
        Encode patient + drug PK parameters into a 12-dim feature vector for the model.
        All values normalized to [0, 1] range.
        """
        pk = self.compute_pk_params(patient, drug_alogp, drug_mw)
        f = pk["factors"]

        return np.array([
            pk["bioavailability"],                          # F
            min(1.0, pk["clearance_L_h"] / 50.0),          # CL (normalized to 50 L/h max)
            min(1.0, pk["half_life_h"] / 72.0),             # t½ (normalized to 72h max)
            min(1.0, pk["volume_of_distribution_L"] / 500), # Vd
            f["age"],
            f["renal"],
            f["hepatic_clearance"],
            f["hepatic_bioavail"] / 2.0,                   # Normalized (max 2.0)
            f["weight_vd"],
            f["sex"],
            f["comorbidity_burden"],
            min(1.0, patient.age / 100.0),                  # Raw age normalized
        ], dtype=np.float32)

    def patient_efficacy_multiplier(self, patient: PatientProfile, drug_alogp: float = 2.0) -> float:
        """
        Quick scalar: how much does this patient's physiology reduce/increase drug efficacy?
        1.0 = healthy 35yo adult baseline, <1 = reduced efficacy, >1 = increased exposure
        """
        pk = self.compute_pk_params(patient, drug_alogp)
        # Effective drug exposure ∝ bioavailability / clearance
        exposure = pk["bioavailability"] / max(pk["clearance_L_h"] / 15.0, 0.1)
        return round(min(2.0, exposure), 3)
