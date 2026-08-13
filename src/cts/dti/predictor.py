"""
DTI Predictor — High-level inference API for the Novel Pathogen Drug Efficacy Predictor

Usage:
  from cts.dti.predictor import DTIPredictor, predict_drug_efficacy

  result = predict_drug_efficacy(
      pathogen_input="MKTIIALSYIFCLVFA...",   # FASTA or text description
      drugs=[
          {"input": "CC(=O)Nc1ccc(O)cc1", "ratio": 0.5},   # SMILES or drug name
          {"input": "Osimertinib", "ratio": 0.3},
          {"input": "Carboplatin", "ratio": 0.2},
      ],
      patient={"age": 65, "weight": 78, "gfr": 45, "ast": 35, "alt": 40,
               "sex": "female", "comorbidities": ["hypertension", "ckd"]}
  )
"""

from __future__ import annotations

import os
import json
import time
import re
import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

import numpy as np
import torch

# Add project root
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from cts.dti.encoders import DrugEncoder, ProteinEncoder
from cts.dti.patient_pk import PatientProfile, PatientPKModule
from cts.dti.fusion_model import DTIFusionModel

MODEL_PATH = str(Path(__file__).parent.parent.parent.parent / "artifacts" / "dti" / "dti_model.pt")
STATS_PATH = str(Path(__file__).parent.parent.parent.parent / "artifacts" / "dti" / "training_stats.json")
DRUG_VECTOR_DIM = 2248
CHEMBL_DB_PATH = str(Path(__file__).parent.parent.parent.parent / "chembl_37" / "chembl_37_sqlite" / "chembl_37.db")

PATHOGEN_TARGET_HINTS = [
    ("spike", "viral entry / envelope glycoprotein"),
    ("glycoprotein", "viral entry / envelope glycoprotein"),
    ("polymerase", "polymerase / replication machinery"),
    ("protease", "protease / polyprotein processing"),
    ("reverse transcriptase", "reverse transcription machinery"),
    ("dna gyrase", "bacterial DNA topology control"),
    ("topoisomerase", "DNA topology control"),
    ("dhfr", "folate synthesis / nucleotide metabolism"),
    ("inha", "mycolic-acid biosynthesis"),
    ("katg", "mycobacterial activation / resistance pathway"),
]

TARGET_QUERY_EXPANSIONS = {
    "egfr": ["epidermal growth factor receptor", "egfr"],
    "epidermal": ["epidermal growth factor receptor"],
    "polymerase": ["rna-directed rna polymerase", "rna polymerase", "dna polymerase", "polymerase"],
    "rna": ["rna-directed rna polymerase", "rna polymerase"],
    "protease": ["protease"],
    "cell-wall": ["penicillin-binding protein", "peptidoglycan"],
    "cell": ["penicillin-binding protein", "peptidoglycan"],
    "gyrase": ["dna gyrase"],
    "topoisomerase": ["topoisomerase"],
    "ribosomal": ["ribosomal"],
}


class DTIPredictor:
    """Singleton-style predictor that lazily loads all model components."""

    _instance: Optional["DTIPredictor"] = None

    def __init__(self, device: str = "auto"):
        if device == "auto":
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self._device = device

        self._drug_encoder = DrugEncoder()
        self._protein_encoder = ProteinEncoder(device=self._device)
        self._patient_pk = PatientPKModule()
        self._chembl_conn: Optional[sqlite3.Connection] = None
        self._model: Optional[DTIFusionModel] = None
        self._model_loaded = False

    @classmethod
    def get_instance(cls) -> "DTIPredictor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_model(self):
        if self._model_loaded:
            return
        self._model = DTIFusionModel()
        if os.path.exists(MODEL_PATH):
            print(f"[DTIPredictor] Loading trained model from {MODEL_PATH}")
            checkpoint = torch.load(MODEL_PATH, map_location=self._device, weights_only=False)
            self._model.load_state_dict(checkpoint["model_state"])
            print(f"[DTIPredictor] Model loaded (trained epoch {checkpoint.get('epoch', '?')}, val_loss={checkpoint.get('val_loss', '?'):.4f})")
        else:
            raise FileNotFoundError(f"Trained DTI model not found at {MODEL_PATH}")
        self._model.to(self._device)
        self._model.eval()
        self._model_loaded = True

    def _infer_mechanism_breakdown(self, pathogen_input: str, resolved_drugs: list[dict]) -> dict:
        pathogen_text = pathogen_input.lower()
        target_hints = []
        seen = set()
        for keyword, label in PATHOGEN_TARGET_HINTS:
            if keyword in pathogen_text and label not in seen:
                target_hints.append({"pathogen_signal": keyword, "target_family": label})
                seen.add(label)

        if not target_hints:
            target_hints.append({"pathogen_signal": "unclassified", "target_family": "unknown pathogen family"})

        drug_mechanisms = []
        for drug in resolved_drugs:
            drug_name = (drug.get("drug_name") or drug.get("input") or "unknown drug").strip()
            smiles = drug.get("resolved_smiles") or ""
            confidence = "high" if smiles else "medium"
            drug_mechanisms.append({
                "drug": drug_name,
                "ratio": drug.get("ratio", 0.0),
                "predicted_action": "binding / activity modulation estimated from ChEMBL-trained latent interaction model",
                "confidence": confidence,
            })

        return {
            "pathogen_targets": target_hints,
            "drug_actions": drug_mechanisms,
            "summary": "Pathogen family signals are matched against inferred target families, and each drug is scored through the trained DTI interaction model with patient PK adjustment.",
        }

    def _connect_chembl(self) -> Optional[sqlite3.Connection]:
        if self._chembl_conn is None and os.path.exists(CHEMBL_DB_PATH):
            self._chembl_conn = sqlite3.connect(CHEMBL_DB_PATH, check_same_thread=False)
        return self._chembl_conn

    def _target_queries_from_text(self, pathogen_input: str) -> list[str]:
        text = pathogen_input.lower()
        queries: list[str] = []
        for key, expansions in TARGET_QUERY_EXPANSIONS.items():
            if key in text:
                queries.extend(expansions)
        for token in re.findall(r"[a-z0-9]{4,}", text):
            queries.append(token)

        deduped = []
        seen = set()
        for query in queries:
            q = query.strip().lower()
            if q and q not in seen:
                seen.add(q)
                deduped.append(q)
        return deduped[:12]

    def _chembl_potency_prior(self, pathogen_input: str, resolved_drugs: list[dict]) -> Optional[dict]:
        """
        Use direct ChEMBL evidence when a known drug-target pair is present.

        This improves demo accuracy for known targets such as EGFR while keeping
        the neural DTI model as the fallback for genuinely novel inputs.
        """
        conn = self._connect_chembl()
        if conn is None:
            return None

        target_queries = self._target_queries_from_text(pathogen_input)
        if not target_queries:
            return None

        cur = conn.cursor()
        weighted_scores = []
        evidence = []

        for drug in resolved_drugs:
            drug_name = str(drug.get("drug_name") or drug.get("input") or "").strip()
            if not drug_name:
                continue
            cur.execute(
                """
                SELECT molregno
                FROM molecule_dictionary
                WHERE UPPER(pref_name) = ?
                LIMIT 1
                """,
                (drug_name.upper(),),
            )
            mol_row = cur.fetchone()
            if not mol_row:
                cur.execute(
                    """
                    SELECT molregno
                    FROM molecule_synonyms
                    WHERE UPPER(synonyms) = ?
                    LIMIT 1
                    """,
                    (drug_name.upper(),),
                )
                mol_row = cur.fetchone()
            if not mol_row:
                continue

            molregno = int(mol_row[0])
            ratio = float(drug.get("ratio", 0.0) or 0.0)
            best_row = None
            for target_query in target_queries:
                cur.execute(
                    """
                    SELECT
                        md.pref_name,
                        td.pref_name,
                        td.organism,
                        MAX(act.pchembl_value) AS best_pchembl,
                        COUNT(*) AS measurements
                    FROM activities act
                    JOIN molecule_dictionary md ON act.molregno = md.molregno
                    JOIN assays ass ON act.assay_id = ass.assay_id
                    JOIN target_dictionary td ON ass.tid = td.tid
                    WHERE act.molregno = ?
                      AND UPPER(td.pref_name) LIKE ?
                      AND act.pchembl_value IS NOT NULL
                    GROUP BY md.pref_name, td.pref_name, td.organism
                    ORDER BY best_pchembl DESC
                    LIMIT 1
                    """,
                    (molregno, f"%{target_query.upper()}%"),
                )
                row = cur.fetchone()
                if row and (best_row is None or float(row[3]) > float(best_row[3])):
                    best_row = row

            if best_row:
                pchembl = float(best_row[3])
                score = max(0.0, min(1.0, (pchembl - 4.0) / 6.0))
                weighted_scores.append(score * ratio)
                evidence.append({
                    "drug": drug_name,
                    "target": best_row[1],
                    "organism": best_row[2],
                    "pchembl": round(pchembl, 3),
                    "measurements": int(best_row[4]),
                    "ratio": ratio,
                    "score": round(score, 4),
                })

        if not evidence:
            return None

        covered_ratio = sum(float(item["ratio"]) for item in evidence)
        if covered_ratio <= 0:
            return None
        prior_score = sum(weighted_scores) / covered_ratio
        return {
            "score": round(max(0.0, min(1.0, prior_score)), 4),
            "covered_ratio": round(covered_ratio, 4),
            "evidence": evidence,
        }

    def predict(
        self,
        pathogen_input: str,
        drugs: list[dict],
        patient_dict: dict,
    ) -> dict:
        """
        Full prediction pipeline.

        Args:
            pathogen_input: FASTA sequence or text description of the pathogen
            drugs: list of {input: smiles_or_name, ratio: float, dosage_mg: float}
            patient_dict: {age, weight, sex, gfr, ast, alt, comorbidities}

        Returns:
            Full analysis dict with efficacy, toxicity, mechanism, PK, recommendations
        """
        t0 = time.time()
        self._load_model()

        # 1. Encode pathogen
        protein_vec, protein_mode = self._protein_encoder.encode(pathogen_input)

        # 2. Encode drugs (weighted combination by ratio)
        resolved_drugs = []
        combined_drug_vec = np.zeros(DRUG_VECTOR_DIM, dtype=np.float32)
        total_ratio = sum(d.get("ratio", 1.0) for d in drugs)

        for drug_spec in drugs:
            drug_input = drug_spec.get("input", "")
            ratio = drug_spec.get("ratio", 1.0 / len(drugs))
            drug_vec, smiles, name = self._drug_encoder.encode(drug_input)
            combined_drug_vec += drug_vec * (ratio / total_ratio)
            resolved_drugs.append({
                "input": drug_input,
                "resolved_smiles": smiles,
                "drug_name": name or drug_input,
                "ratio": ratio / total_ratio,
            })

        # 3. Encode patient
        patient = PatientProfile(
            age=float(patient_dict.get("age", 35)),
            weight=float(patient_dict.get("weight", 70)),
            sex=str(patient_dict.get("sex", "male")),
            gfr=float(patient_dict.get("gfr", 90)),
            ast=float(patient_dict.get("ast", 25)),
            alt=float(patient_dict.get("alt", 25)),
            comorbidities=list(patient_dict.get("comorbidities", [])),
        )

        # Estimate mean AlogP from resolved SMILES for PK calculation
        avg_alogp = 2.0
        avg_mw = 400.0
        if resolved_drugs and resolved_drugs[0]["resolved_smiles"]:
            try:
                from rdkit import Chem
                from rdkit.Chem import Descriptors
                mol = Chem.MolFromSmiles(resolved_drugs[0]["resolved_smiles"])
                if mol:
                    avg_alogp = Descriptors.MolLogP(mol)
                    avg_mw = Descriptors.MolWt(mol)
            except Exception:
                pass

        pk_params = self._patient_pk.compute_pk_params(patient, avg_alogp, avg_mw)
        patient_vec = self._patient_pk.encode(patient, avg_alogp, avg_mw)
        efficacy_multiplier = self._patient_pk.patient_efficacy_multiplier(patient, avg_alogp)

        # 4. Model inference
        drug_t = torch.FloatTensor(combined_drug_vec).unsqueeze(0).to(self._device)
        protein_t = torch.FloatTensor(protein_vec).unsqueeze(0).to(self._device)
        patient_t = torch.FloatTensor(patient_vec).unsqueeze(0).to(self._device)

        raw_pred = self._model.predict(drug_t, protein_t, patient_t)
        chembl_prior = self._chembl_potency_prior(pathogen_input, resolved_drugs)

        # 5. Apply patient PK adjustment to efficacy
        base_efficacy = raw_pred["efficacy_score"]
        if chembl_prior:
            # Direct known-target evidence should calibrate the neural fallback,
            # especially when the user enters a named drug and known target.
            coverage = float(chembl_prior["covered_ratio"])
            base_efficacy = min(1.0, (coverage * chembl_prior["score"]) + ((1.0 - coverage) * base_efficacy))
        patient_adjusted_efficacy = min(1.0, base_efficacy * efficacy_multiplier)

        # 6. Confidence interval (simplified: wider for text-mode descriptions)
        uncertainty = 0.08 if protein_mode == "fasta" else 0.18
        ci_low = max(0.0, patient_adjusted_efficacy - uncertainty)
        ci_high = min(1.0, patient_adjusted_efficacy + uncertainty)

        # 7. Clinical recommendation
        recommendation = self._generate_recommendation(
            patient_adjusted_efficacy, raw_pred["toxicity_class"], patient, pk_params
        )

        mechanism = self._infer_mechanism_breakdown(pathogen_input, resolved_drugs)

        elapsed = time.time() - t0

        return {
            "efficacy": {
                "base_score": round(base_efficacy, 4),
                "patient_adjusted_score": round(patient_adjusted_efficacy, 4),
                "patient_adjusted_percent": round(patient_adjusted_efficacy * 100, 1),
                "confidence_interval": [round(ci_low * 100, 1), round(ci_high * 100, 1)],
                "predicted_pic50": raw_pred["predicted_pic50"],
                "predicted_ic50_nM": raw_pred["predicted_ic50_nM"],
                "efficacy_multiplier": efficacy_multiplier,
                "chembl_prior": chembl_prior,
            },
            "toxicity": {
                "class": raw_pred["toxicity_class"],
                "probabilities": raw_pred["toxicity_probabilities"],
            },
            "pathogen": {
                "input_mode": protein_mode,
                "embedding_dim": int(protein_vec.shape[0]),
            },
            "drugs": resolved_drugs,
            "patient_pk": {
                "bioavailability": pk_params["bioavailability"],
                "half_life_h": pk_params["half_life_h"],
                "clearance_L_h": pk_params["clearance_L_h"],
                "volume_of_distribution_L": pk_params["volume_of_distribution_L"],
                "factors": pk_params["factors"],
            },
            "mechanism": mechanism,
            "recommendation": recommendation,
            "inference_time_ms": round(elapsed * 1000, 1),
            "model_trained": True,
        }

    def _generate_recommendation(self, efficacy: float, toxicity: str, patient: PatientProfile, pk: dict) -> dict:
        """Generate plain-English clinical recommendation."""
        efficacy_pct = efficacy * 100

        if efficacy_pct >= 75:
            eff_text = "Strong efficacy predicted"
            eff_emoji = "✅"
        elif efficacy_pct >= 50:
            eff_text = "Moderate efficacy predicted"
            eff_emoji = "⚠️"
        elif efficacy_pct >= 25:
            eff_text = "Low efficacy — consider alternatives"
            eff_emoji = "⚠️"
        else:
            eff_text = "Poor efficacy — this combination is unlikely to work"
            eff_emoji = "❌"

        tox_notes = []
        if patient.gfr < 45:
            tox_notes.append("Reduce dosage by 40% due to reduced kidney function (GFR < 45)")
        if patient.gfr < 30:
            tox_notes.append("Consider renal dose adjustment or alternative drug")
        if patient.age > 70:
            tox_notes.append("Start at 50–75% of standard dose due to age-related clearance reduction")
        if patient.ast > 80 or patient.alt > 80:
            tox_notes.append("Monitor liver enzymes closely — elevated baseline hepatotoxicity risk")
        if toxicity in ["Moderate", "Severe"]:
            tox_notes.append(f"High molecular lipophilicity may cause {toxicity.lower()} systemic toxicity")
        if "ckd" in [c.lower() for c in patient.comorbidities]:
            tox_notes.append("CKD detected: verify drug is not nephrotoxic")

        half_life_h = pk["half_life_h"]
        if half_life_h < 6:
            dosing = "3-4 times daily"
        elif half_life_h < 12:
            dosing = "twice daily"
        elif half_life_h < 24:
            dosing = "once daily"
        else:
            dosing = f"every {int(half_life_h / 24)} days"

        return {
            "summary": f"{eff_emoji} {eff_text}",
            "efficacy_interpretation": eff_text,
            "suggested_dosing_frequency": dosing,
            "dosage_adjustment_notes": tox_notes if tox_notes else ["No special adjustments required for this patient profile"],
            "monitoring": [
                "Monitor CBC, liver function tests (LFT) at weeks 2, 4, 8",
                "Check drug levels if narrow therapeutic index",
                "Assess clinical response at week 4",
            ],
        }

    def model_status(self) -> dict:
        trained = os.path.exists(MODEL_PATH)
        stats = {}
        if os.path.exists(STATS_PATH):
            with open(STATS_PATH) as f:
                stats = json.load(f)
        validation_mse = stats.get("best_val_loss")
        if validation_mse is not None:
            validation_mse = round(float(validation_mse), 6)
        last_trained = None
        if trained:
            try:
                last_trained = datetime.fromtimestamp(os.path.getmtime(MODEL_PATH), tz=timezone.utc).isoformat()
            except Exception:
                last_trained = None
        return {
            "trained": trained,
            "model_path": MODEL_PATH,
            "training_samples": stats.get("training_samples"),
            "validation_mse": validation_mse,
            "last_trained": last_trained,
            "training_stats": stats,
            "device": self._device,
            "protein_encoder": getattr(self._protein_encoder, "_backend", "unknown"),
        }


def predict_drug_efficacy(pathogen_input: str, drugs: list[dict], patient: dict) -> dict:
    """Convenience function for one-off predictions."""
    predictor = DTIPredictor.get_instance()
    return predictor.predict(pathogen_input, drugs, patient)
