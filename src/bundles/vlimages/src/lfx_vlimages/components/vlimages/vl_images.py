r"""VL Images Component — Qwen3.5-2B VLM via vLLM for image description to Markdown.

Upload images or paste base64-encoded images, and the component sends them
to a local vLLM server running a vision-language model (e.g. Qwen3.5-2B).
Returns structured Markdown descriptions.

Requires a running vLLM server (user-managed):
    vllm serve unsloth/Qwen3.5-2B-MTP-GGUF \\
        --quantization gguf \\
        --max-model-len 50000 \\
        --max-num-seqs 4 \\
        --port 8000 \\
        --trust-remote-code
"""  # noqa: EXE002

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from lfx.custom import Component
from lfx.field_typing.range_spec import RangeSpec
from lfx.io import BoolInput, FileInput, IntInput, Output, SecretStrInput, SliderInput, StrInput
from lfx.schema import Data, DataFrame, Message

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful image description assistant. "
    "Describe the image in detail using Markdown formatting. "
    "Use headings, bullet points, and paragraphs as appropriate. "
    "Be concise but thorough. "
    "Do NOT include thinking, reasoning, or chain-of-thought in your response. "
    "Output only the final description."
)

DEFAULT_MODEL = "unsloth/Qwen3.5-2B-MTP-GGUF"
DEFAULT_API_BASE = "http://localhost:8000/v1"


class VLImagesComponent(Component):
    display_name = "VL Images"
    description = (
        "Describe images using Qwen3.5-2B VLM via vLLM. "
        "Upload images or paste base64 data. "
        "Returns structured Markdown descriptions. "
        "Requires a running vLLM server (see docs)."
    )
    documentation = "https://github.com/langflow-ai/langflow"
    trace_type = "tool"
    icon = "image"
    name = "VLImages"

    VALID_EXTENSIONS = ["png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "gif", "heic", "heif", "avif", "jfif", "pjpeg", "pjp"]

    inputs = [
        FileInput(
            name="images",
            display_name="Images",
            file_types=VALID_EXTENSIONS,
            info="Upload one or more images to describe.",
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
        StrInput(
            name="model_name",
            display_name="Model Name",
            info="The vision-language model name as registered in vLLM.",
            value=DEFAULT_MODEL,
        ),
        StrInput(
            name="api_base",
            display_name="vLLM API Base",
            info="vLLM OpenAI-compatible API base URL.",
            value=DEFAULT_API_BASE,
        ),
        SecretStrInput(
            name="api_key",
            display_name="API Key",
            info="API key for vLLM (optional for local servers).",
            advanced=True,
            required=False,
        ),
        SliderInput(
            name="temperature",
            display_name="Temperature",
            value=0.1,
            range_spec=RangeSpec(min=0, max=1, step=0.01),
            advanced=True,
        ),
        IntInput(
            name="max_tokens",
            display_name="Max Tokens",
            info="Maximum tokens in the generated description.",
            value=2000,
            advanced=True,
        ),
        IntInput(
            name="max_model_len",
            display_name="Max Model Context",
            info="Context window size (max_model_len). Set to 50000 for Qwen3.5-2B.",
            value=50000,
            advanced=True,
        ),
        BoolInput(
            name="no_think_mode",
            display_name="No-Think Mode",
            value=True,
            info="Disable thinking/reasoning tokens in the output.",
            advanced=True,
        ),
        StrInput(
            name="system_prompt",
            display_name="System Prompt",
            info="Custom system prompt for image description.",
            value=DEFAULT_SYSTEM_PROMPT,
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Markdown Output",
            name="markdown_output",
            method="describe_images",
            types=["Message"],
        ),
        Output(
            display_name="DataFrame",
            name="dataframe",
            method="describe_images_dataframe",
        ),
    ]

    # ------------------------------ Image loading ------------------------------

    def _collect_images(self) -> list[tuple[str, bytes]]:
        """Collect all images (uploaded + pasted) as (name, bytes) list."""
        images_list: list[tuple[str, bytes]] = []

        # From file uploads
        raw_images = getattr(self, "images", None)
        if raw_images:
            if not isinstance(raw_images, list):
                raw_images = [raw_images]
            for img in raw_images:
                if img is None:
                    continue
                path_str = str(img) if not hasattr(img, "path") else str(img.path)
                path = Path(path_str)
                try:
                    data = path.read_bytes()
                    images_list.append((path.name, data))
                except OSError as e:
                    self.log(f"Cannot read {path_str}: {e}")

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
                try:
                    data = base64.b64decode(b64_str)
                    images_list.append((f"pasted_image_{i + 1}.png", data))
                except (ValueError, base64.binascii.Error) as e:
                    self.log(f"Base64 decode error on line {i + 1}: {e}")

        if not images_list:
            msg = "No images provided. Upload images or paste base64 data."
            raise ValueError(msg)

        return images_list

    def _image_to_base64_url(self, image_bytes: bytes, filename: str) -> str:
        """Convert image bytes to a data URL for the VLM API."""
        ext = Path(filename).suffix.lower().lstrip(".")
        mime_map = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "bmp": "image/bmp",
        }
        mime = mime_map.get(ext, "image/png")
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    # ------------------------------ vLLM API call -----------------------------

    def _build_system_prompt(self) -> str:
        """Build the system prompt with no-think instruction if enabled."""
        base = str(getattr(self, "system_prompt", DEFAULT_SYSTEM_PROMPT))
        if self.no_think_mode:
            base += (
                "\n\nIMPORTANT: Do NOT output any thinking, reasoning, or chain-of-thought. "
                "Skip any thinking/reasoning tags or internal monologue. Output only the final description."
            )
        return base

    def _call_vlm(self, image_name: str, image_bytes: bytes) -> str:
        """Call vLLM VLM API for a single image and return the description."""
        try:
            from openai import OpenAI
        except ImportError as e:
            msg = "openai package not installed. Run: uv pip install 'openai>=1.60.0'"
            raise ImportError(msg) from e

        client = OpenAI(
            base_url=str(getattr(self, "api_base", DEFAULT_API_BASE)),
            api_key=str(getattr(self, "api_key", "") or None),
        )

        image_url = self._image_to_base64_url(image_bytes, image_name)
        extra_body: dict[str, Any] = {}
        max_model_len = int(getattr(self, "max_model_len", 50000))
        if max_model_len:
            extra_body["max_model_len"] = max_model_len

        try:
            response = client.chat.completions.create(
                model=str(getattr(self, "model_name", DEFAULT_MODEL)),
                messages=[
                    {"role": "system", "content": self._build_system_prompt()},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": image_url},
                            },
                            {
                                "type": "text",
                                "text": "Describe this image in Markdown format.",
                            },
                        ],
                    },
                ],
                max_tokens=int(getattr(self, "max_tokens", 2000)),
                temperature=float(getattr(self, "temperature", 0.1)),
                extra_body=extra_body if extra_body else None,
            )
        except Exception as e:
            error_msg = str(e)
            if "connect" in error_msg.lower() or "refused" in error_msg.lower():
                msg = f"Cannot connect to vLLM server at {self.api_base}. Make sure vLLM is running. Error: {error_msg}"
                raise ConnectionError(msg) from e
            raise

        if not response.choices:
            msg = "vLLM returned no completions."
            raise RuntimeError(msg)

        return response.choices[0].message.content or ""

    # ------------------------------ Output methods ----------------------------

    def describe_images(self) -> Message:
        """Describe all images and return combined Markdown as a Message."""
        images = self._collect_images()

        md_sections: list[str] = []
        for name, data in images:
            try:
                description = self._call_vlm(name, data)
                md_sections.append(f"## {name}\n\n{description}")
            except (ConnectionError, RuntimeError, ImportError) as e:
                md_sections.append(f"## {name}\n\n*Error: {e!s}*")

        combined = "\n\n---\n\n".join(md_sections) if md_sections else "*(No output)*"

        self.status = f"Described {len(images)} image(s)"
        return Message(text=combined)

    def describe_images_dataframe(self) -> DataFrame:
        """Describe all images and return a DataFrame with per-file results."""
        images = self._collect_images()

        rows: list[Data] = []
        for name, data in images:
            try:
                description = self._call_vlm(name, data)
                rows.append(
                    Data(
                        data={
                            "file": name,
                            "description": description,
                            "error": None,
                        }
                    )
                )
            except (ConnectionError, RuntimeError, ImportError) as e:
                rows.append(
                    Data(
                        data={
                            "file": name,
                            "description": "",
                            "error": str(e),
                        }
                    )
                )

        if not rows:
            msg = "No results from VLM processing."
            raise ValueError(msg)

        self.status = f"Described {len(rows)} image(s)"
        return DataFrame(rows)
