"""OCR Paddle Component — PaddleOCR + PP-DocLayoutV3 for document OCR to Markdown.

Processes images (upload or paste) through PaddleOCR text detection/recognition
and optional PP-DocLayoutV3 layout analysis, outputting structured Markdown.

PaddlePaddle and PyTorch run in an isolated subprocess (same pattern as Docling's
_CHILD_SCRIPT) to prevent OOM and native-library-state issues in the main process.

Optimization: Persistent worker subprocess keeps models loaded across calls.
"""  # noqa: EXE002

from __future__ import annotations

import atexit
import json
import os
import select
import socket
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

from lfx.custom import Component
from lfx.io import BoolInput, DropdownInput, FileInput, IntInput, Output, StrInput
from lfx.schema import Data, DataFrame, Message

PADDLEOCR_LANG_MAP = {
    "Auto": "ch",
    "chinese": "ch",
    "english": "en",
    "vietnamese": "vi",
    "japanese": "japan",
    "korean": "korean",
    "french": "fr",
    "german": "german",
}

OCR_TIMEOUT_PER_IMAGE = 300


# ------------------------------------------------------------------ #
# Persistent worker process — keeps models loaded across calls.       #
# ------------------------------------------------------------------ #
class _OcrWorkerProcess:
    """Persistent PaddleOCR worker process.

    Keeps PaddleOCR + PP-DocLayoutV3 models loaded in memory across
    multiple OCR calls by running a long-lived subprocess. Spawned
    once on first use; automatically restarted on crash / timeout.
    Communication is line-delimited JSON over stdin/stdout.
    """

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Child script that loops, reading JSON lines from stdin.            #
    # ------------------------------------------------------------------ #
    _CHILD_SCRIPT: str = textwrap.dedent("""\
        import base64, io, json, sys, os
        from pathlib import Path

        os.environ["PP_DEBUG"] = "0"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"

        # Module-level caches (persist across requests in same process)
        _ocr_engine = None
        _ocr_lang = None
        _layout_pipeline = None

        LAYOUT_LABELS = {
            0: "title", 1: "plain_text", 2: "abandon", 3: "figure",
            4: "figure_caption", 5: "table", 6: "table_caption",
            7: "table_footnote", 8: "isolate_formula", 9: "formula_caption",
        }

        def _ensure_ocr(lang):
            global _ocr_engine, _ocr_lang
            if _ocr_engine is not None and _ocr_lang == lang:
                return
            from paddleocr import PaddleOCR
            _ocr_engine = PaddleOCR(use_textline_orientation=True, lang=lang, engine="transformers")
            _ocr_lang = lang

        def _ensure_layout():
            global _layout_pipeline
            if _layout_pipeline is not None:
                return
            from transformers import AutoProcessor, AutoModelForDocumentImageClassification
            import torch
            model_id = "PaddlePaddle/PP-DocLayoutV3_safetensors"
            _layout_pipeline = {
                "model": AutoModelForDocumentImageClassification.from_pretrained(model_id).eval(),
                "processor": AutoProcessor.from_pretrained(model_id),
            }
            if torch.cuda.is_available():
                _layout_pipeline["model"] = _layout_pipeline["model"].cuda()

        def _run_layout_analysis(pil_img):
            if _layout_pipeline is None:
                return []
            try:
                import torch
                inputs = _layout_pipeline["processor"](images=pil_img, return_tensors="pt")
                if torch.cuda.is_available():
                    inputs = {k: v.cuda() for k, v in inputs.items()}
                with torch.no_grad():
                    outputs = _layout_pipeline["model"](**inputs)
                predicted_ids = outputs.logits.argmax(-1).squeeze().tolist()
                if isinstance(predicted_ids, int):
                    predicted_ids = [predicted_ids]
                return [{"category": LAYOUT_LABELS.get(pid, "unknown")} for pid in predicted_ids]
            except Exception as e:
                sys.stderr.write(f"Layout analysis error: {e}\\n")
                return []

        def _process_image(img_data: bytes, img_name: str, use_layout: bool) -> dict:
            try:
                from PIL import Image
                import numpy as np
                pil_img = Image.open(io.BytesIO(img_data)).convert("RGB")
                img_array = np.array(pil_img)
            except Exception as e:
                return {"file": img_name, "error": f"Image load failed: {e}", "markdown": ""}

            try:
                ocr_result = _ocr_engine.ocr(img_array, use_textline_orientation=True)
            except Exception as e:
                return {"file": img_name, "error": f"OCR failed: {e}", "markdown": ""}

            lines_text = []
            if ocr_result:
                for page_result in ocr_result:
                    texts = page_result.get("rec_texts") or []
                    scores = page_result.get("rec_scores") or []
                    polys = page_result.get("rec_polys") or []
                    for i, text in enumerate(texts):
                        confidence = scores[i] if i < len(scores) else 0.0
                        poly = polys[i] if i < len(polys) else None
                        lines_text.append({"text": text, "confidence": confidence, "bbox": poly})

            if use_layout:
                _run_layout_analysis(pil_img)

            md_parts = [f"## {img_name}", ""]
            if not lines_text:
                md_parts.append("*(No text detected)*")
            else:
                lines_text.sort(key=lambda x: (x["bbox"][0][1], x["bbox"][0][0]))
                paragraph = []
                for line in lines_text:
                    text = line["text"].strip()
                    if not text:
                        if paragraph:
                            md_parts.append(" ".join(paragraph))
                            md_parts.append("")
                            paragraph = []
                        continue
                    paragraph.append(text)
                if paragraph:
                    md_parts.append(" ".join(paragraph))
                    md_parts.append("")

            return {
                "file": img_name,
                "markdown": "\\n".join(md_parts).strip(),
                "text_lines": len(lines_text),
                "error": None,
            }

        def _handle_request(cfg):
            images_input = cfg["images"]
            lang = cfg["lang"]
            use_layout = cfg["use_layout"]

            ocr_lang = lang if lang != "Auto" else "ch"
            _ensure_ocr(ocr_lang)

            if use_layout:
                try:
                    _ensure_layout()
                except Exception as e:
                    sys.stderr.write(f"Layout model load failed (continuing without layout): {e}\\n")

            results = []
            for item in images_input:
                kind = item["kind"]
                name = item.get("file_name", "image")
                if kind == "file" and item.get("path"):
                    try:
                        data_bytes = Path(item["path"]).read_bytes()
                    except Exception as e:
                        results.append({"file": name, "error": f"File read error: {e}", "markdown": ""})
                        continue
                elif kind == "base64" and item.get("data"):
                    try:
                        data_bytes = base64.b64decode(item["data"])
                    except Exception as e:
                        results.append({"file": name, "error": f"Base64 decode error: {e}", "markdown": ""})
                        continue
                else:
                    results.append({"file": name, "error": "No valid image data", "markdown": ""})
                    continue
                results.append(_process_image(data_bytes, name, use_layout))

            print(json.dumps({"ok": True, "results": results}))

        def main():
            while True:
                line = sys.stdin.readline()
                if not line:
                    break
                try:
                    cfg = json.loads(line)
                    _handle_request(cfg)
                except Exception as e:
                    print(json.dumps({"ok": False, "error": str(e)}))
                sys.stdout.flush()

        if __name__ == "__main__":
            main()
    """)

    # ------------------------------------------------------------------ #

    def _ensure_alive(self):
        if self._process is None or self._process.poll() is not None:
            self._start()

    def _start(self):
        _env = os.environ.copy()
        _env.setdefault("PADDLE_PDX_CACHE_HOME", os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir, os.pardir, os.pardir, os.pardir, os.pardir, "models", "ocr", "paddlex"))
        _env.setdefault("HF_HOME", os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir, os.pardir, os.pardir, os.pardir, os.pardir, "models", "ocr", "hf"))
        _env.setdefault("TOKENIZERS_PARALLELISM", "false")
        self._process = subprocess.Popen(
            [sys.executable, "-u", "-c", self._CHILD_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_env,
        )

    def _kill(self):
        proc, self._process = self._process, None
        if proc and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass

    def process(self, images_config, lang, use_layout, timeout_per_image, n_images):
        timeout = max(30, timeout_per_image * n_images)
        self._ensure_alive()
        request = {"images": images_config, "lang": lang, "use_layout": use_layout}

        with self._lock:
            self._process.stdin.write(json.dumps(request).encode("utf-8") + b"\n")
            self._process.stdin.flush()
            readable, _, _ = select.select([self._process.stdout], [], [], timeout)
            if not readable:
                self._kill()
                raise TimeoutError(f"OCR processing timed out after {timeout}s.")
            response = self._process.stdout.readline()

        if not response:
            self._kill()
            raise RuntimeError("OCR subprocess died unexpectedly.")

        try:
            payload = json.loads(response.decode("utf-8"))
        except Exception as e:
            self._kill()
            raise RuntimeError(f"Invalid JSON from OCR subprocess: {e}") from e

        if not payload.get("ok"):
            raise RuntimeError(payload.get("error", "Unknown OCR error"))

        return payload.get("results", [])

    def shutdown(self):
        proc, self._process = self._process, None
        if proc and proc.poll() is None:
            try:
                proc.stdin.close()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                    proc.wait()
                except Exception:
                    pass


_ocr_worker = _OcrWorkerProcess()
atexit.register(_ocr_worker.shutdown)


# ------------------------------------------------------------------ #
# TCP client -- connects to an external OCR worker server.           #
# ------------------------------------------------------------------ #


class _OcrTcpClient:
    """Lightweight TCP client for the standalone OCR worker server.

    When the worker server is running (started via
    ``ocr_worker_server.py`` at boot), this client sends requests
    over TCP instead of spawning an embedded subprocess.  This enables
    concurrent OCR calls and keeps models pre-loaded.

    Falls back gracefully to the embedded worker when the server is
    unreachable.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 18765):
        self._host = host
        self._port = port
        self._last_ok: bool | None = None

    def is_alive(self, timeout: float = 2.0) -> bool:
        """Return True iff the TCP server is reachable."""
        try:
            with socket.create_connection((self._host, self._port), timeout=timeout):
                pass
            self._last_ok = True
            return True
        except (TimeoutError, OSError):
            self._last_ok = False
            return False

    def process(
        self,
        images_config: list[dict],
        lang: str,
        use_layout: bool,
        timeout_per_image: int,
        n_images: int,
    ) -> list[dict]:
        """Send an OCR request to the external worker and return results."""
        timeout = max(30, timeout_per_image * n_images)
        request = {
            "images": images_config,
            "lang": lang,
            "use_layout": use_layout,
        }
        payload = json.dumps(request, ensure_ascii=False) + "\n"

        s = socket.create_connection((self._host, self._port), timeout=10)
        try:
            s.settimeout(timeout)
            s.sendall(payload.encode("utf-8"))
            s.shutdown(socket.SHUT_WR)

            # Read response (newline-terminated)
            buf = bytearray()
            while True:
                ch = s.recv(1)
                if not ch or ch == b"\n":
                    break
                buf.extend(ch)
        finally:
            s.close()

        if not buf:
            self._last_ok = False
            raise RuntimeError("OCR worker returned empty response")

        result = json.loads(buf.decode("utf-8"))
        if not result.get("ok"):
            self._last_ok = False
            raise RuntimeError(result.get("error", "Unknown OCR error"))

        return result["results"]


# Module-level singleton
_ocr_tcp = _OcrTcpClient()
_ocr_tcp_available = (
    False
    if os.environ.get("LFX_OCR_WORKER_DISABLE", "").lower() in ("1", "true", "yes")
    else _ocr_tcp.is_alive()
)



# ------------------------------------------------------------------ #
# Component — delegates to persistent worker.                         #
# ------------------------------------------------------------------ #
class OcrPaddleComponent(Component):
    display_name = "OCR Paddle"
    description = (
        "OCR documents using PaddleOCR + PP-DocLayoutV3. "
        "Upload images or paste base64-encoded images. "
        "Outputs structured Markdown with text and layout."
    )
    documentation = "https://github.com/PaddlePaddle/PaddleOCR"
    trace_type = "tool"
    icon = "file-text"
    name = "OcrPaddle"

    VALID_EXTENSIONS = ["png", "jpg", "jpeg", "bmp", "tiff", "tif", "webp", "gif", "heic", "heif", "avif", "jfif", "pjpeg", "pjp"]

    inputs = [
        FileInput(
            name="images",
            display_name="Images",
            file_types=VALID_EXTENSIONS,
            info="Upload one or more images for OCR processing.",
            is_list=True,
            required=False,
        ),
        StrInput(
            name="paste_images",
            display_name="Paste Images",
            info="Alternative: paste base64-encoded image data (one per line). "
            "Used when component is called as a tool.",
            advanced=True,
            tool_mode=True,
            required=False,
        ),
        DropdownInput(
            name="lang",
            display_name="Language",
            options=["Auto", "chinese", "english", "vietnamese", "japanese", "korean", "french", "german"],
            value="vietnamese",
            info="OCR language. 'Auto' tries multiple common languages and picks the best result.",
        ),
        BoolInput(
            name="use_layout",
            display_name="Use Layout Analysis",
            value=False,
            info="Enable PP-DocLayoutV3 for document structure analysis (title, table, figure, etc.).",
            advanced=True,
        ),
        IntInput(
            name="timeout",
            display_name="Timeout (s)",
            value=OCR_TIMEOUT_PER_IMAGE,
            info="Maximum seconds per image.",
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Markdown Output",
            name="markdown_output",
            method="process_images",
            types=["Message"],
        ),
        Output(
            display_name="DataFrame",
            name="dataframe",
            method="process_images_dataframe",
        ),
    ]

    # ------------------------------ Core logic ------------------------------

    def _get_images_config(self) -> list[dict]:
        """Collect all image sources (files + paste) into a uniform config list."""
        configs: list[dict] = []

        # From file uploads
        images = getattr(self, "images", None)
        if images:
            if not isinstance(images, list):
                images = [images]
            for img in images:
                if img is None:
                    continue
                path_str = str(img) if not hasattr(img, "path") else str(img.path)
                configs.append(
                    {
                        "kind": "file",
                        "path": path_str,
                        "data": None,
                        "file_name": Path(path_str).name,
                    }
                )

        # From paste (base64)
        paste = getattr(self, "paste_images", None)
        if paste:
            if isinstance(paste, str):
                paste_lines = [line.strip() for line in paste.split("\n") if line.strip()]
            elif isinstance(paste, list):
                paste_lines = paste
            else:
                paste_lines = [str(paste)]

            for i, b64_str in enumerate(paste_lines):
                configs.append(
                    {
                        "kind": "base64",
                        "path": None,
                        "data": b64_str,
                        "file_name": f"pasted_image_{i + 1}.png",
                    }
                )

        return configs

    def _run_ocr(self, images_config: list[dict]) -> list[dict]:
        """Run OCR -- prefer external TCP worker, fall back to embedded."""
        if not images_config:
            msg = "No images provided. Upload images or paste base64 data."
            raise ValueError(msg)

        # Always try TCP worker first (lazy check on each call).
        # The TCP worker keeps models pre-loaded for fast (~3s) OCR.
        # If the worker wasn't running when the module was imported,
        # _ocr_tcp_available may be False, but the worker could have
        # started later — so we try anyway.
        try:
            return _ocr_tcp.process(
                images_config=images_config,
                lang=PADDLEOCR_LANG_MAP.get(self.lang, "ch"),
                use_layout=bool(self.use_layout),
                timeout_per_image=int(getattr(self, "timeout", OCR_TIMEOUT_PER_IMAGE)),
                n_images=len(images_config),
            )
        except (TimeoutError, ConnectionError, OSError, RuntimeError) as exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "OCR TCP worker failed (%s), falling back to embedded.", exc
            )

        # Fallback: embedded persistent subprocess
        return _ocr_worker.process(
            images_config=images_config,
            lang=PADDLEOCR_LANG_MAP.get(self.lang, "ch"),
            use_layout=bool(self.use_layout),
            timeout_per_image=int(getattr(self, "timeout", OCR_TIMEOUT_PER_IMAGE)),
            n_images=len(images_config),
        )

    def process_images(self) -> Message:
        """Process images and return combined Markdown as a Message."""
        images_config = self._get_images_config()

        results = self._run_ocr(images_config)

        md_sections = []
        file_count = 0
        error_count = 0

        for r in results:
            err = r.get("error")
            if err:
                md_sections.append(f"## {r.get('file', 'unknown')}\n\n*Error: {err}*\n")
                error_count += 1
            else:
                md = r.get("markdown", "")
                if md:
                    md_sections.append(md)
                file_count += 1

        combined = "\n\n---\n\n".join(md_sections) if md_sections else "*(No output)*"

        summary = f"Processed {file_count} image(s)" + (f", {error_count} error(s)" if error_count else "")
        self.status = summary

        return Message(text=combined)

    def process_images_dataframe(self) -> DataFrame:
        """Process images and return a DataFrame with per-file results."""
        images_config = self._get_images_config()
        results = self._run_ocr(images_config)

        rows = [
            Data(
                data={
                    "file": r.get("file", "unknown"),
                    "markdown": r.get("markdown", ""),
                    "text_lines": r.get("text_lines", 0),
                    "error": r.get("error"),
                }
            )
            for r in results
        ]

        if not rows:
            msg = "No results from OCR processing."
            raise ValueError(msg)

        self.status = f"OCR complete: {len(rows)} file(s)"
        return DataFrame(rows)
