# Persian OCR — خط‌خوان

Stateless AI text extraction from images (print, handwriting, Nasta'liq, forms). **Nothing is stored** — no database, no saved uploads.

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | React + Vite + TypeScript (`front/`) |
| Backend | Go (`back/`) |
| OCR | **Cursor Agent** (`composer-2.5` by default) |

## How it works

1. User selects an image (preview stays in the browser only).
2. Server runs Cursor on a **temporary** JPEG under `back/.scratch/` (deleted right after OCR).
3. JSON result is shown in the UI.
4. **Download** (Excel/Word) only if the user clicks — built in memory from the result; nothing persisted.

Requires `cursor-agent` logged in (`cursor-agent login`) or `CURSOR_API_KEY`.

## Prerequisites

- Go 1.22+
- Node.js 22+ (24 recommended)
- `cursor-agent` on `PATH`

## Backend

```bash
cd back
go run ./cmd/server
```

| Variable | Purpose |
| --- | --- |
| `CURSOR_OCR_MODEL` | Model id (default `composer-2.5`) |
| `CURSOR_OCR_TIMEOUT` | Agent timeout in seconds |
| `CURSOR_API_KEY` | Optional API key |
| `OCR_MAX_IMAGE_SIDE` | Max image longest side for OCR |

## Frontend

```bash
cd front
npm install
npm run dev
```

http://localhost:5173 — Vite proxies `/api` to port 8000.

## API

- `POST /api/ocr/upload` — image in, OCR JSON out (not stored)
- `POST /api/ocr/export/excel` / `export/word` — JSON body in, file bytes out
- `GET /api/health`