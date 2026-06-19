#!/usr/bin/env bash
# Stop the Llama Vision Worker daemon.
set -euo pipefail

PIDFILE="/tmp/llama_worker.pid"
PORT="${LFX_LLAMA_PORT:-18766}"

if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping Llama worker (PID $OLD_PID) …"
        kill "$OLD_PID" 2>/dev/null || true
        for i in $(seq 1 10); do
            if ! kill -0 "$OLD_PID" 2>/dev/null; then break; fi
            sleep 1
        done
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "Force killing Llama worker …"
            kill -9 "$OLD_PID" 2>/dev/null || true
        fi
    fi
    rm -f "$PIDFILE"
fi

STALE_PID=$(lsof -t -i ":$PORT" 2>/dev/null || true)
if [ -n "$STALE_PID" ]; then
    echo "Cleaning up process on port $PORT …"
    kill -9 "$STALE_PID" 2>/dev/null || true
fi

# Also kill llama-server instances
pkill -f "llama-server.*Qwen3.5" 2>/dev/null || true

echo "Llama worker stopped."
