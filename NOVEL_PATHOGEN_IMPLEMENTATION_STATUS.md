# Novel Pathogen Drug Efficacy Predictor - Implementation Status

## What is implemented

- A full DTI inference pipeline exists in `src/cts/dti/`.
- The predictor loads a trained checkpoint from `artifacts/dti/dti_model.pt` and returns:
  - efficacy score and confidence interval
  - toxicity class and probabilities
  - patient PK summary
  - recommendation and monitoring guidance
  - mechanism breakdown
- The protein encoder supports:
  - FASTA sequences
  - text descriptions that resolve to ChEMBL target families through keyword lookup
- The drug encoder supports:
  - SMILES input
  - ChEMBL drug-name lookup to SMILES
  - RDKit fingerprints and descriptors
- The trainer builds from the local ChEMBL-derived parquet dataset and writes a checkpoint plus training stats.
- The frontend includes:
  - landing-page CTA to open the novel pathogen analyzer directly
  - main navigation entry for Novel Pathogen
  - analyzer view with efficacy, toxicity, mechanism, PK/PD, and recommendation tabs
- The backend includes:
  - `/dti/analyze`
  - `/dti/model-status`
  - `/dti/drug-lookup`

## What was validated

- The ChEMBL database path now resolves correctly from the module location.
- The trainer runs from the repo root and from direct script execution.
- The DTI model retrains successfully on the local dataset.
- The predictor loads the retrained checkpoint and returns a structured result.
- The frontend builds successfully with Vite after the latest UI changes.

## Current trained artifacts

- Model checkpoint: `artifacts/dti/dti_model.pt`
- Training stats: `artifacts/dti/training_stats.json`
- Cached fingerprints: `data/training/drug_fingerprints.npz`

## Remaining work to fully match the original scientific ambition

- Replace training-time k-mer proxies with full ESM-based training embeddings or a staged distillation scheme.
- Expand the text-description resolver so broader pathogen descriptions map to richer, validated protein families.
- Replace heuristic mechanism summaries with real explainability:
  - substructure attribution for drugs
  - target-region attribution for pathogen proteins
  - calibrated confidence estimates
- Add explicit model calibration and external holdout evaluation.
- Add automated tests for:
  - FASTA path
  - text-description path
  - drug-name lookup
  - mechanism output
  - frontend rendering of the new analyzer tab
- Decide whether the simulator core should consume DTI outputs through a `dti_override` integration path.

## Notes

- The implementation is now operational end to end, but the current mechanism layer is deterministic and inference-driven rather than a true biological explainability system.
- The trained model is real and reproducible, but it is still a first-pass predictor and not a clinical decision tool.