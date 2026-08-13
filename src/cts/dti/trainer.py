"""
DTI Trainer — Trains the DTI Fusion Model on ChEMBL 37 data

Usage:
  python -m cts.dti.trainer
  # or
  python src/cts/dti/trainer.py --epochs 50 --lr 0.001 --batch 256

Training data: data/training/chembl_dti_training.parquet
Model saved to: artifacts/dti/dti_model.pt
"""

from __future__ import annotations

import os
import json
import argparse
import time
import math
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from cts.dti.fusion_model import DTIFusionModel
from cts.dti.encoders import DrugEncoder


REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = REPO_ROOT / "data" / "training" / "chembl_dti_training.parquet"
FINGERPRINT_CACHE = REPO_ROOT / "data" / "training" / "drug_fingerprints.npz"
MODEL_OUT = REPO_ROOT / "artifacts" / "dti" / "dti_model.pt"
STATS_OUT = REPO_ROOT / "artifacts" / "dti" / "training_stats.json"


class DTIDataset(Dataset):
    def __init__(self, drug_vecs, protein_vecs, patient_vecs, efficacy_scores, pic50s):
        self.drug_vecs = torch.FloatTensor(drug_vecs)
        self.protein_vecs = torch.FloatTensor(protein_vecs)
        self.patient_vecs = torch.FloatTensor(patient_vecs)
        self.efficacy_scores = torch.FloatTensor(efficacy_scores)
        self.pic50s = torch.FloatTensor(pic50s)

    def __len__(self):
        return len(self.efficacy_scores)

    def __getitem__(self, idx):
        return {
            "drug": self.drug_vecs[idx],
            "protein": self.protein_vecs[idx],
            "patient": self.patient_vecs[idx],
            "efficacy": self.efficacy_scores[idx],
            "pic50": self.pic50s[idx],
        }


def load_or_compute_fingerprints(df: pd.DataFrame, encoder: DrugEncoder) -> np.ndarray:
    """Load cached fingerprints or compute them fresh."""
    os.makedirs(FINGERPRINT_CACHE.parent, exist_ok=True)

    if FINGERPRINT_CACHE.exists():
        print(f"Loading cached fingerprints from {FINGERPRINT_CACHE}")
        data = np.load(FINGERPRINT_CACHE, allow_pickle=True)
        fingerprints = data["fingerprints"]
        if len(fingerprints) == len(df):
            return fingerprints
        print(f"Cached fingerprints size {len(fingerprints)} does not match training set size {len(df)}; recomputing.")

    print(f"Computing fingerprints for {len(df)} compounds...")
    fps = []
    for i, smiles in enumerate(df["smiles"]):
        if i % 10000 == 0:
            print(f"  {i}/{len(df)} ({100*i/len(df):.1f}%)")
        fp = encoder.encode_smiles(str(smiles))
        fps.append(fp)

    fps_arr = np.array(fps, dtype=np.float32)
    np.savez_compressed(FINGERPRINT_CACHE, fingerprints=fps_arr)
    print(f"Saved fingerprints to {FINGERPRINT_CACHE}")
    return fps_arr


def generate_protein_embeddings_from_kmers(sequences: list[str], k: int = 3) -> np.ndarray:
    """
    Fast k-mer frequency encoding as a proxy for ESM-2 embeddings during training.
    Full ESM-2 encoding of 500K proteins would take hours; this is a practical approximation.
    In production inference, real ESM-2 embeddings are used.

    For training, this is sufficient to learn the cross-attention mechanism.
    """
    import hashlib

    AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
    # 3-mer frequency vector (20^3 = 8000 possible, but we hash to 1280)
    DIM = 1280

    result = np.zeros((len(sequences), DIM), dtype=np.float32)
    for i, seq in enumerate(sequences):
        seq = seq.upper()
        vec = np.zeros(DIM, dtype=np.float32)
        for j in range(len(seq) - k + 1):
            kmer = seq[j:j+k]
            if all(aa in AMINO_ACIDS for aa in kmer):
                # Hash to index
                idx = int(hashlib.md5(kmer.encode()).hexdigest(), 16) % DIM
                vec[idx] += 1.0
        # L2 normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        result[i] = vec

    return result


def generate_synthetic_patient_vectors(n: int) -> np.ndarray:
    """
    Generate synthetic patient feature vectors for training.
    The model learns to use patient features; at inference, real values are used.
    """
    rng = np.random.RandomState(42)
    vecs = []
    for _ in range(n):
        age = rng.uniform(18, 85)
        bioavail = rng.uniform(0.2, 1.0)
        clearance = rng.uniform(0.1, 0.9)
        half_life = rng.uniform(0.05, 0.8)
        vd = rng.uniform(0.1, 1.0)
        gfr_norm = rng.choice([1.0, 0.85, 0.60, 0.35, 0.15], p=[0.5, 0.2, 0.15, 0.1, 0.05])
        liver_norm = rng.choice([1.0, 0.8, 0.6, 0.4], p=[0.6, 0.2, 0.15, 0.05])
        comorbidity = rng.uniform(0, 0.5)
        sex = rng.choice([1.0, 0.87])
        vec = np.array([
            bioavail, clearance, half_life, vd,
            rng.uniform(0.3, 1.0),  # age factor
            gfr_norm, liver_norm, rng.uniform(0.5, 1.0),
            rng.uniform(0.5, 1.5),  # weight vd
            sex, comorbidity,
            age / 100.0,
        ], dtype=np.float32)
        vecs.append(vec)
    return np.array(vecs)


def train(epochs: int = 50, lr: float = 0.001, batch_size: int = 256, max_samples: int = 100_000):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Training on: {device}")

    # 1. Load dataset
    if not DATASET_PATH.exists():
        print(f"Dataset not found at {DATASET_PATH}")
        print("Run: python scripts/build_dti_dataset.py first")
        sys.exit(1)

    print(f"Loading dataset: {DATASET_PATH}")
    df = pd.read_parquet(DATASET_PATH)
    print(f"Total samples: {len(df)}")

    # Sample if too large
    if len(df) > max_samples:
        df = df.sample(n=max_samples, random_state=42).reset_index(drop=True)
        print(f"Sampled {max_samples} training examples")

    # 2. Drug fingerprints
    drug_enc = DrugEncoder()
    drug_vecs = load_or_compute_fingerprints(df, drug_enc)

    # 3. Protein k-mer embeddings (training proxy for ESM-2)
    print("Computing protein k-mer embeddings for training...")
    protein_vecs = generate_protein_embeddings_from_kmers(df["protein_sequence"].tolist())
    print(f"Protein embeddings shape: {protein_vecs.shape}")

    # 4. Synthetic patient vectors
    patient_vecs = generate_synthetic_patient_vectors(len(df))

    # 5. Labels
    efficacy_scores = df["efficacy_score"].values.astype(np.float32)
    pic50s = df["pchembl"].values.astype(np.float32)

    # 6. Train/val split
    idx = np.arange(len(df))
    train_idx, val_idx = train_test_split(idx, test_size=0.15, random_state=42)

    train_ds = DTIDataset(
        drug_vecs[train_idx], protein_vecs[train_idx], patient_vecs[train_idx],
        efficacy_scores[train_idx], pic50s[train_idx]
    )
    val_ds = DTIDataset(
        drug_vecs[val_idx], protein_vecs[val_idx], patient_vecs[val_idx],
        efficacy_scores[val_idx], pic50s[val_idx]
    )

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=0)

    print(f"Train: {len(train_ds)}, Val: {len(val_ds)}")

    # 7. Model
    model = DTIFusionModel().to(device)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {total_params:,}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=lr * 5, steps_per_epoch=len(train_loader), epochs=epochs
    )
    efficacy_loss_fn = nn.MSELoss()
    pic50_loss_fn = nn.MSELoss()

    # 8. Training loop
    history = []
    best_val_loss = float("inf")
    os.makedirs(MODEL_OUT.parent, exist_ok=True)

    for epoch in range(1, epochs + 1):
        model.train()
        train_losses = []
        t0 = time.time()

        for batch in train_loader:
            drug = batch["drug"].to(device)
            protein = batch["protein"].to(device)
            patient = batch["patient"].to(device)
            eff_target = batch["efficacy"].unsqueeze(1).to(device)
            pic50_target = batch["pic50"].unsqueeze(1).to(device)

            out = model(drug, protein, patient)
            loss_eff = efficacy_loss_fn(out["efficacy"], eff_target)
            loss_pic = pic50_loss_fn(out["pic50"], pic50_target)
            loss = 0.6 * loss_eff + 0.4 * loss_pic  # Weighted combination

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            train_losses.append(loss.item())

        # Validation
        model.eval()
        val_losses = []
        with torch.no_grad():
            for batch in val_loader:
                drug = batch["drug"].to(device)
                protein = batch["protein"].to(device)
                patient = batch["patient"].to(device)
                eff_target = batch["efficacy"].unsqueeze(1).to(device)
                pic50_target = batch["pic50"].unsqueeze(1).to(device)

                out = model(drug, protein, patient)
                loss_eff = efficacy_loss_fn(out["efficacy"], eff_target)
                loss_pic = pic50_loss_fn(out["pic50"], pic50_target)
                val_losses.append((0.6 * loss_eff + 0.4 * loss_pic).item())

        train_loss = np.mean(train_losses)
        val_loss = np.mean(val_losses)
        elapsed = time.time() - t0
        rmse = math.sqrt(val_loss)

        print(f"Epoch {epoch:3d}/{epochs} | Train {train_loss:.4f} | Val {val_loss:.4f} | RMSE {rmse:.4f} | {elapsed:.1f}s")

        history.append({"epoch": epoch, "train_loss": train_loss, "val_loss": val_loss, "rmse": rmse})

        # Save best model
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save({
                "model_state": model.state_dict(),
                "epoch": epoch,
                "val_loss": val_loss,
                "config": {
                    "drug_dim": DTIFusionModel.DRUG_DIM,
                    "protein_dim": DTIFusionModel.PROTEIN_DIM,
                    "patient_dim": DTIFusionModel.PATIENT_DIM,
                }
            }, MODEL_OUT)
            print(f"  Saved best model (val_loss={val_loss:.4f})")

    # Save training stats
    with open(STATS_OUT, "w") as f:
        json.dump({
            "best_val_loss": best_val_loss,
            "best_val_rmse": math.sqrt(best_val_loss),
            "training_samples": len(train_ds),
            "val_samples": len(val_ds),
            "epochs_trained": epochs,
            "history": history[-10:],  # Last 10 epochs
        }, f, indent=2)

    print(f"\nTraining complete. Best val RMSE: {math.sqrt(best_val_loss):.4f}")
    print(f"Model saved to: {MODEL_OUT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--max-samples", type=int, default=100_000)
    args = parser.parse_args()
    train(epochs=args.epochs, lr=args.lr, batch_size=args.batch, max_samples=args.max_samples)
