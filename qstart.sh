#!/usr/bin/env bash
# qstart — Production Launch
# Build frontend, start workers, start production server.
set -euo pipefail

cd "$(dirname "$0")"

VENV="${UV_PROJECT_ENVIRONMENT:-/tmp/langflow-venv}"
OCR_PORT="${LFX_OCR_WORKER_PORT:-18765}"
LLAMA_PORT="${LFX_LLAMA_PORT:-18766}"
PORT="${PORT:-7860}"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  qstart — production launch"
echo "═══════════════════════════════════════════════════════"

# Ensure bundles are installed
"$VENV/bin/pip" install -q -e src/bundles/paddleocr -e src/bundles/llama 2>/dev/null || true

# Start workers (if not already running)
if ! lsof -i ":$OCR_PORT" >/dev/null 2>&1; then
    echo "  Starting OCR worker..."
    bash scripts/start_ocr_worker.sh > /dev/null 2>&1 &
fi
if ! lsof -i ":$LLAMA_PORT" >/dev/null 2>&1; then
    echo "  Starting Llama worker..."
    bash scripts/start_llama_worker.sh > /dev/null 2>&1 &
fi

# Build frontend
echo "  Building frontend..."
cd src/frontend
CI='' npm run build 2>&1 | tail -3
cd ../..

# Copy build to backend
rm -rf src/backend/base/langflow/frontend
cp -r src/frontend/build/. src/backend/base/langflow/frontend

# Wait for OCR worker
echo "  Waiting for workers..."
for i in $(seq 1 30); do
    if lsof -i ":$OCR_PORT" >/dev/null 2>&1; then
        echo "  Workers ready (${i}s)"
        break
    fi
    sleep 1
done

# Start production server
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Open http://localhost:$PORT"
echo "  (còn nhớ AGENTS.md)"
echo "═══════════════════════════════════════════════════════"
UV_PROJECT_ENVIRONMENT="$VENV" LANGFLOW_SKIP_AUTH_AUTO_LOGIN=true "$VENV/bin/langflow" run \
    --frontend-path src/backend/base/langflow/frontend \
    --port "$PORT" --host 0.0.0.0
