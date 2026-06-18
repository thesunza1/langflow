#!/usr/bin/env bash
# Start the OCR Worker daemon — pre-loads PaddleOCR for fast concurrent OCR.
# Usage: ./scripts/start_ocr_worker.sh [--port PORT] [--preload-layout]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

PORT="${LFX_OCR_WORKER_PORT:-18765}"
HOST="${LFX_OCR_WORKER_HOST:-127.0.0.1}"
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

echo "Starting OCR worker on $HOST:$PORT …"
echo "Logs: $LOGFILE"

# Launch via Python subprocess with start_new_session=True so the worker
# survives after this script exits (immune to SIGHUP / orphan-process kill).
.venv/bin/python << PYLAUNCHER
import subprocess, sys, time, os, socket

logfile = "$LOGFILE"
host = "$HOST"
port = int($PORT)
pidfile = "$PIDFILE"

log = open(logfile, 'w')
proc = subprocess.Popen(
    [sys.executable, 'src/bundles/paddleocr/ocr_worker_server.py',
     '--host', host, '--port', str(port),
     '--preload-lang', 'ch'],
    stdout=log,
    stderr=subprocess.STDOUT,
    stdin=subprocess.DEVNULL,
    close_fds=True,
    start_new_session=True,
)

with open(pidfile, 'w') as f:
    f.write(str(proc.pid))
print(f"Worker PID: {proc.pid}", flush=True)

# Wait for ready (up to 180s for first-time model download)
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