# Persian OCR — خط‌خوان

Extract Persian (Farsi) text from images with a focus on handwriting accuracy. Upload an image, review the preview and extracted text, then download an Excel file.

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | React + Vite + TypeScript (`front/`) |
| Backend | FastAPI + Ollama Vision (Nasta'liq) + Paddle/EasyOCR fallback (`back/`) |
| Database | PostgreSQL |
| Design skill | `design-taste-frontend` (taste-skill) |

## Prerequisites

- Python 3.9+
- Node.js 22+ (24 recommended)
- PostgreSQL 16 (local Homebrew install works)

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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

First launch downloads EasyOCR Persian models (can take a few minutes).

## Frontend

```bash
cd front
npm install
npm run dev
```

Open http://localhost:5173 — API calls proxy to port 8000.

## OCR accuracy notes

Optimized for **deceased-list documents** (Persian / Nasta'liq):

Extracted fields per person:
- نام متوفی (final valid name)
- کد ملی
- نام پدر
- علت فوت
- پزشک معالج

Pipeline:
1. Vision OCR (`qwen2.5vl:3b`) prompted specifically for deceased lists
2. Name resolution: if readings are similar, show similarity % and keep one final valid name
3. Persian normalization + ≥80% confidence floor
4. Excel export of structured deceased records

```bash
brew services start ollama
ollama pull qwen2.5vl:3b
```

