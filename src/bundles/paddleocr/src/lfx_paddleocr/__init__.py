"""lfx-paddleocr: OCR Paddle component bundle.

Uses PaddleOCR for text detection + recognition and PP-DocLayoutV3
for document layout analysis, exporting results as structured Markdown.
"""

from lfx_paddleocr.components.paddleocr.ocr_paddle import OcrPaddleComponent

__all__ = ["OcrPaddleComponent"]
