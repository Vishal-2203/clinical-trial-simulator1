from __future__ import annotations

import copy
import json
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from cts.config import EventRates, TrialConfig
from cts.environment.models import ReactionSeverity, TrialState, DiseaseType
from cts.patient.models import PatientTrialState


@dataclass
class PatientLatent:
    metabolism: float
    immune_reactivity: float
    age_factor: float
    comorbidity: float


class EventEngine:
    """Seeded event engine for adverse events, dropout, and recruitment variation."""

    def __init__(self, rates: EventRates):
        self.rates = rates
        self._priors = {}
        # Load priors if available
        try:
            priors_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "snapshots", "disease_priors_v2.json")
            if os.path.exists(priors_path):
                with open(priors_path, "r") as f:
                    self._priors = json.load(f)
        except Exception:
            pass

    def _get_chembl_weights(self, disease_key: str) -> dict:
        """Return ChEMBL-calibrated (efficacy_a, efficacy_b, toxicity_a, toxicity_b) for a disease."""
        try:
            disease_data = self._priors.get(disease_key, {})
            components = disease_data.get("components", {})
            keys = list(components.keys())
            comp_a = components.get(keys[0], {}) if keys else {}
            comp_b = components.get(keys[1], {}) if len(keys) > 1 else {}
            return {
                "eff_a": comp_a.get("efficacy_weight", 0.4),
                "eff_b": comp_b.get("efficacy_weight", 0.3),
                "tox_a": comp_a.get("toxicity_weight", 0.1),
                "tox_b": comp_b.get("toxicity_weight", 0.15),
            }
        except Exception:
            return {"eff_a": 0.4, "eff_b": 0.3, "tox_a": 0.1, "tox_b": 0.15}

    def transition_patient(self, state: PatientTrialState, global_composition: dict[str, float]) -> PatientTrialState:
        # Update composition exposure
        state.composition_exposure = dict(global_composition)
        c_a = state.composition_exposure.get("a", 0.34)
        c_b = state.composition_exposure.get("b", 0.33)
        c_c = state.composition_exposure.get("c", 0.33)
        
        # Calculate PK-driven PD effect
        concentration = getattr(state, "drug_concentration", 1.0)
        pd_effect = (1.5 * concentration) / (0.5 + concentration) if concentration > 0 else 0.0
        
        # Resolve ChEMBL-calibrated weights for this patient's disease
        disease_key = state.profile.disease.value if hasattr(state.profile.disease, "value") else str(state.profile.disease)
        w = self._get_chembl_weights(disease_key)

        # Base efficacy and toxicity probabilities using real ChEMBL IC50-derived weights
        eff_prob = w["eff_a"] * c_a + w["eff_b"] * c_b - 0.1 * c_c
        if state.profile.disease_stage == "severe":
            eff_prob *= 0.8
        eff_prob += 0.1 * state.profile.biomarkers.get("marker_a", 0.5)
        state.efficacy_response = min(1.0, max(0.0, eff_prob + random.uniform(-0.05, 0.05)))
        
        # Toxicity probability from ChEMBL AlogP-derived weights
        tox_prob = w["tox_a"] * c_a + w["tox_b"] * c_b + 0.4 * c_c
        if state.profile.age_group == "elderly":
            tox_prob *= 1.3
        if "ckd" in state.profile.comorbidities:
            tox_prob *= 1.4
            
        # Update physiological vitals based on drug composition and disease
        vitals = dict(state.profile.vitals)
        
        if state.profile.disease == DiseaseType.TYPE2_DIABETES:
            # Efficacy lowers glucose, but toxicity elevates heart rate
            if state.assigned_arm == "treatment":
                # ChEMBL: Metformin eff_a=0.42, Semaglutide eff_b=0.882
                # Glucose reduction scales with real-world HbA1c efficacy
                reduction = (90 * w["eff_a"] * c_a + 130 * w["eff_b"] * c_b) * pd_effect
                vitals["glucose"] = max(80.0, vitals.get("glucose", 150.0) - reduction + random.uniform(-5.0, 5.0))
                # GLP-1 causes mild tachycardia (real-world side effect)
                hr_elevation = (15 * w["tox_b"] * c_b + 5 * c_c) * pd_effect
                vitals["hr"] = min(130.0, vitals.get("hr", 72.0) + hr_elevation + random.uniform(-2.0, 2.0))
            else:
                # Placebo / untreated progression
                vitals["glucose"] = min(300.0, vitals.get("glucose", 150.0) + 1.5 + random.uniform(-3.0, 3.0))
                vitals["hr"] = vitals.get("hr", 72.0) + random.uniform(-1.0, 1.0)
                
        elif state.profile.disease == DiseaseType.HYPERTENSION:
            if state.assigned_arm == "treatment":
                # ChEMBL: Lisinopril eff_a=0.593 (ACEi), Amlodipine eff_b=0.659 (CCB)
                sbp_red = (55 * w["eff_a"] * c_a + 42 * w["eff_b"] * c_b) * pd_effect
                dbp_red = (30 * w["eff_a"] * c_a + 22 * w["eff_b"] * c_b) * pd_effect
                vitals["sbp"] = max(90.0, vitals.get("sbp", 145.0) - sbp_red + random.uniform(-3.0, 3.0))
                vitals["dbp"] = max(60.0, vitals.get("dbp", 92.0) - dbp_red + random.uniform(-2.0, 2.0))
                # Reflex tachycardia from CCB - real side effect, scaled to AlogP toxicity
                hr_elevation = (12 * w["tox_b"] * c_b + 4 * c_c) * pd_effect
                vitals["hr"] = min(125.0, vitals.get("hr", 70.0) + hr_elevation + random.uniform(-2.0, 2.0))
            else:
                vitals["sbp"] = min(200.0, vitals.get("sbp", 145.0) + 0.8 + random.uniform(-2.0, 2.0))
                vitals["dbp"] = min(120.0, vitals.get("dbp", 92.0) + 0.5 + random.uniform(-1.0, 1.0))
                vitals["hr"] = vitals.get("hr", 70.0) + random.uniform(-1.0, 1.0)
                
        elif state.profile.disease == DiseaseType.DENGUE:
            if state.assigned_arm == "treatment":
                # ChEMBL: Tecovirimat antiviral eff_b=0.95 (IC50=5.3nM)
                # Brefeldin A analogs eff_a modeled at 0.60 from vaccine arm
                recovery = (55000 * w["eff_a"] * c_a + 48000 * w["eff_b"] * c_b) * pd_effect
                vitals["platelets"] = min(400000.0, vitals.get("platelets", 110000.0) + recovery + random.uniform(-1000.0, 1000.0))
                hr_elevation = (8 * w["tox_a"] * c_a + 4 * c_c) * pd_effect
                vitals["hr"] = min(120.0, vitals.get("hr", 72.0) + hr_elevation + random.uniform(-1.0, 1.0))
            else:
                vitals["platelets"] = max(20000.0, vitals.get("platelets", 110000.0) - 15000.0 + random.uniform(-2000.0, 2000.0))
                vitals["hr"] = vitals.get("hr", 72.0) + random.uniform(-1.0, 1.0)
                
        else: # NSCLC
            if state.assigned_arm == "treatment":
                # ChEMBL: Osimertinib eff_a=0.889 (Ki=82.9nM, EGFR T790M)
                shrinkage = (7.5 * w["eff_a"] * c_a + 3.0 * w["eff_b"] * c_b) * pd_effect
                vitals["tumor_size"] = max(0.1, vitals.get("tumor_size", 5.0) - shrinkage + random.uniform(-0.2, 0.2))
                # Osimertinib AlogP=4.51 → moderate cardiac toxicity
                hr_elevation = (14 * w["tox_a"] * c_a + 10 * w["tox_b"] * c_b + 8 * c_c) * pd_effect
                vitals["hr"] = min(140.0, vitals.get("hr", 75.0) + hr_elevation + random.uniform(-3.0, 3.0))
            else:
                vitals["tumor_size"] = min(15.0, vitals.get("tumor_size", 5.0) + 0.15 + random.uniform(-0.05, 0.05))
                vitals["hr"] = vitals.get("hr", 75.0) + random.uniform(-1.0, 1.0)

        state.profile.vitals = vitals
        state.vitals_history.append(vitals)

        # Trigger adverse events based on toxic thresholds
        is_serious = False
        grade = 1
        if vitals.get("hr", 70.0) > 120.0:
            is_serious = True
            grade = 3
        if vitals.get("glucose", 120.0) > 280.0 or vitals.get("sbp", 120.0) > 185.0:
            is_serious = True
            grade = 3
        if vitals.get("tumor_size", 0.0) > 12.0:
            is_serious = True
            grade = 4
        if vitals.get("platelets", 250000.0) < 50000.0:
            is_serious = True
            grade = 4

        if random.random() < tox_prob or is_serious:
            grade = max(grade, 3 if is_serious else (3 if random.random() < 0.2 else 1))
            ae = {
                "term": "Thrombocytopenia" if vitals.get("platelets", 250000.0) < 100000.0 else ("Tachycardia" if vitals.get("hr", 70.0) > 110.0 else ("Hyperglycemia" if vitals.get("glucose", 120.0) > 250.0 else "Nausea")),
                "grade": grade,
                "is_serious": grade >= 3,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            state.adverse_events.append(ae)

        # Calculate dropout risk
        base_dropout = 0.05
        if state.adverse_events and any(ae["grade"] >= 3 for ae in state.adverse_events):
            base_dropout += 0.3
        if state.efficacy_response < 0.1:
            base_dropout += 0.1
            
        state.dropout_risk = min(1.0, base_dropout)
        if random.random() < state.dropout_risk:
            state.status = "dropped_out"
            
        state.lab_history.append({"alt": 25.0 + random.uniform(-5, 5)})
        return state

    def step(self, state: TrialState, rng: random.Random, config: TrialConfig | None = None) -> TrialState:
        next_state = copy.deepcopy(state)
        from cts.config import default_config
        cfg = config or default_config()
        
        disease_profile = cfg.disease_profiles.get(next_state.disease, {})
        phase_profile = self._phase_profile(next_state.stage_name)
        
        # 1. Update Pharmacokinetics (Concentration)
        absorbed = next_state.dose_level * cfg.pk_absorption_rate
        next_state.drug_concentration = (next_state.drug_concentration * (1.0 - cfg.pk_elimination_rate)) + absorbed
        
        # 2. Update Disease Progression (Drift)
        drift = disease_profile.get("drift_rate", cfg.disease_drift_base)
        concentration = next_state.drug_concentration
        pd_effect = (cfg.pd_emax * concentration) / (cfg.pd_ec50 + concentration)
        next_state.disease_progression = max(0.1, next_state.disease_progression + drift - (pd_effect * 0.15))

        # Propagate concentration state to each patient
        for p in next_state.patient_states:
            if p.status == "active":
                p.drug_concentration = next_state.drug_concentration

        if next_state.active > 0:
            dropped = 0
            aes = 0
            serious = 0
            fatal = 0
            minor = 0
            major = 0
            improvement_sum = 0.0
            
            tox_spike = max(0.0, next_state.drug_concentration - 0.7) * 0.1
            next_state.cumulative_toxicity = max(0.0, next_state.cumulative_toxicity * 0.9 + tox_spike)

            for _ in range(min(next_state.active, next_state.sample_batch_size)):
                latent = self._sample_patient_latent(rng)
                
                efficacy, toxicity = self._simulate_response_pkpd(
                    latent,
                    next_state.composition,
                    next_state.drug_concentration,
                    next_state.cumulative_toxicity,
                    disease_profile,
                    rng,
                    phase_boost=phase_profile["response_boost"],
                    phase_tox_scale=phase_profile["toxicity_scale"],
                )
                
                reaction = self._classify_reaction(toxicity, disease_profile)

                if reaction != ReactionSeverity.NONE:
                    aes += 1
                if reaction in {ReactionSeverity.MAJOR, ReactionSeverity.FATAL}:
                    serious += 1
                if reaction == ReactionSeverity.MINOR:
                    minor += 1
                if reaction == ReactionSeverity.MAJOR:
                    major += 1
                if reaction == ReactionSeverity.FATAL:
                    fatal += 1

                improvement_sum += efficacy

                if rng.random() < min(1.0, self.rates.dropout_prob * phase_profile["dropout_scale"] * (1.0 + next_state.cumulative_toxicity)):
                    dropped += 1

            next_state.active = max(0, next_state.active - dropped)
            next_state.dropped_out += dropped
            next_state.adverse_events += aes
            next_state.serious_adverse_events += serious
            next_state.fatal_reactions += fatal
            next_state.minor_reactions += minor
            next_state.major_reactions += major
            next_state.adverse_event_log.append(aes)

            completed_candidates = max(0, int(0.12 * next_state.active))
            next_state.completed += completed_candidates
            next_state.active = max(0, next_state.active - completed_candidates)

            sampled = max(1, min(next_state.enrolled, next_state.sample_batch_size))
            avg_improvement = improvement_sum / sampled
            next_state.biomarker_improvement = max(0.0, min(1.0, avg_improvement))
            
            efficacy_delta = max(0.0, (1.0 - next_state.disease_progression) * 0.1 - (serious * 0.002))
            next_state.efficacy_signal = min(1.0, next_state.efficacy_signal * 0.9 + efficacy_delta)

        # 3. Aggregate patient demographics and mean physiological vitals
        active_pats = [p for p in next_state.patient_states if p.status == "active"]
        if active_pats:
            next_state.pediatric_count = sum(1 for p in active_pats if p.profile.age_group == "pediatric")
            next_state.adult_count = sum(1 for p in active_pats if p.profile.age_group == "adult")
            next_state.elderly_count = sum(1 for p in active_pats if p.profile.age_group == "elderly")
            
            next_state.mean_heart_rate = sum(p.profile.vitals.get("hr", 75.0) for p in active_pats) / len(active_pats)
            next_state.mean_glucose = sum(p.profile.vitals.get("glucose", 120.0) for p in active_pats) / len(active_pats)
            next_state.mean_systolic_bp = sum(p.profile.vitals.get("sbp", 120.0) for p in active_pats) / len(active_pats)
            next_state.mean_diastolic_bp = sum(p.profile.vitals.get("dbp", 80.0) for p in active_pats) / len(active_pats)
            next_state.mean_tumor_size = sum(p.profile.vitals.get("tumor_size", 0.0) for p in active_pats) / len(active_pats)
            next_state.mean_platelets = sum(p.profile.vitals.get("platelets", 250000.0) for p in active_pats) / len(active_pats)
        else:
            next_state.pediatric_count = 0
            next_state.adult_count = 0
            next_state.elderly_count = 0
            next_state.mean_heart_rate = 75.0
            next_state.mean_glucose = 120.0
            next_state.mean_systolic_bp = 120.0
            next_state.mean_diastolic_bp = 80.0
            next_state.mean_tumor_size = 0.0
            next_state.mean_platelets = 250000.0

        return next_state

    def _simulate_response_pkpd(
        self,
        latent: PatientLatent,
        composition: dict[str, float],
        concentration: float,
        cumulative_toxicity: float,
        disease_profile: dict,
        rng: random.Random,
        phase_boost: float = 1.0,
        phase_tox_scale: float = 1.0,
    ) -> tuple[float, float]:
        c_a = composition.get("a", 0.0)
        c_b = composition.get("b", 0.0)
        c_c = composition.get("c", 0.0)

        efficacy_potency = (0.4 * c_a + 0.3 * c_b - 0.1 * c_c)
        efficacy = (
            disease_profile.get("baseline_response", 0.5)
            + (efficacy_potency * concentration * (1.0 - latent.comorbidity))
            + rng.gauss(0.0, 0.04)
        ) * phase_boost

        tox_sensitivity = disease_profile.get("toxicity_sensitivity", 0.4)
        toxicity = (
            tox_sensitivity
            + (0.5 * c_c * concentration)
            + (0.2 * cumulative_toxicity)
            + (0.1 * latent.age_factor)
            + rng.gauss(0.0, 0.05)
        ) * phase_tox_scale

        return (max(0.0, min(1.0, efficacy)), max(0.0, min(1.0, toxicity)))

    def _phase_profile(self, stage_name: str) -> dict[str, float]:
        if stage_name == "stage1":
            return {"response_boost": 0.95, "toxicity_scale": 1.08, "dropout_scale": 1.05}
        if stage_name == "stage2":
            return {"response_boost": 1.0, "toxicity_scale": 1.0, "dropout_scale": 1.0}
        return {"response_boost": 1.05, "toxicity_scale": 0.92, "dropout_scale": 0.94}

    def _sample_patient_latent(self, rng: random.Random) -> PatientLatent:
        return PatientLatent(
            metabolism=min(1.0, max(0.0, rng.gauss(0.55, 0.2))),
            immune_reactivity=min(1.0, max(0.0, rng.gauss(0.50, 0.2))),
            age_factor=min(1.0, max(0.0, rng.gauss(0.52, 0.22))),
            comorbidity=min(1.0, max(0.0, rng.gauss(0.45, 0.24))),
        )

    def _classify_reaction(self, toxicity: float, disease_profile: dict) -> ReactionSeverity:
        if toxicity >= disease_profile.get("fatal_threshold", 0.85):
            return ReactionSeverity.FATAL
        if toxicity >= disease_profile.get("major_threshold", 0.60):
            return ReactionSeverity.MAJOR
        if toxicity >= self.rates.adverse_event_prob:
            return ReactionSeverity.MINOR
        return ReactionSeverity.NONE

    def sample_recruitment(self, base_count: int, rng: random.Random) -> int:
        jitter = self.rates.recruit_variation
        factor = 1.0 + rng.uniform(-jitter, jitter)
        return max(0, int(round(base_count * factor)))
