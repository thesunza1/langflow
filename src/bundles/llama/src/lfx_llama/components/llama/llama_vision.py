"""Llama Vision Component — Qwen3.5-2B-VL via llama.cpp for image description.

Follows the same pattern as the OCR Paddle component.
"""

from __future__ import annotations

import json
import logging
import socket
from pathlib import Path

from lfx.custom import Component
from lfx.io import (
    BoolInput,
    DropdownInput,
    FileInput,
    IntInput,
    MultilineInput,
    Output,
    StrInput,
)
from lfx.schema import Message

logger = logging.getLogger(__name__)

LLAMA_WORKER_HOST = "127.0.0.1"
LLAMA_WORKER_PORT = 18766
LLAMA_TIMEOUT = 300

VALID_EXTENSIONS = ["png", "jpg", "jpeg", "bmp", "tiff", "tif", "webp", "gif", "heic", "heif", "avif"]

class _LlamaTcpClient:
    """Lightweight TCP client for the standalone llama-worker server."""

    def __init__(self, host: str = LLAMA_WORKER_HOST, port: int = LLAMA_WORKER_PORT):
        self._host = host
        self._port = port

    def is_alive(self, timeout: float = 2.0) -> bool:
        try:
            with socket.create_connection((self._host, self._port), timeout=timeout):
                pass
            return True
        except (TimeoutError, OSError):
            return False

    def describe(
        self,
        images_config: list[dict],
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> list[dict]:
        request = {
            "images": images_config,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        payload = json.dumps(request, ensure_ascii=False) + "\n"
        s = socket.create_connection((self._host, self._port), timeout=10)
        try:
            s.settimeout(LLAMA_TIMEOUT)
            s.sendall(payload.encode("utf-8"))
            s.shutdown(socket.SHUT_WR)
            buf = bytearray()
            while True:
                ch = s.recv(1)
                if not ch or ch == b"\n":
                    break
                buf.extend(ch)
        finally:
            s.close()

        if not buf:
            raise RuntimeError("Llama worker returned empty response")
        result = json.loads(buf.decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Unknown error"))
        return result["results"]

_llama_tcp = _LlamaTcpClient()


class LlamaVisionComponent(Component):
    display_name = "Llama Vision"
    description = (
        "Describe images using Qwen3.5-2B-VL via llama.cpp. "
        "Upload images or paste base64-encoded images."
    )
    documentation = "https://huggingface.co/unsloth/Qwen3.5-2B-GGUF"
    trace_type = "tool"
    icon = "eye"
    name = "LlamaVision"

    inputs = [
        FileInput(name="llama_images", display_name="Images", file_types=VALID_EXTENSIONS,
                  info="Upload one or more images.", is_list=True, required=False),
        StrInput(name="llama_paste_images", display_name="Paste Images", advanced=True,
                 tool_mode=True, required=False),
        MultilineInput(name="prompt", display_name="Prompt",
                       value="Describe this image in detail.", required=True),
        IntInput(name="max_tokens", display_name="Max Tokens", value=512, advanced=True),
        DropdownInput(name="temperature", display_name="Temperature",
                      options=["0.1", "0.3", "0.5", "0.7", "0.9"],
                      value="0.3", advanced=True),
    ]

    outputs = [
        Output(display_name="Description", name="description",
               method="process_images", types=["Message"]),
    ]

    def _get_images_config(self) -> list[dict]:
        configs = []
        images = getattr(self, "llama_images", None)
        if images:
            if not isinstance(images, list):
                images = [images]
            for img in images:
                if img is None: continue
                path_str = str(img) if not hasattr(img, "path") else str(img.path)
                configs.append({"kind": "file", "path": path_str, "data": None,
                                "file_name": Path(path_str).name})
        paste = getattr(self, "llama_paste_images", None)
        if paste:
            lines = paste.split("\n") if isinstance(paste, str) else [str(paste)]
            for i, b64_str in enumerate(lines):
                b = b64_str.strip()
                if not b: continue
                configs.append({"kind": "base64", "path": None, "data": b,
                                "file_name": f"pasted_image_{i+1}.png"})
        return configs

    def process_images(self) -> Message:
        images_config = self._get_images_config()
        if not images_config:
            raise ValueError("No images provided.")
        prompt = getattr(self, "prompt", "Describe this image in detail.")
        max_tokens = int(getattr(self, "max_tokens", 512))
        temperature = float(getattr(self, "temperature", 0.3))

        try:
            results = _llama_tcp.describe(images_config, prompt, max_tokens, temperature)
        except (TimeoutError, ConnectionError, OSError, RuntimeError) as exc:
            logger.warning("Llama worker failed (%s)", exc)
            raise RuntimeError("Llama vision worker not available. Run: make start_llama_worker") from exc

        parts = []
        for r in results:
            err = r.get("error")
            if err:
                parts.append(f"## {r.get('file', '?')}\n\n*Error: {err}*")
            else:
                parts.append(f"## {r.get('file', 'image')}\n\n{r.get('description', '')}")
        combined = "\n\n---\n\n".join(parts)
        self.status = f"Described {len(images_config)} image(s)"
        return Message(text=combined)
