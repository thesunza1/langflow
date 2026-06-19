#!/usr/bin/env bash
# qstart_dev — Development Mode (Hot Reload)
# Start workers, backend (uvicorn --reload), and frontend (Vite HMR).
set -euo pipefail

cd "$(dirname "$0")"

VENV="${UV_PROJECT_ENVIRONMENT:-/tmp/langflow-venv}"
OCR_PORT="${LFX_OCR_WORKER_PORT:-18765}"
LLAMA_PORT="${LFX_LLAMA_PORT:-18766}"
PORT="${PORT:-7860}"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  qstart_dev — development mode (hot reload)"
echo "═══════════════════════════════════════════════════════"

# Ensure bundles are installed
"$VENV/bin/pip" install -q -e src/bundles/paddleocr -e src/bundles/llama 2>/dev/null || true

# ── Workers ──────────────────────────────────────────────
if ! lsof -i ":$OCR_PORT" >/dev/null 2>&1; then
    echo "  [0] Starting OCR worker..."
    bash scripts/start_ocr_worker.sh > /dev/null 2>&1 &
else
    echo "  [0] OCR worker already running on port $OCR_PORT"
fi

if ! lsof -i ":$LLAMA_PORT" >/dev/null 2>&1; then
    echo "  [0] Starting Llama worker..."
    bash scripts/start_llama_worker.sh > /dev/null 2>&1 &
else
    echo "  [0] Llama worker already running on port $LLAMA_PORT"
fi

# ── Backend ──────────────────────────────────────────────
echo "  [1] Starting backend (uvicorn --reload) on port $PORT..."
"$VENV/bin/python" -m uvicorn \
    --factory langflow.main:create_app \
    --host 0.0.0.0 --port "$PORT" \
    --reload --loop asyncio --workers 1 &
BACKEND_PID=$!

# ── Frontend ─────────────────────────────────────────────
echo "  [2] Starting frontend (Vite HMR) on port 3000..."
cd src/frontend
npx vite --host 0.0.0.0 --port 3000 &
FRONTEND_PID=$!
cd ../..

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Frontend : http://localhost:3000"
echo "  Backend  : http://localhost:$PORT"
echo "  (còn nhớ AGENTS.md)"
echo "═══════════════════════════════════════════════════════"
echo "  Press Ctrl+C to stop all services"
echo ""

# Trap to clean up on exit
cleanup() {
    echo ""
    echo "Stopping services..."
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT INT TERM

# Wait for either to exit
wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
