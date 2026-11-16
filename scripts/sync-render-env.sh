#!/usr/bin/env bash
# Print env vars to paste into Render → persian-ocr-api → Environment (never commit secrets).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/back/.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a
FRONT_URL="${FRONT_URL:-https://front-sigma-dun.vercel.app}"
echo "Set on Render (Web Service persian-ocr-api, root: back):"
echo "  DATABASE_URL=<Neon pooled URL from Vercel persian-ocr-db or Neon console>"
echo "  CURSOR_API_KEY=${CURSOR_API_KEY:-<from Cursor dashboard>}"
echo "  SESSION_SECRET=${SESSION_SECRET:-<random>}"
echo "  AUTH_USERNAME=${AUTH_USERNAME:-}"
echo "  AUTH_PASSWORD=${AUTH_PASSWORD:-}"
echo "  CORS_ORIGINS=${CORS_ORIGINS:-},${FRONT_URL}"
echo "  COOKIE_CROSS_SITE=1"
echo "  OCR_USE_CURSOR=1"
echo "  OCR_FAST=1"
echo ""
echo "Then update front/vercel.json rewrites destination to https://<your-service>.onrender.com"