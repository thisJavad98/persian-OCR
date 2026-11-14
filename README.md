# Persian OCR — خط‌خوان

AI-only extraction of exact text (words + sentences) from any image: print, handwriting, Nasta'liq, tables, forms.

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | React + Vite + TypeScript (`front/`) |
| Backend | FastAPI (`back/`) |
| OCR | **AI vision only** — OpenAI GPT-4o / Claude / Gemini (+ Ollama fallback) |
| Database | PostgreSQL (job history) |
| Export | Excel (`.xlsx`) and Word (`.docx`) |

## How OCR works

1. **Extract** — strong vision model transcribes the full page  
2. **Verify** — second AI pass proofreads the draft against the same image (`OCR_AI_VERIFY=1`)  
3. **Cross-check** — if a second cloud key exists, another model re-reads and merges (`OCR_AI_CROSS_CHECK=1`)

No classic OCR engines, no row-slice UI, no death-list-only mode.

## Prerequisites

- Python 3.9+
- Node.js 22+ (24 recommended)
- PostgreSQL 16
- At least one of:
  - `OPENAI_API_KEY` (recommended: `gpt-4o`)
  - `ANTHROPIC_API_KEY`
  - `GEMINI_API_KEY`
  - or local [Ollama](https://ollama.com) with a vision model (`qwen2.5vl:3b`)

## Database

```bash
createdb persian_ocr
```

Copy `back/.env.example` to `back/.env` and set your AI key(s).

## Backend

```bash
cd back
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Useful env vars:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | Cloud vision providers |
| `AI_PROVIDER` | `auto` / `openai` / `anthropic` / `gemini` / `ollama` |
| `OCR_AI_VERIFY` | Second AI proofread pass (`1` default) |
| `OCR_AI_CROSS_CHECK` | Extra provider merge when a 2nd key exists |
| `VISION_OCR_MODEL` | Ollama fallback model |

## Frontend

```bash
cd front
npm install
npm run dev
```

Open http://localhost:5173 — Vite proxies `/api` to port 8000.

## API

- `POST /api/ocr/upload` — image in, AI transcript out (`text`, `lines`, `words`, `sentences`)
- `GET /api/ocr/{id}/excel` / `/word` — exports
- `GET /api/health` — provider readiness
