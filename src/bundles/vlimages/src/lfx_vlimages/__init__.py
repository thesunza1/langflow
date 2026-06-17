"""lfx-vlimages: VL Images component bundle.

Uses Qwen3.5-2B VLM running on vLLM (local server) to describe
images and return structured Markdown descriptions.
"""

from lfx_vlimages.components.vlimages.vl_images import VLImagesComponent

__all__ = ["VLImagesComponent"]
