"""
DTI Encoders for the Novel Pathogen Drug Efficacy Predictor

Protein Encoder:
  - Mode A: FASTA protein sequence → ESM-2 650M → 480-dim embedding
  - Mode B: Text description → keyword extraction → ChEMBL protein family lookup → ESM-2

Drug Encoder:
  - Mode A: SMILES string → RDKit ECFP4 (2048-bit) + 200 physicochemical descriptors
  - Mode B: Drug name → ChEMBL SQLite lookup → SMILES → Mode A
"""

from __future__ import annotations

import os
import re
import sqlite3
import warnings
from pathlib import Path
from typing import Optional

import numpy as np

# Suppress verbose warnings from ESM
warnings.filterwarnings("ignore", category=UserWarning)

# ──────────────────────────────────────────────
# 1. Drug Encoder  (RDKit → 2248-dim vector)
# ──────────────────────────────────────────────

class DrugEncoder:
    """
    Encodes a drug from either SMILES or name into a fixed-length vector.
    Combines:
      - 2048-bit ECFP4 Morgan fingerprint
      - 200 RDKit molecular descriptors
    Total: 2248-dim float32 vector
    """

    CHEMBL_DB = str(Path(__file__).resolve().parents[3] / "chembl_37" / "chembl_37_sqlite" / "chembl_37.db")

    # ChEMBL occasionally has approved drugs without a canonical_smiles row.
    # Provide narrowly-scoped fallbacks for known demo-critical compounds.
    _MANUAL_SMILES_BY_NAME = {
        "carboplatin": "N.N.[O-]C(=O)C(=O)[O-].N.N.[Pt+2]",
        "paraplatin": "N.N.[O-]C(=O)C(=O)[O-].N.N.[Pt+2]",
    }
    _MANUAL_SMILES_BY_CHEMBL_ID = {
        "CHEMBL1351": "N.N.[O-]C(=O)C(=O)[O-].N.N.[Pt+2]",  # Carboplatin
    }

    def __init__(self):
        self._conn: Optional[sqlite3.Connection] = None
        self._setup_rdkit()

    def _setup_rdkit(self):
        try:
            from rdkit.Chem import rdFingerprintGenerator, Descriptors

            self._mfp_gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
            self._descriptor_fns = [func for name, func in Descriptors._descList if not name.startswith("fr_")]
            if not self._descriptor_fns:
                raise RuntimeError("RDKit descriptor table is empty")
        except Exception as exc:
            raise RuntimeError(f"RDKit initialization failed: {exc}") from exc

    def _connect_chembl(self) -> Optional[sqlite3.Connection]:
        if self._conn is None:
            db = os.path.abspath(self.CHEMBL_DB)
            if os.path.exists(db):
                self._conn = sqlite3.connect(db, check_same_thread=False)
        return self._conn

    def lookup_smiles(self, drug_name: str) -> Optional[str]:
        """Look up SMILES by drug name in local ChEMBL 37 database."""
        if not drug_name or not drug_name.strip():
            return None

        query = drug_name.strip()
        normalized = re.sub(r"[^a-z0-9]+", "", query.lower())
        if normalized in self._MANUAL_SMILES_BY_NAME:
            return self._MANUAL_SMILES_BY_NAME[normalized]

        conn = self._connect_chembl()
        if conn is None:
            return None
        cur = conn.cursor()
        # Try exact match first
        cur.execute("""
            SELECT cs.canonical_smiles
            FROM molecule_dictionary md
            JOIN compound_structures cs ON md.molregno = cs.molregno
            WHERE UPPER(md.pref_name) = ?
            LIMIT 1
        """, (query.upper(),))
        row = cur.fetchone()
        if row:
            return row[0]
        # Fuzzy synonym match
        cur.execute("""
            SELECT cs.canonical_smiles
            FROM molecule_dictionary md
            JOIN compound_structures cs ON md.molregno = cs.molregno
            JOIN molecule_synonyms ms ON md.molregno = ms.molregno
            WHERE UPPER(ms.synonyms) LIKE ?
            LIMIT 1
        """, (f"%{query.upper()}%",))
        row = cur.fetchone()
        if row:
            return row[0]

        # If ChEMBL has the molecule record but no structure row, recover via
        # a small curated fallback keyed by CHEMBL ID.
        cur.execute("""
            SELECT md.chembl_id
            FROM molecule_dictionary md
            WHERE UPPER(md.pref_name) = ?
            LIMIT 1
        """, (query.upper(),))
        row = cur.fetchone()
        if row and row[0] in self._MANUAL_SMILES_BY_CHEMBL_ID:
            return self._MANUAL_SMILES_BY_CHEMBL_ID[row[0]]

        cur.execute("""
            SELECT md.chembl_id
            FROM molecule_dictionary md
            JOIN molecule_synonyms ms ON md.molregno = ms.molregno
            WHERE UPPER(ms.synonyms) LIKE ?
            LIMIT 1
        """, (f"%{query.upper()}%",))
        row = cur.fetchone()
        if row and row[0] in self._MANUAL_SMILES_BY_CHEMBL_ID:
            return self._MANUAL_SMILES_BY_CHEMBL_ID[row[0]]

        return None

    def encode_smiles(self, smiles: str) -> np.ndarray:
        """Encode a SMILES string into a 2248-dim vector."""
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES string: {smiles}")

        # ECFP4 fingerprint (2048-bit)
        fp = self._mfp_gen.GetFingerprint(mol)
        fp_arr = np.array(fp, dtype=np.float32)

        # Molecular descriptors (200-dim)
        desc_vals = [func(mol) for func in self._descriptor_fns]
        if len(desc_vals) < 200:
            desc_vals.extend([0.0] * (200 - len(desc_vals)))
        else:
            desc_vals = desc_vals[:200]
        desc_arr = np.array(desc_vals, dtype=np.float64)
        desc_arr = np.nan_to_num(desc_arr, nan=0.0, posinf=1e6, neginf=-1e6)
        # Clip extreme values
        desc_arr = np.clip(desc_arr, -1e5, 1e5)
        desc_arr = desc_arr.astype(np.float32)

        return np.concatenate([fp_arr, desc_arr])

    def encode(self, smiles_or_name: str) -> tuple[np.ndarray, str, Optional[str]]:
        """
        Encode a drug. Auto-detects if input is SMILES or name.
        Returns: (embedding, resolved_smiles, drug_name_if_looked_up)
        """
        # Detect SMILES vs name
        is_smiles = any(c in smiles_or_name for c in ['(', ')', '=', '#', '@', '[', ']', '/', '\\'])
        smiles = smiles_or_name if is_smiles else None
        name = None

        if not is_smiles:
            smiles = self.lookup_smiles(smiles_or_name)
            name = smiles_or_name
            if smiles is None:
                raise ValueError(f"Drug '{smiles_or_name}' not found in ChEMBL 37")

        embedding = self.encode_smiles(smiles)
        return embedding, smiles, name


# ──────────────────────────────────────────────
# 2. Protein Encoder  (ESM-2 → 480-dim)
# ──────────────────────────────────────────────

# Virus/bacteria family keyword map → representative protein signatures
PATHOGEN_KEYWORD_MAP = {
    "influenza": ["Hemagglutinin", "Neuraminidase", "RNA-directed RNA polymerase"],
    "coronavirus": ["Spike glycoprotein", "RNA-directed RNA polymerase", "Main protease"],
    "dengue": ["Envelope protein", "NS5 RNA-directed RNA polymerase", "NS3"],
    "zika": ["Envelope protein E", "NS5", "NS2B-NS3 protease"],
    "hiv": ["Reverse transcriptase", "Integrase", "Protease"],
    "ebola": ["Glycoprotein", "RNA-directed RNA polymerase L"],
    "herpes": ["DNA polymerase", "Thymidine kinase", "Glycoprotein B"],
    "malaria": ["Dihydrofolate reductase", "Falcipain-2", "Merozoite surface protein 1"],
    "tuberculosis": ["RNA polymerase", "InhA", "KatG"],
    "bacteria": ["Peptidoglycan", "RNA polymerase beta", "DNA gyrase"],
    "mrsa": ["Penicillin-binding protein 2a", "DNA gyrase", "Sortase A"],
    "e. coli": ["DNA gyrase", "Topoisomerase IV", "Dihydropteroate synthase"],
}

DESCRIPTION_PHRASE_MAP = {
    "spike glycoprotein": ["coronavirus", "influenza"],
    "enveloped rna virus": ["coronavirus", "influenza", "dengue"],
    "positive-sense single-stranded rna": ["coronavirus", "dengue", "zika"],
    "negative-sense rna": ["influenza", "ebola"],
    "dna virus": ["herpes"],
    "bacterial": ["bacteria", "e. coli", "mrsa"],
    "mycobacter": ["tuberculosis"],
    "protozoa": ["malaria"],
}


def protein_kmer_embedding(sequence: str, k: int = 3, dim: int = 1280) -> np.ndarray:
    """
    Fast protein representation used by the DTI training pipeline.

    The first DTI checkpoint was trained on this hashed k-mer representation, so
    inference should use the same representation unless the model is retrained on
    ESM embeddings.
    """
    import hashlib

    amino_acids = "ACDEFGHIKLMNPQRSTVWY"
    seq = sequence.upper()
    vec = np.zeros(dim, dtype=np.float32)
    for idx in range(len(seq) - k + 1):
        kmer = seq[idx:idx + k]
        if all(aa in amino_acids for aa in kmer):
            bucket = int(hashlib.md5(kmer.encode()).hexdigest(), 16) % dim
            vec[bucket] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


class ProteinEncoder:
    """
    Encodes a protein into a 480-dim ESM-2 embedding.

    Mode A (FASTA sequence): ESM-2 650M → 480-dim average pooling
    Mode B (text description): keyword → ChEMBL protein lookup → ESM-2
    """

    ESM_MODEL = "facebook/esm2_t33_650M_UR50D"
    EMBEDDING_DIM = 1280  # ESM-2 650M output dim per token

    CHEMBL_DB = str(Path(__file__).resolve().parents[3] / "chembl_37" / "chembl_37_sqlite" / "chembl_37.db")

    def __init__(self, device: str = "cuda", backend: str | None = None):
        self._model = None
        self._tokenizer = None
        self._device = device
        self._backend = (backend or os.environ.get("CTS_DTI_PROTEIN_ENCODER", "kmer")).lower()
        self._conn: Optional[sqlite3.Connection] = None
        self._loaded = False

    def load(self):
        """Lazily load ESM-2 model (downloads ~2.5GB on first use)."""
        if self._loaded:
            return
        print(f"[ProteinEncoder] Loading ESM-2 650M model on {self._device}...")
        from transformers import EsmModel, EsmTokenizer
        import torch

        self._tokenizer = EsmTokenizer.from_pretrained(self.ESM_MODEL)
        self._model = EsmModel.from_pretrained(self.ESM_MODEL)
        self._model.eval()
        if self._device == "cuda":
            if torch.cuda.is_available():
                self._model = self._model.cuda()
            else:
                self._device = "cpu"
        self._loaded = True
        print(f"[ProteinEncoder] ESM-2 loaded. VRAM used: ~2.5GB")

    def _connect_chembl(self) -> Optional[sqlite3.Connection]:
        if self._conn is None:
            db = os.path.abspath(self.CHEMBL_DB)
            if os.path.exists(db):
                self._conn = sqlite3.connect(db, check_same_thread=False)
        return self._conn

    def _embed_sequence(self, sequence: str) -> np.ndarray:
        """Embed a single protein sequence with ESM-2, returns 1280-dim vector."""
        if self._backend == "kmer":
            return protein_kmer_embedding(sequence)

        import torch
        self.load()

        # Truncate to 1022 tokens (ESM-2 max length)
        sequence = sequence[:1022]

        inputs = self._tokenizer(
            sequence, return_tensors="pt", truncation=True, max_length=1024
        )
        if self._device == "cuda":
            inputs = {k: v.cuda() for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self._model(**inputs)

        # Mean pool over sequence length (exclude CLS and EOS tokens)
        hidden = outputs.last_hidden_state[0, 1:-1, :]  # (L-2, 1280)
        embedding = hidden.mean(dim=0).cpu().numpy()    # (1280,)
        return embedding.astype(np.float32)

    def encode_sequence(self, fasta_sequence: str) -> np.ndarray:
        """
        Encode from FASTA sequence.
        Handles multi-record FASTA (takes first protein or averages all).
        """
        # Parse FASTA: strip header lines starting with '>'
        lines = fasta_sequence.strip().split('\n')
        sequences = []
        current = []
        for line in lines:
            if line.startswith('>'):
                if current:
                    sequences.append(''.join(current))
                current = []
            else:
                current.append(line.strip())
        if current:
            sequences.append(''.join(current))

        if not sequences:
            # Plain sequence, no FASTA headers
            sequences = [re.sub(r'[^ACDEFGHIKLMNPQRSTVWY]', '', fasta_sequence.upper())]

        sequences = [s for s in sequences if len(s) >= 10]
        if not sequences:
            raise ValueError("No valid amino acid sequence found in FASTA input")

        # Average embeddings across all protein sequences (e.g., for multi-protein virus)
        embeddings = [self._embed_sequence(s) for s in sequences[:5]]  # cap at 5
        return np.mean(embeddings, axis=0)

    def lookup_sequences_by_keyword(self, keyword: str) -> list[str]:
        """
        Look up representative protein sequences from ChEMBL by keyword search
        on target names. Used for text description mode.
        """
        conn = self._connect_chembl()
        if conn is None:
            return []

        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT cs.sequence
            FROM target_dictionary td
            JOIN target_components tc ON td.tid = tc.tid
            JOIN component_sequences cs ON tc.component_id = cs.component_id
            WHERE (UPPER(td.pref_name) LIKE ? OR UPPER(td.organism) LIKE ?)
              AND cs.sequence IS NOT NULL
              AND LENGTH(cs.sequence) BETWEEN 50 AND 1500
            LIMIT 5
        """, (f"%{keyword.upper()}%", f"%{keyword.upper()}%"))
        return [row[0] for row in cur.fetchall()]

    def _lookup_sequences_for_protein_name(self, protein_name: str) -> list[str]:
        """Resolve a protein label through exact and token-level ChEMBL lookups."""
        sequences = self.lookup_sequences_by_keyword(protein_name)
        if sequences:
            return sequences

        tokens = [token for token in re.findall(r"[A-Za-z0-9]+", protein_name) if len(token) >= 4]
        for token in tokens:
            sequences.extend(self.lookup_sequences_by_keyword(token))
            if len(sequences) >= 5:
                break
        return sequences[:5]

    def encode_text_description(self, description: str) -> np.ndarray:
        """
        Encode from text description (e.g. 'enveloped RNA virus with spike glycoprotein').
        Uses keyword matching to find representative protein sequences, then embeds them.
        """
        description_lower = description.lower()

        # Find matching keywords
        matched_proteins = []
        matched_keywords = []
        for keyword, protein_names in PATHOGEN_KEYWORD_MAP.items():
            if keyword in description_lower:
                matched_keywords.append(keyword)
                for pname in protein_names:
                    seqs = self._lookup_sequences_for_protein_name(pname)
                    matched_proteins.extend(seqs)

        for phrase, keywords in DESCRIPTION_PHRASE_MAP.items():
            if phrase in description_lower:
                matched_keywords.extend(keywords)
                for keyword in keywords:
                    for pname in PATHOGEN_KEYWORD_MAP.get(keyword, []):
                        seqs = self._lookup_sequences_for_protein_name(pname)
                        matched_proteins.extend(seqs)

        # Also try direct keyword search in ChEMBL
        words = re.findall(r'\b[a-z]{4,}\b', description_lower)
        for word in words[:5]:
            seqs = self.lookup_sequences_by_keyword(word)
            matched_proteins.extend(seqs[:2])

        for keyword in matched_keywords:
            if keyword in PATHOGEN_KEYWORD_MAP:
                for pname in PATHOGEN_KEYWORD_MAP[keyword]:
                    seqs = self._lookup_sequences_for_protein_name(pname)
                    matched_proteins.extend(seqs[:1])

        if not matched_proteins:
            raise ValueError(f"No matching ChEMBL protein sequences found for description: {description}")

        # Average embeddings from matched proteins (up to 5)
        embeddings = [self._embed_sequence(s) for s in matched_proteins[:5]]
        result = np.mean(embeddings, axis=0)
        return result

    def encode(self, sequence_or_description: str) -> tuple[np.ndarray, str]:
        """
        Auto-detect whether input is a FASTA sequence or text description.
        Returns: (1280-dim embedding, mode_used)
        """
        stripped = sequence_or_description.strip()

        # FASTA: starts with '>' or contains only amino acid characters
        is_fasta = (
            stripped.startswith('>') or
            re.match(r'^[ACDEFGHIKLMNPQRSTVWY\s*-]{20,}$', stripped.upper())
        )

        if is_fasta:
            return self.encode_sequence(stripped), "fasta"
        else:
            return self.encode_text_description(stripped), "text"
