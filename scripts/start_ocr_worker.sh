#!/usr/bin/env bash
# Start the OCR Worker daemon — pre-loads PaddleOCR for fast concurrent OCR.
# Usage: ./scripts/start_ocr_worker.sh [--port PORT]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

PORT="${LFX_OCR_WORKER_PORT:-18765}"
HOST="${LFX_OCR_WORKER_HOST:-127.0.0.1}"

# Model cache directory (project-local, survives restarts)
export PADDLE_PDX_CACHE_HOME="${LFX_OCR_CACHE_DIR:-$(pwd)/models/ocr/paddlex}"
export HF_HOME="${LFX_OCR_HF_CACHE_DIR:-$(pwd)/models/ocr/hf}"
export TOKENIZERS_PARALLELISM="false"

PIDFILE="/tmp/ocr_worker.pid"
LOGFILE="/tmp/ocr_worker.log"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --preload-layout) shift ;;  # kept for API compatibility
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Kill existing worker if any
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping existing OCR worker (PID $OLD_PID) …"
        kill "$OLD_PID" 2>/dev/null || true
        sleep 2
    fi
    rm -f "$PIDFILE"
fi

# Kill any stale process on the port
STALE_PID=$(lsof -t -i ":$PORT" 2>/dev/null || true)
if [ -n "$STALE_PID" ]; then
    echo "Killing stale process on port $PORT (PID $STALE_PID) …"
    kill -9 "$STALE_PID" 2>/dev/null || true
    sleep 2
fi

# Auto-detect GPU: use CUDA only if >2.5GB free, otherwise CPU
_OCR_PYTHON="${LFX_OCR_PYTHON:-python3}"
if command -v nvidia-smi &>/dev/null; then
    _GPU_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
    if [ -n "$_GPU_FREE" ] && [ "$_GPU_FREE" -ge 2500 ] 2>/dev/null; then
        echo "GPU free: ${_GPU_FREE}MiB — using CUDA"
    else
        echo "GPU free: ${_GPU_FREE:-0}MiB (need >2.5GB) — forcing CPU"
        export CUDA_VISIBLE_DEVICES=""
    fi
else
    echo "No GPU detected — using CPU"
    export CUDA_VISIBLE_DEVICES=""
fi
echo "Starting OCR worker on $HOST:$PORT …"
echo "Logs: $LOGFILE"
echo "Model cache: $PADDLE_PDX_CACHE_HOME"

# Launch via Python subprocess with start_new_session=True so the worker
# survives after this script exits (immune to SIGHUP / orphan-process kill).
.venv/bin/python << PYLAUNCHER
import subprocess, sys, time, os, socket

logfile = "$LOGFILE"
host = "$HOST"
port = int($PORT)
pidfile = "$PIDFILE"

env = os.environ.copy()
env["PADDLE_PDX_CACHE_HOME"] = "$PADDLE_PDX_CACHE_HOME"
env["HF_HOME"] = "$HF_HOME"

log = open(logfile, 'w')
proc = subprocess.Popen(
    ["python3", 'src/bundles/paddleocr/ocr_worker_server.py',
     '--host', host, '--port', str(port),
     '--preload-lang', 'vi'],
    stdout=log,
    stderr=subprocess.STDOUT,
    stdin=subprocess.DEVNULL,
    close_fds=True,
    start_new_session=True,
    env=env,
)

with open(pidfile, 'w') as f:
    f.write(str(proc.pid))
print(f"Worker PID: {proc.pid}", flush=True)

# Wait for ready (up to 30s since models are pre-cached)
for i in range(30):
    try:
        s = socket.create_connection((host, port), timeout=1)
        s.close()
        print(f"Worker ready on {host}:{port} (PID {proc.pid})", flush=True)
        break
    except (OSError, ConnectionRefusedError):
        if proc.poll() is not None:
            print(f"Worker failed (exit={proc.returncode})", flush=True)
            log.flush()
            with open(logfile) as lf:
                for line in list(lf)[-20:]:
                    print(f"  {line.rstrip()}")
            sys.exit(1)
        time.sleep(1)
else:
    print("Timed out waiting for worker", flush=True)
    proc.kill()
    sys.exit(1)
PYLAUNCHER
