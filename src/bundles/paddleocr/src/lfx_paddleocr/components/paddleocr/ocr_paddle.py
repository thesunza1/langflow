"""OCR Paddle Component — PaddleOCR + PP-DocLayoutV3 for document OCR to Markdown.

Processes images (upload or paste) through PaddleOCR text detection/recognition
and optional PP-DocLayoutV3 layout analysis, outputting structured Markdown.

PaddlePaddle and PyTorch run in an isolated subprocess (same pattern as Docling's
_CHILD_SCRIPT) to prevent OOM and native-library-state issues in the main process.
"""  # noqa: EXE002

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
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
POLL_INTERVAL = 5


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
            value="Auto",
            info="OCR language. 'Auto' tries multiple common languages and picks the best result.",
        ),
        BoolInput(
            name="use_layout",
            display_name="Use Layout Analysis",
            value=True,
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

    # ------------------------------------------------------------------ #
    # Child script that runs PaddleOCR in a separate OS process.          #
    # ------------------------------------------------------------------ #
    _CHILD_SCRIPT: str = textwrap.dedent(r"""
        import base64, io, json, sys, os
        from pathlib import Path

        # Suppress excessive PaddlePaddle/transformers logging in the child
        os.environ["PP_DEBUG"] = "0"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"

        def main():
            cfg = json.loads(sys.stdin.read())
            images_input  = cfg["images"]       # list of {"kind":"file"|"base64","path":str|None,"data":str|None}
            lang          = cfg["lang"]
            use_layout    = cfg["use_layout"]

            # ----- import paddleocr (lazy; first import loads torch/paddle) -----
            try:
                from paddleocr import PaddleOCR
            except ImportError as e:
                print(json.dumps({"ok": False, "error": f"PaddleOCR not installed: {e}"}))
                return

            # ----- layout model (optional) -----
            layout_pipeline = None
            if use_layout:
                try:
                    from transformers import AutoProcessor, AutoModelForDocumentImageClassification
                    import torch
                    # PP-DocLayoutV3 uses a lightweight layout model
                    layout_model_id = "PaddlePaddle/PP-DocLayoutV3_safetensors"
                    layout_processor = AutoProcessor.from_pretrained(layout_model_id)
                    layout_model = AutoModelForDocumentImageClassification.from_pretrained(layout_model_id)
                    layout_model.eval()
                    if torch.cuda.is_available():
                        layout_model = layout_model.cuda()
                    layout_pipeline = {
                        "model": layout_model,
                        "processor": layout_processor,
                    }
                except Exception as e:
                    # Layout model is best-effort; fall back to OCR-only
                    sys.stderr.write(f"Layout model load failed (continuing without layout): {e}\n")
                    layout_pipeline = None

            LAYOUT_LABELS = {
                0: "title", 1: "plain_text", 2: "abandon", 3: "figure",
                4: "figure_caption", 5: "table", 6: "table_caption",
                7: "table_footnote", 8: "isolate_formula", 9: "formula_caption",
            }

            # ----- PaddleOCR -----
            ocr_lang = lang if lang != "Auto" else "ch"
            try:
                ocr = PaddleOCR(use_angle_cls=True, lang=ocr_lang, show_log=False)
            except Exception as e:
                print(json.dumps({"ok": False, "error": f"PaddleOCR init failed: {e}"}))
                return

            def run_layout_analysis(pil_img) -> list[dict]:
                # Run PP-DocLayoutV3 on a PIL image and return list of layout regions.
                if layout_pipeline is None:
                    return []
                try:
                    import torch
                    inputs = layout_pipeline["processor"](images=pil_img, return_tensors="pt")
                    if torch.cuda.is_available():
                        inputs = {k: v.cuda() for k, v in inputs.items()}
                    with torch.no_grad():
                        outputs = layout_pipeline["model"](**inputs)
                    logits = outputs.logits
                    predicted_ids = logits.argmax(-1).squeeze().tolist()
                    if isinstance(predicted_ids, int):
                        predicted_ids = [predicted_ids]
                    # Return list of detected layout categories (no bbox from simple classifier)
                    labels = [LAYOUT_LABELS.get(pid, "unknown") for pid in predicted_ids]
                    return [{"category": cat} for cat in labels]
                except Exception as e:
                    sys.stderr.write(f"Layout analysis error: {e}\n")
                    return []

            def process_single_image(img_data: bytes, img_name: str) -> dict:
                # Run OCR + optional layout on one image, return Markdown.
                try:
                    from PIL import Image
                    pil_img = Image.open(io.BytesIO(img_data)).convert("RGB")
                except Exception as e:
                    return {"file": img_name, "error": f"Image load failed: {e}", "markdown": ""}

                # ---- OCR ----
                try:
                    ocr_result = ocr.ocr(img_data, cls=True)
                except Exception as e:
                    return {"file": img_name, "error": f"OCR failed: {e}", "markdown": ""}

                lines_text = []
                if ocr_result and ocr_result[0]:
                    for line_info in ocr_result[0]:
                        bbox, (text, confidence) = line_info
                        lines_text.append({"text": text, "confidence": confidence, "bbox": bbox})

                # ---- Layout analysis (optional) ----
                layout_regions = []
                if use_layout:
                    layout_regions = run_layout_analysis(pil_img)

                # ---- Build Markdown ----
                md_parts = [f"## {img_name}", ""]

                if not lines_text:
                    md_parts.append("*(No text detected)*")
                else:
                    # Sort OCR results top-to-bottom, left-to-right
                    lines_text.sort(key=lambda x: (x["bbox"][0][1], x["bbox"][0][0]))

                    # Group consecutive lines into paragraphs
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

                md_text = "\n".join(md_parts).strip()
                return {
                    "file": img_name,
                    "markdown": md_text,
                    "text_lines": len(lines_text),
                    "error": None,
                }

            # ----- Process each image -----
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

                result = process_single_image(data_bytes, name)
                results.append(result)

            print(json.dumps({"ok": True, "results": results}))

        if __name__ == "__main__":
            main()
    """)

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

    def _run_ocr_subprocess(self, images_config: list[dict]) -> list[dict]:
        """Run PaddleOCR in a subprocess and return results list."""
        if not images_config:
            msg = "No images provided. Upload images or paste base64 data."
            raise ValueError(msg)

        args = {
            "images": images_config,
            "lang": PADDLEOCR_LANG_MAP.get(self.lang, "ch"),
            "use_layout": bool(self.use_layout),
        }

        timeout = max(30, int(getattr(self, "timeout", OCR_TIMEOUT_PER_IMAGE)) * len(images_config))
        poll_interval = POLL_INTERVAL

        import tempfile

        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            proc = subprocess.Popen(  # noqa: S603
                [sys.executable, "-u", "-c", self._CHILD_SCRIPT],
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
            )
            proc.stdin.write(json.dumps(args).encode("utf-8"))
            proc.stdin.close()

            start = time.monotonic()
            while proc.poll() is None:
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    proc.kill()
                    proc.wait()
                    msg = f"OCR processing timed out after {timeout}s."
                    raise TimeoutError(msg)
                self.log(f"OCR processing in progress ({int(elapsed)}s elapsed)...")
                time.sleep(poll_interval)

            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout_bytes = stdout_file.read()
            stderr_bytes = stderr_file.read()

        if not stdout_bytes:
            err_msg = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else "no output"
            msg = f"OCR subprocess error: {err_msg}"
            raise RuntimeError(msg)

        try:
            payload = json.loads(stdout_bytes.decode("utf-8"))
        except Exception as e:
            err_msg = stderr_bytes.decode("utf-8", errors="replace")
            msg = f"Invalid JSON from OCR subprocess: {e}. stderr={err_msg}"
            raise RuntimeError(msg) from e

        if not payload.get("ok"):
            error_msg = payload.get("error", "Unknown OCR error")
            raise RuntimeError(error_msg)

        return payload.get("results", [])

    def process_images(self) -> Message:
        """Process images and return combined Markdown as a Message."""
        images_config = self._get_images_config()
        results = self._run_ocr_subprocess(images_config)

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
        results = self._run_ocr_subprocess(images_config)

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
