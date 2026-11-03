# Bina 0.2 model directory

Expected layout (matches [Reza2kn/Bina-0.2-Roryh](https://huggingface.co/Reza2kn/Bina-0.2-Roryh)):

```text
detector/     # text detection (PP-OCRv6_medium_det)
inference/    # Persian text recognition (Bina fine-tune)
```

Download / refresh:

```bash
cd back
export HF_TOKEN=hf_...   # required for the gated Bina recognizer
python scripts/download_bina.py
```

Without a token, `download_bina.py --bootstrap-only` installs the public detector and a PP-OCRv6 medium recognizer so the page-OCR + word-split pipeline still runs.
