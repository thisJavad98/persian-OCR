#!/usr/bin/env bash
# Sync secrets from back/.env into Vercel project (persian-ocr-api). Never commit .env.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/back/.env"
export PATH="$HOME/.local/bin:$PATH"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

cd "$ROOT/back"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

FRONT_URL="${FRONT_URL:-https://front-sigma-dun.vercel.app}"
export CORS_ORIGINS="${CORS_ORIGINS},${FRONT_URL}"

push_env() {
  local name="$1"
  local val="$2"
  [[ -z "$val" ]] && return 0
  printf '%s' "$val" | vercel env add "$name" production --force --yes 2>/dev/null || \
    printf '%s' "$val" | vercel env add "$name" production --force 2>/dev/null || true
}

if [[ -n "${DATABASE_URL:-}" ]] && [[ "$DATABASE_URL" != *localhost* ]] && [[ "$DATABASE_URL" != *127.0.0.1* ]]; then
  push_env DATABASE_URL "$DATABASE_URL"
else
  echo "Skip DATABASE_URL (set Neon URL in Vercel dashboard for production handwriting DB)."
fi

for key in CURSOR_API_KEY SESSION_SECRET AUTH_USERNAME AUTH_PASSWORD \
  OCR_USE_CURSOR CURSOR_OCR_MODEL CURSOR_OCR_TIMEOUT OCR_FAST COOKIE_CROSS_SITE CORS_ORIGINS; do
  push_env "$key" "${!key-}"
done
push_env COOKIE_CROSS_SITE "1"
echo "Done. Redeploy API from repo root: vercel deploy --environment production --yes"