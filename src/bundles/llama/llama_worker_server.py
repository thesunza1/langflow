"""Llama Vision Worker Server — manages llama.cpp llama-server for VL inference.

Starts llama-server as a managed subprocess with multimodal (vision) support,
pre-loads the model into GPU memory, and provides a TCP JSON-line API for
image captioning / VQA.

Usage:
    python src/bundles/llama/llama_worker_server.py \\
        --host 127.0.0.1 --port 18766 \\
        --model /path/to/qwen.gguf --mmproj /path/to/mmproj.gguf

Protocol (same as OCR worker):
    Request:  {"images": [{"kind": "base64", "data": "<b64>", "file_name": "img.png"}],
               "prompt": "Describe this image", "max_tokens": 512}
    Response: {"ok": true, "results": [{"file": "img.png", "description": "..."}]}
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
import select
import signal
import socket
import socketserver
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

# --------------------------------------------------------------------------- #
# Early environment setup                                                     #
# --------------------------------------------------------------------------- #
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Use project-local model cache if not set
_script_dir = Path(__file__).resolve().parent
_project_root = str(_script_dir.parent.parent)
os.environ.setdefault("HF_HOME", os.path.join(_project_root, "models", "ocr", "hf"))

# --------------------------------------------------------------------------- #
# Logging setup                                                               #
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("llama-worker")

# --------------------------------------------------------------------------- #
# Persistent llama-server subprocess                                          #
# --------------------------------------------------------------------------- #
class _LlamaServerProcess:
    """Manages the llama-server subprocess (starts, monitors, restarts)."""

    def __init__(self, model_path: str, mmproj_path: str, host: str, port: int,
                 ctx_size: int = 10240, n_gpu_layers: int = 99):
        self._model_path = model_path
        self._mmproj_path = mmproj_path
        self._host = host
        self._api_port = port  # HTTP API port for llama-server
        self._ctx_size = ctx_size
        self._n_gpu_layers = n_gpu_layers
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def ensure_alive(self):
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._start()

    def _start(self):
        llama_bin = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "..", "..",
            "llama.cpp", "build", "bin", "llama-server"
        )
        llama_bin = os.path.abspath(llama_bin)

        if not os.path.exists(llama_bin):
            # Fallback: search PATH
            import shutil
            llama_bin = shutil.which("llama-server") or llama_bin

        cmd = [
            llama_bin,
            "--model", self._model_path,
            "--mmproj", self._mmproj_path,
            "--host", self._host,
            "--port", str(self._api_port),
            "--ctx-size", str(self._ctx_size),
            "--n-gpu-layers", str(self._n_gpu_layers),
            "--parallel", "1",
            "--warmup",
            "--image-min-tokens", "1024",
        ]

        logger.info("Starting llama-server: %s", " ".join(str(c) for c in cmd))
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )

    def wait_ready(self, timeout: int = 120) -> bool:
        """Wait until the HTTP API is ready (up to timeout seconds)."""
        for _ in range(timeout):
            try:
                import urllib.request
                resp = urllib.request.urlopen(
                    f"http://{self._host}:{self._api_port}/health",
                    timeout=2
                )
                if resp.status == 200:
                    return True
            except Exception:
                pass
            if self._process and self._process.poll() is not None:
                logger.error("llama-server exited prematurely (code=%s)", self._process.returncode)
                return False
            time.sleep(1)
        return False

    def stop(self):
        with self._lock:
            proc, self._process = self._process, None
            if proc and proc.poll() is None:
                logger.info("Stopping llama-server (PID %s)...", proc.pid)
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

    @property
    def api_url(self) -> str:
        return f"http://{self._host}:{self._api_port}"

# --------------------------------------------------------------------------- #
# Request handler — one connection = one image description                    #
# --------------------------------------------------------------------------- #
class _LlamaRequestHandler(socketserver.StreamRequestHandler):
    """Receives JSON requests, forwards to llama-server API, returns JSON."""

    timeout: int = 600

    def handle(self) -> None:
        try:
            line = self.rfile.readline()
            if not line:
                return
            cfg = json.loads(line.decode("utf-8"))
            response = self._process_request(cfg)
        except json.JSONDecodeError as e:
            response = {"ok": False, "error": f"Invalid JSON: {e}"}
        except Exception as e:
            logger.exception("Request handler error")
            response = {"ok": False, "error": str(e)}

        payload = (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.wfile.write(payload)
            self.wfile.flush()
        except BrokenPipeError:
            pass

    def _process_request(self, cfg: dict) -> dict:
        images = cfg.get("images", [])
        prompt = cfg.get("prompt", "Describe this image in detail.")
        max_tokens = cfg.get("max_tokens", 512)
        temperature = cfg.get("temperature", 0.3)

        if not images:
            return {"ok": False, "error": "No images provided"}

        server = self.server._llama_server  # type: ignore[attr-defined]
        api_url = server.api_url

        results = []
        for item in images:
            kind = item.get("kind", "")
            name = item.get("file_name", "image")

            if kind == "base64" and item.get("data"):
                img_b64 = item["data"]
            elif kind == "file" and item.get("path"):
                try:
                    with open(item["path"], "rb") as f:
                        img_b64 = base64.b64encode(f.read()).decode()
                except Exception as e:
                    results.append({"file": name, "error": f"File read error: {e}", "description": ""})
                    continue
            else:
                results.append({"file": name, "error": "No valid image data", "description": ""})
                continue

            # Call llama-server OpenAI-compatible /v1/chat/completions
            description = self._call_llama_api(api_url, img_b64, prompt, max_tokens, temperature)
            results.append({"file": name, "description": description, "error": None})

        return {"ok": True, "results": results}

    def _call_llama_api(self, api_url: str, img_b64: str, prompt: str,
                        max_tokens: int, temperature: float) -> str:
        import urllib.request

        payload = {
            "model": "qwen",
            "messages": [
                {
                    "role": "system",
                    "content": "Reply concisely without reasoning. Output only the answer.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        req = urllib.request.Request(
            f"{api_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        msg = result["choices"][0]["message"]
        content = msg.get("content", "") or ""
        reasoning = msg.get("reasoning_content", "") or ""
        # Qwen3.5 sometimes puts answer in reasoning_content when content is empty
        return content or reasoning

# --------------------------------------------------------------------------- #
# Threaded TCP server                                                         #
# --------------------------------------------------------------------------- #
class ThreadedLlamaServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, llama_server: _LlamaServerProcess):
        self._llama_server = llama_server
        super().__init__(server_address, RequestHandlerClass)

# --------------------------------------------------------------------------- #
# CLI entry point                                                             #
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Llama Vision Worker Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default="127.0.0.1", help="TCP API host")
    parser.add_argument("--port", type=int, default=18766, help="TCP API port (for component communication)")
    parser.add_argument("--api-port", type=int, default=18080, help="llama-server HTTP port")
    parser.add_argument("--model", required=True, help="Path to GGUF model file")
    parser.add_argument("--mmproj", required=True, help="Path to multimodal projection GGUF")
    parser.add_argument("--ctx-size", type=int, default=10240, help="Context size (tokens)")
    parser.add_argument("--n-gpu-layers", type=int, default=99, help="GPU layers")
    args = parser.parse_args()

    # Start llama-server
    llama_proc = _LlamaServerProcess(
        model_path=args.model,
        mmproj_path=args.mmproj,
        host=args.host,
        port=args.api_port,
        ctx_size=args.ctx_size,
        n_gpu_layers=args.n_gpu_layers,
    )
    llama_proc.ensure_alive()

    logger.info("Waiting for llama-server to be ready...")
    if not llama_proc.wait_ready(timeout=180):
        logger.error("llama-server failed to start")
        sys.exit(1)
    logger.info("llama-server ready on %s", llama_proc.api_url)

    # Start TCP server
    server = ThreadedLlamaServer(
        (args.host, args.port),
        _LlamaRequestHandler,
        llama_server=llama_proc,
    )
    logger.info("Llama Worker ready on %s:%s", args.host, args.port)

    # Handle shutdown
    def _handle_signal(signum, frame):
        logger.info("Received signal %s, shutting down...", signum)
        server.shutdown()
        llama_proc.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        server.serve_forever()
    finally:
        llama_proc.stop()

if __name__ == "__main__":
    main()
