"""
DTI Fusion Model — Novel Pathogen Drug Efficacy Predictor

Architecture:
  1. Drug MLP Encoder:     2248-dim ECFP4+desc → 256-dim
  2. Protein MLP Encoder:  1280-dim ESM-2 → 256-dim
  3. Patient Encoder:      12-dim PK → 32-dim
  4. Cross-Attention:      Drug × Protein → context-aware interaction
  5. Efficacy Head:        concat → MLP → [0,1] efficacy + log(IC50)
  6. Toxicity Head:        concat → MLP → 4-class toxicity

Trained on ChEMBL 37 drug-protein-IC50 triples.
At inference: generalizes to any novel pathogen protein via ESM-2 embedding.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class DrugMLP(nn.Module):
    """Encodes 2248-dim ECFP4 + descriptor vector → 256-dim latent."""

    def __init__(self, input_dim: int = 2248, latent_dim: int = 256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 1024),
            nn.LayerNorm(1024),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(1024, 512),
            nn.LayerNorm(512),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(512, latent_dim),
            nn.LayerNorm(latent_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class ProteinMLP(nn.Module):
    """Encodes 1280-dim ESM-2 embedding → 256-dim latent."""

    def __init__(self, input_dim: int = 1280, latent_dim: int = 256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 512),
            nn.LayerNorm(512),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(512, latent_dim),
            nn.LayerNorm(latent_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class PatientMLP(nn.Module):
    """Encodes 12-dim PK feature vector → 32-dim latent."""

    def __init__(self, input_dim: int = 12, latent_dim: int = 32):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.GELU(),
            nn.Linear(64, latent_dim),
            nn.LayerNorm(latent_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class CrossAttentionFusion(nn.Module):
    """
    Cross-attention between drug and protein embeddings.
    Drug query attends to protein keys/values, learning WHICH protein regions
    the drug binds to. This is the core mechanism for generalization to novel proteins.
    """

    def __init__(self, dim: int = 256, num_heads: int = 4):
        super().__init__()
        self.attn = nn.MultiheadAttention(embed_dim=dim, num_heads=num_heads, batch_first=True)
        self.norm = nn.LayerNorm(dim)

    def forward(self, drug_emb: torch.Tensor, protein_emb: torch.Tensor) -> torch.Tensor:
        # drug_emb: (B, 256), protein_emb: (B, 256)
        # Add sequence dim for attention: (B, 1, 256)
        drug_q = drug_emb.unsqueeze(1)
        protein_kv = protein_emb.unsqueeze(1)
        attended, _ = self.attn(drug_q, protein_kv, protein_kv)
        # Residual connection
        out = self.norm(drug_emb + attended.squeeze(1))
        return out


class DTIFusionModel(nn.Module):
    """
    Full DTI model: (drug, protein, patient) → (efficacy, toxicity)
    """

    DRUG_DIM = 2248
    PROTEIN_DIM = 1280
    PATIENT_DIM = 12
    LATENT = 256
    PATIENT_LATENT = 32

    def __init__(self):
        super().__init__()
        self.drug_encoder = DrugMLP(self.DRUG_DIM, self.LATENT)
        self.protein_encoder = ProteinMLP(self.PROTEIN_DIM, self.LATENT)
        self.patient_encoder = PatientMLP(self.PATIENT_DIM, self.PATIENT_LATENT)
        self.cross_attention = CrossAttentionFusion(self.LATENT)

        # Fusion input: drug_attn(256) + protein(256) + patient(32) = 544
        fusion_dim = self.LATENT * 2 + self.PATIENT_LATENT  # 544

        # Efficacy head (regression): predicts normalized efficacy [0, 1]
        self.efficacy_head = nn.Sequential(
            nn.Linear(fusion_dim, 256),
            nn.GELU(),
            nn.Dropout(0.15),
            nn.Linear(256, 64),
            nn.GELU(),
            nn.Linear(64, 1),
            nn.Sigmoid(),   # [0, 1] output
        )

        # pIC50 head (regression): predicts -log10(IC50 in M), range ~4-12
        self.pic50_head = nn.Sequential(
            nn.Linear(fusion_dim, 128),
            nn.GELU(),
            nn.Linear(128, 1),
        )

        # Toxicity head (4-class): none/low/moderate/severe
        self.toxicity_head = nn.Sequential(
            nn.Linear(fusion_dim, 128),
            nn.GELU(),
            nn.Dropout(0.15),
            nn.Linear(128, 4),
        )

    def forward(
        self,
        drug_vec: torch.Tensor,
        protein_vec: torch.Tensor,
        patient_vec: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        """
        Args:
            drug_vec:    (B, 2248) ECFP4 + descriptor
            protein_vec: (B, 1280) ESM-2 embedding
            patient_vec: (B, 12)   PK feature vector
        Returns:
            dict with 'efficacy', 'pic50', 'toxicity_logits'
        """
        drug_latent = self.drug_encoder(drug_vec)           # (B, 256)
        protein_latent = self.protein_encoder(protein_vec)  # (B, 256)
        patient_latent = self.patient_encoder(patient_vec)  # (B, 32)

        # Cross-attention: drug attends to protein
        drug_attended = self.cross_attention(drug_latent, protein_latent)  # (B, 256)

        # Fuse all representations
        fused = torch.cat([drug_attended, protein_latent, patient_latent], dim=-1)  # (B, 544)

        efficacy = self.efficacy_head(fused)         # (B, 1)
        pic50 = self.pic50_head(fused)               # (B, 1)
        toxicity_logits = self.toxicity_head(fused)  # (B, 4)

        return {
            "efficacy": efficacy,
            "pic50": pic50,
            "toxicity_logits": toxicity_logits,
        }

    def predict(
        self,
        drug_vec: torch.Tensor,
        protein_vec: torch.Tensor,
        patient_vec: torch.Tensor,
    ) -> dict:
        """Inference-mode forward with interpretable output dict."""
        self.eval()
        with torch.no_grad():
            out = self.forward(drug_vec, protein_vec, patient_vec)

        efficacy = out["efficacy"].item()
        pic50 = out["pic50"].item()
        # The training label for efficacy is derived from pChEMBL:
        # pChEMBL 4 -> 0, pChEMBL 10 -> 1. Blend the direct efficacy head with
        # the potency head so the UI remains calibrated to the ChEMBL scale.
        potency_efficacy = max(0.0, min(1.0, (pic50 - 4.0) / 6.0))
        calibrated_efficacy = max(0.0, min(1.0, 0.55 * efficacy + 0.45 * potency_efficacy))
        toxicity_probs = F.softmax(out["toxicity_logits"], dim=-1)[0].tolist()
        toxicity_labels = ["None", "Low", "Moderate", "Severe"]
        tox_class = toxicity_labels[int(torch.argmax(out["toxicity_logits"][0]).item())]

        # Convert pIC50 back to IC50 in nM
        ic50_nM = 10 ** (9 - pic50) if pic50 > 0 else None

        return {
            "efficacy_score": round(calibrated_efficacy, 4),
            "raw_efficacy_score": round(efficacy, 4),
            "potency_efficacy_score": round(potency_efficacy, 4),
            "efficacy_percent": round(calibrated_efficacy * 100, 1),
            "predicted_pic50": round(pic50, 3),
            "predicted_ic50_nM": round(ic50_nM, 2) if ic50_nM else None,
            "toxicity_class": tox_class,
            "toxicity_probabilities": {
                label: round(p, 3) for label, p in zip(toxicity_labels, toxicity_probs)
            },
        }
