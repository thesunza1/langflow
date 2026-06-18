#!/usr/bin/env python3
"""OCR Worker Server — standalone TCP daemon for PaddleOCR + PP-DocLayoutV3.

Pre-loads PaddleOCR and optional layout models at startup so that
Langflow OCR components can make fast, concurrent OCR calls.

Usage:
    uv run python src/bundles/paddleocr/ocr_worker_server.py [OPTIONS]

Options:
    --host HOST         Listen address (default: 127.0.0.1)
    --port PORT         Listen port (default: 18765)
    --preload-lang LANG OCR language to preload (default: ch)
    --preload-layout    Also preload PP-DocLayoutV3 layout model

Environment variables (overridden by CLI flags):
    LFX_OCR_WORKER_HOST
    LFX_OCR_WORKER_PORT

Protocol:
    One request per TCP connection.  Send a JSON line, receive a JSON line.
    Request schema:
        {
            "images": [
                {"kind": "file", "path": "/path/to/img.jpg", "file_name": "img.jpg"},
                {"kind": "base64", "data": "<base64>", "file_name": "img.png"}
            ],
            "lang": "ch",
            "use_layout": true
        }
    Response schema:
        {"ok": true, "results": [{"file": "...", "markdown": "...", "text_lines": N, "error": null}]}
        or
        {"ok": false, "error": "message"}
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
import signal
import socket
import socketserver
import sys
import textwrap
import threading
import time
from pathlib import Path

# --------------------------------------------------------------------------- #
# Early environment setup                                                     #
# --------------------------------------------------------------------------- #
os.environ.setdefault("PP_DEBUG", "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ocr-worker")

# --------------------------------------------------------------------------- #
# Shared OCR engine (module-level, persists across requests)                  #
# --------------------------------------------------------------------------- #
_ocr_engine = None
_ocr_lang = None
_layout_pipeline = None

LAYOUT_LABELS: dict[int, str] = {
    0: "title",
    1: "plain_text",
    2: "abandon",
    3: "figure",
    4: "figure_caption",
    5: "table",
    6: "table_caption",
    7: "table_footnote",
    8: "isolate_formula",
    9: "formula_caption",
}


def ensure_ocr(lang: str = "ch") -> None:
    """Load (or re-load) PaddleOCR engine for *lang*."""
    global _ocr_engine, _ocr_lang
    if _ocr_engine is not None and _ocr_lang == lang:
        return
    logger.info("Loading PaddleOCR (lang=%s) …", lang)
    from paddleocr import PaddleOCR

    _ocr_engine = PaddleOCR(use_textline_orientation=True, lang=lang, engine="transformers")
    _ocr_lang = lang
    logger.info("PaddleOCR loaded (lang=%s).", lang)


def ensure_layout() -> None:
    """Load PP-DocLayoutV3 model (once)."""
    global _layout_pipeline
    if _layout_pipeline is not None:
        return
    logger.info("Loading PP-DocLayoutV3 …")
    from transformers import AutoModelForImageClassification, AutoProcessor

    model_id = "PaddlePaddle/PP-DocLayoutV3_safetensors"
    _layout_pipeline = {
        "model": AutoModelForImageClassification.from_pretrained(model_id).eval(),
        "processor": AutoProcessor.from_pretrained(model_id),
    }
    import torch

    if torch.cuda.is_available():
        _layout_pipeline["model"] = _layout_pipeline["model"].cuda()
    logger.info("PP-DocLayoutV3 loaded.")


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
        logger.warning("Layout analysis error: %s", e)
        return []


def _process_image(img_data: bytes, img_name: str, use_layout: bool) -> dict:
    """Run OCR on *img_data* and return a result dict."""
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

    lines_text: list[dict] = []
    if ocr_result:
        for page_result in ocr_result:
            texts = page_result.get("rec_texts") or []
            scores = page_result.get("rec_scores") or []
            polys = page_result.get("rec_polys") or []
            for i, text in enumerate(texts):
                confidence = scores[i] if i < len(scores) else 0.0
                poly = polys[i].tolist() if i < len(polys) else None
                lines_text.append({"text": text, "confidence": confidence, "bbox": poly})

    if use_layout:
        _run_layout_analysis(pil_img)

    md_parts = [f"## {img_name}", ""]
    if not lines_text:
        md_parts.append("*(No text detected)*")
    else:
        lines_text.sort(key=lambda x: (x["bbox"][0][1], x["bbox"][0][0]))
        paragraph: list[str] = []
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
        "markdown": "\n".join(md_parts).strip(),
        "text_lines": len(lines_text),
        "error": None,
    }


def handle_request(cfg: dict) -> dict:
    """Process one OCR request and return the response payload."""
    images_input = cfg.get("images", [])
    lang = cfg.get("lang", "ch")
    use_layout = cfg.get("use_layout", False)

    ocr_lang = lang if lang != "Auto" else "ch"
    ensure_ocr(ocr_lang)

    if use_layout:
        try:
            ensure_layout()
        except Exception as e:
            logger.warning("Layout model load failed (continuing w/o layout): %s", e)

    results: list[dict] = []
    for item in images_input:
        kind = item.get("kind", "")
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

    return {"ok": True, "results": results}


# --------------------------------------------------------------------------- #
# TCP Request Handler                                                         #
# --------------------------------------------------------------------------- #
class OCRRequestHandler(socketserver.StreamRequestHandler):
    """One connection = one OCR request."""

    timeout: int = 600  # Max seconds to wait for a request

    def handle(self) -> None:
        try:
            line = self.rfile.readline()
            if not line:
                return
            cfg = json.loads(line.decode("utf-8"))
            response = handle_request(cfg)
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


class ThreadedOCRServer(socketserver.ThreadingTCPServer):
    """Threaded TCP server that accepts concurrent OCR requests."""

    allow_reuse_address = True
    daemon_threads = True  # Threads exit when main thread exits


# --------------------------------------------------------------------------- #
# Startup pre-warm: send a dummy request to ensure models are loaded          #
# --------------------------------------------------------------------------- #
def _prewarm(preload_lang: str, preload_layout: bool) -> None:
    """Load models by processing a minimal request."""
    logger.info("Pre-warming models (lang=%s, layout=%s) …", preload_lang, preload_layout)
    try:
        cfg = {
            "images": [],
            "lang": preload_lang,
            "use_layout": preload_layout,
        }
        # Calling handle_request forces ensure_ocr / ensure_layout
        handle_request(cfg)
    except Exception as e:
        logger.error("Pre-warm failed (continuing): %s", e)
    logger.info("Pre-warm complete.")


# --------------------------------------------------------------------------- #
# CLI entry point                                                             #
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(
        description="OCR Worker Server — pre-loaded PaddleOCR daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              uv run python src/bundles/paddleocr/ocr_worker_server.py
              uv run python src/bundles/paddleocr/ocr_worker_server.py --port 18765 --preload-layout
        """),
    )
    parser.add_argument("--host", default=os.environ.get("LFX_OCR_WORKER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LFX_OCR_WORKER_PORT", "18765")))
    parser.add_argument("--preload-lang", default="ch", help="OCR language to preload (default: ch)")
    parser.add_argument(
        "--preload-layout",
        action="store_true",
        help="Also preload PP-DocLayoutV3 layout model",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------ #
    # Pre-warm models before accepting connections                        #
    # ------------------------------------------------------------------ #
    logger.info("OCR Worker starting on %s:%d", args.host, args.port)
    _prewarm(args.preload_lang, args.preload_layout)

    # ------------------------------------------------------------------ #
    # Start server                                                        #
    # ------------------------------------------------------------------ #
    server = ThreadedOCRServer((args.host, args.port), OCRRequestHandler)
    # Graceful shutdown on SIGTERM / SIGINT
    _shutdown_requested = False

    def _handle_signal(signum, frame):
        nonlocal _shutdown_requested
        if _shutdown_requested:
            return  # already shutting down, re-signal for force-kill
        _shutdown_requested = True
        logger.info("Shutdown signal received, stopping server …")
        # Set the internal flag directly so serve_forever() exits on its
        # next poll cycle (avoids deadlock from calling shutdown() inside
        # the signal handler while serve_forever holds __shutdown_lock).
        server._BaseServer__shutdown_request = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("OCR Worker ready on %s:%d", args.host, args.port)
    sys.stdout.flush()

    # Serve until shutdown signal
    server.serve_forever()
if __name__ == "__main__":
    main()
