"""Render only visible pixels for local OCR, review, and irreversible PDF output."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from importlib import import_module
import math
from pathlib import Path
from threading import Lock
from types import ModuleType

import numpy as np

from shared.windows_platform import prime_windows_platform
from .detection import Box, Finding, Line, Mark, combine_pages, inspect_page
from .micr import transit_bands


def _load_pdfium() -> ModuleType:
    # PDFium and ONNX Runtime both consult Python's platform cache.
    prime_windows_platform()
    return import_module("pypdfium2")


pdf = _load_pdfium()

# PDFium cannot be called concurrently, even for different documents. Keep
# OCR outside the lock so an arriving scan does not block the cashier's preview.
_pdf_lock = Lock()


def local_ocr() -> Callable:
    import rapidocr
    from rapidocr import RapidOCR

    models = Path(rapidocr.__file__).parent / "models"
    engine = RapidOCR(params={
        "Det.model_path": str(models / "PP-OCRv6_det_small.onnx"),
        "Cls.model_path": str(models / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"),
        "Rec.model_path": str(models / "PP-OCRv6_rec_small.onnx"),
        "EngineConfig.onnxruntime.intra_op_num_threads": 2,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "Global.log_level": "error",
    })

    def recognize(image: np.ndarray) -> list[Line]:
        output = engine(image)
        height, width = image.shape[:2]
        lines = []
        for text, points in zip(output.txts or (), output.boxes if output.boxes is not None else ()):
            left, top = points.min(axis=0)
            right, bottom = points.max(axis=0)
            lines.append(Line(text, Box(max(0., float(left / width)), max(0., float(top / height)),
                                        min(1., float(right / width)), min(1., float(bottom / height)))))
        return lines

    return recognize


def page_count(source: bytes) -> int:
    with _pdf_lock, pdf.PdfDocument(source) as document:
        if not len(document):
            raise ValueError("The PDF has no pages.")
        return len(document)


def _render(page, dpi, limit):
    width, height = page.get_size()
    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
        raise ValueError("The PDF has an invalid page size.")
    return page.render(scale=min(dpi / 72, limit / max(width, height)), draw_annots=True)


def page_pixels(source: bytes, index: int, dpi: int = 150) -> np.ndarray:
    with _pdf_lock, pdf.PdfDocument(source) as document:
        page = document[index]
        bitmap = _render(page, dpi, 3000)
        return bitmap.to_numpy().copy()


def inspect_pdf(source: bytes, recognize: Callable[[np.ndarray], list[Line]]) -> Finding:
    pages = []
    for index in range(page_count(source)):
        image = page_pixels(source, index)
        pages.append(inspect_page(index, recognize(image), tuple(transit_bands(image))))
    return combine_pages(pages)


def redact_pdf(source: bytes, marks: Sequence[Mark], target) -> None:
    """Build a fresh image-only PDF. Never embed original images, text, or attachments."""
    with _pdf_lock, pdf.PdfDocument(source) as original, pdf.PdfDocument.new() as output:
        if not marks or not all(0 <= m.page < len(original) and
                                0 <= m.box.left < m.box.right <= 1 and
                                0 <= m.box.top < m.box.bottom <= 1 for m in marks):
            raise ValueError("Review the redaction boxes before filing.")
        for index in range(len(original)):
            page = original[index]
            width, height = page.get_size()
            bitmap = _render(page, 300, 5400)
            pixels = bitmap.to_numpy()
            h, w = pixels.shape[:2]
            for mark in marks:
                if mark.page == index:
                    b = mark.box
                    pixels[math.floor(b.top*h):math.ceil(b.bottom*h),
                           math.floor(b.left*w):math.ceil(b.right*w)] = 0
            new_page = output.new_page(width, height)
            image = pdf.PdfImage.new(output)
            image.set_bitmap(bitmap)
            image.set_matrix(pdf.PdfMatrix().scale(width, height))
            new_page.insert_obj(image)
            new_page.gen_content()
            new_page.close()
            bitmap.close()
            page.close()
        output.save(target)
