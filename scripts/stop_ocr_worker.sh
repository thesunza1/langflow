#!/usr/bin/env bash
# Stop the OCR Worker daemon.
set -euo pipefail

PIDFILE="/tmp/ocr_worker.pid"
PORT="${LFX_OCR_WORKER_PORT:-18765}"

# Kill by PID file (clean shutdown via SIGTERM)
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping OCR worker (PID $OLD_PID) …"
        kill "$OLD_PID" 2>/dev/null || true
        # Wait up to 5s for graceful shutdown
        for i in $(seq 1 5); do
            if ! kill -0 "$OLD_PID" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        # Force kill if still alive
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "Force killing OCR worker …"
            kill -9 "$OLD_PID" 2>/dev/null || true
        fi
    fi
    rm -f "$PIDFILE"
fi

# Also kill any process on the port
STALE_PID=$(lsof -t -i ":$PORT" 2>/dev/null || true)
if [ -n "$STALE_PID" ]; then
    echo "Cleaning up process on port $PORT …"
    kill -9 "$STALE_PID" 2>/dev/null || true
fi

echo "OCR worker stopped."
