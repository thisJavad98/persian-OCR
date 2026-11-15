# Deploy: Vercel (front) + Neon (DB) + API (Render or Vercel Go)

## وضعیت فعلی

| بخش | آدرس / وضعیت |
|-----|----------------|
| Frontend | https://front-sigma-dun.vercel.app (Vercel · پروژه `front`) |
| API | پروژه Vercel `persian-ocr-api` — Root Directory = `back` — بعد از push روی `main` دیپلوی یا `vercel deploy` |
| Secrets | `scripts/sync-vercel-api-env.sh` از `back/.env` (بدون `localhost` در DATABASE_URL) |
| Neon | `DATABASE_URL` را در Vercel → persian-ocr-api → Environment Variables بگذارید |

# Deploy: Vercel (front) + Neon (DB) + API (Render or Vercel Go)

## Neon (Postgres)

1. [console.neon.tech](https://console.neon.tech) → New project `persian-ocr`
2. Copy **connection string** (`postgres://...?sslmode=require`)
3. Set as `DATABASE_URL` on the API host (Render or Vercel)

Handwriting samples are stored as blobs in Postgres (no disk on serverless).

## API (Render — recommended for OCR)

OCR needs `cursor-agent` and runtimes up to several minutes. **Render** fits better than Vercel serverless.

1. Connect GitHub repo on [render.com](https://render.com)
2. New **Blueprint** from `render.yaml` or Web Service: root `back`, start `./server`
3. Environment (from local `back/.env`, **never commit secrets**):

| Variable | Notes |
|----------|--------|
| `DATABASE_URL` | Neon connection string |
| `CURSOR_API_KEY` | Cursor API key |
| `SESSION_SECRET` | random 32+ chars |
| `AUTH_USERNAME` / `AUTH_PASSWORD` | login |
| `CORS_ORIGINS` | `https://your-app.vercel.app` |

## Frontend (Vercel)

```bash
cd front
vercel login
vercel link
```

Set **Environment**:

- `VITE_API_URL` = your API origin (e.g. `https://persian-ocr-api.onrender.com`)

Update `front/vercel.json` `rewrites` destination to the same API URL, or rely on `VITE_API_URL` only.

```bash
vercel --prod
```

## Local vs production

- Local: no `DATABASE_URL` → SQLite in `back/.data/`
- Production: `DATABASE_URL` → Neon Postgres

## Vercel Go (experimental API)

Deploy from `back/` with Vercel Go preset (`cmd/server/main.go` listens on `PORT`).

Limits: max duration ~300s (Hobby), ephemeral disk, `cursor-agent` must install on build. Prefer Render for reliable OCR.