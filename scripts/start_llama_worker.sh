#!/usr/bin/env bash
# Start the Llama Vision Worker daemon — pre-loads Qwen3.5-2B-VL via llama.cpp.
# Usage: ./scripts/start_llama_worker.sh [--port PORT] [--api-port API_PORT]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

PORT="${LFX_LLAMA_PORT:-18766}"
API_PORT="${LFX_LLAMA_API_PORT:-18080}"
HOST="${LFX_LLAMA_HOST:-127.0.0.1}"
PIDFILE="/tmp/llama_worker.pid"
LOGFILE="/tmp/llama_worker.log"

MODEL="${LFX_LLAMA_MODEL:-/media/1004vmw/code/llama.cpp/models/Qwen3.5-2B-Q4_0.gguf}"
MMPROJ="${LFX_LLAMA_MMPROJ:-/media/1004vmw/code/llama.cpp/models/mmproj-F16.gguf}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --api-port) API_PORT="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        --mmproj) MMPROJ="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Validate model files
if [ ! -f "$MODEL" ]; then echo "Model not found: $MODEL"; exit 1; fi
if [ ! -f "$MMPROJ" ]; then echo "MMProj not found: $MMPROJ"; exit 1; fi

### GPU check ###
if command -v nvidia-smi &>/dev/null; then
    _GPU_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
    if [ -n "$_GPU_FREE" ] && [ "$_GPU_FREE" -lt 3000 ] 2>/dev/null; then
        echo "⚠️  GPU free: ${_GPU_FREE}MiB (need >3GB for VL model)"
    else
        echo "GPU free: ${_GPU_FREE:-?}MiB"
    fi
fi

# Kill existing worker if any
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping existing Llama worker (PID $OLD_PID) …"
        kill "$OLD_PID" 2>/dev/null || true
        sleep 2
    fi
    rm -f "$PIDFILE"
fi

# Kill any stale process on the port
STALE_PID=$(lsof -t -i ":$PORT" 2>/dev/null || true)
if [ -n "$STALE_PID" ]; then
    kill -9 "$STALE_PID" 2>/dev/null || true
    sleep 1
fi

echo "Starting Llama worker on $HOST:$PORT (API :$API_PORT) …"
echo "Model: $MODEL"
echo "MMProj: $MMPROJ"
echo "Logs: $LOGFILE"

.venv/bin/python << PYLAUNCHER
import subprocess, sys, time, os, socket

logfile = "$LOGFILE"
host = "$HOST"
port = int($PORT)
api_port = int($API_PORT)
model = "$MODEL"
mmproj = "$MMPROJ"
pidfile = "$PIDFILE"

log = open(logfile, 'w')
proc = subprocess.Popen(
    [sys.executable, 'src/bundles/llama/llama_worker_server.py',
     '--host', host, '--port', str(port),
     '--api-port', str(api_port),
     '--model', model, '--mmproj', mmproj],
    stdout=log,
    stderr=subprocess.STDOUT,
    stdin=subprocess.DEVNULL,
    close_fds=True,
    start_new_session=True,
)

with open(pidfile, 'w') as f:
    f.write(str(proc.pid))
print(f"Worker PID: {proc.pid}", flush=True)

# Wait for ready (up to 180s)
for i in range(180):
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
