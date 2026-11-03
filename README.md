# Persian OCR — خط‌خوان

Extract Persian (Farsi / Nasta'liq) text from images: deceased-list fields, per-word detection, Iranian name validation, then Excel and Word export.

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | React + Vite + TypeScript (`front/`) |
| Backend | FastAPI (`back/`) |
| OCR | Ollama Vision + **Bina 0.2** word OCR + PaddleOCR-fa + EasyOCR |
| Names / Word polish | Iranian lexicon + optional Ollama text models |
| Database | PostgreSQL |
| Export | Excel (`.xlsx`) and Word (`.docx`) |

## Prerequisites

- Python 3.9+
- Node.js 22+ (24 recommended)
- PostgreSQL 16 (local Homebrew install works)
- [Ollama](https://ollama.com) for vision / name AI (optional but recommended)
- ~2 GB disk for OCR models (Bina bootstrap + Paddle/EasyOCR)

## Database

```bash
createdb persian_ocr
```

Copy `back/.env.example` to `back/.env` and adjust `DATABASE_URL` if needed.

## Backend

```bash
cd back
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install Bina detector + recognizer under models/bina-0.2/
# Without HF_TOKEN: public PP-OCRv6 bootstrap (works; not the gated Bina fine-tune)
python scripts/download_bina.py --bootstrap-only

# With Hugging Face access to Reza2kn/Bina-0.2-Roryh:
# export HF_TOKEN=hf_...
# python scripts/download_bina.py

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# or: ./run.sh
```

Useful env vars (see `back/.env.example`):

| Variable | Purpose |
| --- | --- |
| `BINA_MODEL_DIR` | Path to Bina models (default `models/bina-0.2`) |
| `BINA_DEVICE` | `cpu` or `gpu:0` |
| `OCR_MIN_CONFIDENCE` | Confidence floor (default `0.80`) |
| `VISION_OCR_MODEL` | Ollama VL model (default `qwen2.5vl:3b`) |
| `WORD_AI` / `NAME_AGENT_AI` | Set to `0` to disable AI polish / name agent |

## Frontend

```bash
cd front
npm install
npm run dev
```

Open http://localhost:5173 — Vite proxies `/api` to port 8000.

## OCR pipeline

Optimized for **deceased-list documents** (Persian / Nasta'liq):

1. Image enhance / upscale
2. **Vision OCR** (`qwen2.5vl:3b`) for structured deceased rows when Ollama is up
3. **Bina 0.2** page OCR for text regions and per-word tokens/boxes
4. **PaddleOCR-fa** + **EasyOCR** for Persian letter text (avoids digit-only noise from weak recognizers)
5. Iranian name agent (lexicon + optional LLM) → final names, similarity %, valid words
6. Optional Word AI polish for readable `.docx` body
7. Persist job + row image slices; export Excel / Word

Extracted fields per person:

- نام متوفی (final validated name)
- کد ملی
- نام پدر
- علت فوت
- پزشک معالج

API surface (main routes):

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | DB + OCR readiness / engine list |
| `POST` | `/api/ocr/upload` | Upload image → OCR job |
| `GET` | `/api/ocr/{id}` | Job JSON (lines, words, records) |
| `GET` | `/api/ocr/{id}/excel` | Download `.xlsx` |
| `GET` | `/api/ocr/{id}/word` | Download `.docx` |

## Ollama (vision / name AI)

```bash
brew services start ollama
ollama pull qwen2.5vl:3b
ollama pull qwen2.5:1.5b   # optional, for name / Word polish
```

Without Ollama, classic OCR engines (Bina + Paddle + Easy) still run; vision and AI polish degrade gracefully.

## Models note

Large weights under `back/models/bina-0.2/` are gitignored. Download them with `back/scripts/download_bina.py` (see `back/models/README.md`). The gated [Bina 0.2 Rizeh](https://huggingface.co/Reza2kn/Bina-0.2-Roryh) fine-tune needs `HF_TOKEN`; otherwise the script installs a public PP-OCRv6 bootstrap labeled `bina-0.2-bootstrap`.
