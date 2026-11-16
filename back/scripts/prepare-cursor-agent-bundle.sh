#!/usr/bin/env bash
# Build-time: download agent once, ship as cursor-agent-bundle.tgz (fits Vercel bundle limits).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/cursor-runtime"
TGZ="$ROOT/cursor-agent-bundle.tgz"
URL="${CURSOR_AGENT_PKG_URL:-https://downloads.cursor.com/lab/2026.11.13-eacade1/linux/x64/agent-cli-package.tar.gz}"

if [[ -f "$TGZ" ]]; then
  echo "prepare-cursor-agent: reuse $TGZ ($(du -sh "$TGZ" | awk '{print $1}'))"
  exit 0
fi

rm -rf "$OUT"
mkdir -p "$OUT"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

echo "prepare-cursor-agent: downloading $URL"
curl -fsSL \
  --connect-timeout 45 \
  --max-time 900 \
  --retry 8 \
  --retry-all-errors \
  --retry-delay 3 \
  -o "$TMP" \
  "$URL"

echo "prepare-cursor-agent: extracting (skip SEA blobs)"
gzip -dc "$TMP" | tar -xf - -C "$OUT" \
  --exclude='dist-package/cursor-agent-sea' \
  --exclude='dist-package/cursor-agent-worker-sea'

if [[ ! -f "$OUT/dist-package/index.js" ]]; then
  echo "prepare-cursor-agent: missing dist-package/index.js" >&2
  exit 1
fi

echo "prepare-cursor-agent: packing tgz"
tar -czf "$TGZ" -C "$OUT" .
rm -rf "$OUT"
echo "prepare-cursor-agent: ok $(du -sh "$TGZ" | awk '{print $1}')"