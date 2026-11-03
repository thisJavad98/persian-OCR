# OCR models

## Bina 0.2 (Persian word / page OCR)

Place the [Bina 0.2 Rizeh](https://huggingface.co/Reza2kn/Bina-0.2-Roryh) release under `bina-0.2/`:

```text
bina-0.2/
  detector/     # PP-OCRv6_medium_det (bundled in the Bina release)
  inference/    # Bina Persian recognizer
```

### Download

From `back/`:

```bash
# Hugging Face token required for Reza2kn/Bina-0.2-Roryh (gated/private to anonymous clients)
export HF_TOKEN=hf_...
python scripts/download_bina.py
```

Without `HF_TOKEN`, the script installs the public detector and a PP-OCRv6 medium recognizer bootstrap so the Bina page-OCR pipeline still runs. After you authenticate, re-run the script to replace `inference/` with the real Bina fine-tune.

Config (see `.env.example`):

- `BINA_MODEL_DIR=models/bina-0.2`
- `BINA_DEVICE=cpu` (or `gpu:0`)
- `BINA_SCORE_THRESHOLD=0.0`
