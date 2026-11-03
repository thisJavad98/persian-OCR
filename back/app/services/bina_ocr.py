"""Bina 0.2 page OCR — detect text regions and split into per-word tokens."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, List, Optional, Sequence

import cv2
import numpy as np
from PIL import Image

from app.config import Settings, get_settings
from app.services.persian_text import (
    hazm_normalize,
    is_meaningful_persian,
    normalize_persian,
    pred_reverse,
)

logger = logging.getLogger(__name__)

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

_WORD_SPLIT = re.compile(r"[\s\u200c\u200f\u200e]+")
_PERSIAN_TOKEN = re.compile(r"[\u0600-\u06FF0-9۰-۹A-Za-z]+(?:[‌\-][\u0600-\u06FF0-9۰-۹A-Za-z]+)*")


@dataclass
class WordResult:
    text: str
    confidence: float
    box: Optional[List[List[float]]] = None
    row: int = 0
    line_index: int = 0

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "box": self.box,
            "row": self.row,
            "line_index": self.line_index,
        }


@dataclass
class BinaLine:
    text: str
    confidence: float
    box: Optional[List[List[float]]] = None
    row: int = 0
    raw_visual_text: str = ""

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "box": self.box,
            "row": self.row,
            "raw_visual_text": self.raw_visual_text,
        }


@dataclass
class BinaPageResult:
    text: str
    lines: List[BinaLine] = field(default_factory=list)
    words: List[WordResult] = field(default_factory=list)
    confidence: float = 0.0
    engine: str = "bina-0.2"
    details: dict = field(default_factory=dict)


class BinaOcrService:
    """Full-page Persian OCR using Bina-style detector + recognizer dirs."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._ocr = None
        self._lock = threading.Lock()
        self._ready = False
        self._init_error: Optional[str] = None
        self._engine_label = "bina-0.2"

    @property
    def ready(self) -> bool:
        return self._ready and self._ocr is not None

    @property
    def init_error(self) -> Optional[str]:
        return self._init_error

    @property
    def engine_name(self) -> str:
        return self._engine_label

    def model_paths(self) -> tuple[Path, Path]:
        base = self.settings.bina_model_path
        return base / "inference", base / "detector"

    def models_present(self) -> bool:
        inference, detector = self.model_paths()
        return _dir_has_weights(inference) and _dir_has_weights(detector)

    def warmup(self) -> None:
        with self._lock:
            if self._ready:
                return
            inference, detector = self.model_paths()
            if not _dir_has_weights(inference) or not _dir_has_weights(detector):
                self._init_error = (
                    f"Bina models missing under {self.settings.bina_model_path}. "
                    "Run: python scripts/download_bina.py"
                )
                self._ready = False
                logger.warning(self._init_error)
                return
            try:
                from paddleocr import PaddleOCR

                options: dict[str, Any] = {
                    "text_detection_model_dir": str(detector),
                    "text_recognition_model_dir": str(inference),
                    "use_doc_orientation_classify": False,
                    "use_doc_unwarping": False,
                    "use_textline_orientation": False,
                    "text_rec_score_thresh": float(self.settings.bina_score_threshold),
                }
                device = (self.settings.bina_device or "").strip()
                if device:
                    options["device"] = device
                self._ocr = PaddleOCR(**options)
                if (inference / ".bina_bootstrap").exists():
                    self._engine_label = "bina-0.2-bootstrap"
                else:
                    self._engine_label = "bina-0.2"
                self._ready = True
                self._init_error = None
                logger.info(
                    "Bina OCR ready (%s) inference=%s detector=%s",
                    self._engine_label,
                    inference,
                    detector,
                )
            except Exception as exc:
                self._ocr = None
                self._ready = False
                self._init_error = f"bina: {exc}"
                logger.exception("Bina OCR init failed")

    def extract(self, image: Image.Image) -> BinaPageResult:
        self.warmup()
        if not self.ready:
            raise RuntimeError(self._init_error or "Bina OCR is not available")

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temp_path = handle.name
            rgb = image.convert("RGB")
            bgr = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)
            cv2.imwrite(temp_path, bgr)

        try:
            pages = list(self._predict_paths([temp_path]))
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

        if not pages:
            return BinaPageResult(
                text="",
                lines=[],
                words=[],
                confidence=0.0,
                engine=self._engine_label,
                details={"page_count": 0},
            )

        page = pages[0]
        lines = page["lines"]
        words = _lines_to_words(lines)
        confidence = (
            float(sum(line.confidence for line in lines) / len(lines)) if lines else 0.0
        )
        return BinaPageResult(
            text=page["text"],
            lines=lines,
            words=words,
            confidence=confidence,
            engine=self._engine_label,
            details={
                "page_count": len(pages),
                "line_count": len(lines),
                "word_count": len(words),
                "model_dir": str(self.settings.bina_model_path),
            },
        )

    def _predict_paths(self, inputs: Sequence[str | Path]) -> Iterator[dict[str, Any]]:
        assert self._ocr is not None
        for source in inputs:
            for page_index, result in enumerate(self._ocr.predict(str(source))):
                raw = _paddle_payload(result)
                lines = ordered_lines(raw)
                row_text: dict[int, list[str]] = {}
                for line in lines:
                    row_text.setdefault(int(line.row), []).append(line.text)
                text = "\n".join(
                    " ".join(row_text[index]).strip()
                    for index in sorted(row_text)
                    if row_text[index]
                )
                yield {
                    "input_path": str(source),
                    "page_index": page_index,
                    "text": text,
                    "lines": lines,
                }


def ordered_lines(payload: dict[str, Any]) -> List[BinaLine]:
    visual_texts = [str(value) for value in payload.get("rec_texts", [])]
    texts = [pred_reverse(value) for value in visual_texts]
    scores = [float(value) for value in payload.get("rec_scores", [0.0] * len(texts))]
    boxes = payload.get("rec_polys") or payload.get("rec_boxes") or []

    if len(boxes) != len(texts):
        return [
            BinaLine(
                text=hazm_normalize(normalize_persian(text)),
                confidence=scores[i] if i < len(scores) else 0.0,
                box=None,
                row=0,
                raw_visual_text=visual_texts[i],
            )
            for i, text in enumerate(texts)
            if hazm_normalize(normalize_persian(text))
        ]

    items: list[dict[str, Any]] = []
    for i, (text, box) in enumerate(zip(texts, boxes)):
        poly = _normalize_box(box)
        if poly is None:
            continue
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        cleaned = hazm_normalize(normalize_persian(text))
        if not cleaned:
            continue
        items.append(
            {
                "text": cleaned,
                "score": scores[i] if i < len(scores) else 0.0,
                "raw_visual_text": visual_texts[i],
                "box": poly,
                "x": (min(xs) + max(xs)) / 2,
                "y": (min(ys) + max(ys)) / 2,
                "height": max(max(ys) - min(ys), 1.0),
            }
        )

    items.sort(key=lambda item: item["y"])
    rows: list[list[dict[str, Any]]] = []
    for item in items:
        if not rows:
            rows.append([item])
            continue
        row = rows[-1]
        mean_y = sum(part["y"] for part in row) / len(row)
        mean_h = sum(part["height"] for part in row) / len(row)
        if abs(item["y"] - mean_y) <= 0.55 * max(item["height"], mean_h):
            row.append(item)
        else:
            rows.append([item])

    output: List[BinaLine] = []
    for row_index, row in enumerate(rows):
        row.sort(key=lambda item: item["x"], reverse=True)
        for item in row:
            output.append(
                BinaLine(
                    text=item["text"],
                    confidence=float(item["score"]),
                    box=item["box"],
                    row=row_index,
                    raw_visual_text=item["raw_visual_text"],
                )
            )
    return output


def _lines_to_words(lines: Sequence[BinaLine]) -> List[WordResult]:
    words: List[WordResult] = []
    for line_index, line in enumerate(lines):
        tokens = _tokenize_words(line.text)
        if not tokens:
            if is_meaningful_persian(line.text, min_letters=1) or re.search(r"\d", line.text):
                words.append(
                    WordResult(
                        text=line.text,
                        confidence=line.confidence,
                        box=line.box,
                        row=line.row,
                        line_index=line_index,
                    )
                )
            continue
        boxes = _split_box_rtl(line.box, len(tokens))
        for token_index, token in enumerate(tokens):
            words.append(
                WordResult(
                    text=token,
                    confidence=line.confidence,
                    box=boxes[token_index] if token_index < len(boxes) else line.box,
                    row=line.row,
                    line_index=line_index,
                )
            )
    return words


def _tokenize_words(text: str) -> List[str]:
    cleaned = hazm_normalize(normalize_persian(text or ""))
    if not cleaned:
        return []
    found = _PERSIAN_TOKEN.findall(cleaned)
    if found:
        return [tok for tok in found if tok.strip()]
    return [part for part in _WORD_SPLIT.split(cleaned) if part.strip()]


def _split_box_rtl(
    box: Optional[List[List[float]]], count: int
) -> List[Optional[List[List[float]]]]:
    if count <= 0:
        return []
    if box is None or count == 1:
        return [box for _ in range(count)]
    xs = [point[0] for point in box]
    ys = [point[1] for point in box]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    width = max(x1 - x0, 1.0)
    # RTL: first token occupies the rightmost slice.
    slices: List[Optional[List[List[float]]]] = []
    for index in range(count):
        right_frac = index / count
        left_frac = (index + 1) / count
        right = x1 - width * right_frac
        left = x1 - width * left_frac
        slices.append([[left, y0], [right, y0], [right, y1], [left, y1]])
    return slices


def _paddle_payload(result: Any) -> dict:
    if hasattr(result, "json"):
        payload = result.json() if callable(result.json) else result.json
        if isinstance(payload, dict):
            return payload.get("res", payload)
    if isinstance(result, dict):
        return result.get("res", result)
    return {}


def _normalize_box(box: Any) -> Optional[List[List[float]]]:
    if box is None:
        return None
    if hasattr(box, "tolist"):
        box = box.tolist()
    flat = [float(value) for value in np.array(box).reshape(-1)]
    if len(flat) == 4:
        x0, y0, x1, y1 = flat
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    if len(flat) >= 8:
        return [[flat[i], flat[i + 1]] for i in range(0, 8, 2)]
    return None


def _dir_has_weights(path: Path) -> bool:
    if not path.is_dir():
        return False
    names = {item.name for item in path.iterdir()}
    has_params = any(
        name.endswith(".pdiparams") or name.endswith(".onnx") or name.endswith(".json")
        for name in names
    )
    has_yml = "inference.yml" in names or any(name.endswith(".yml") for name in names)
    return has_params and (has_yml or "inference.json" in names)


_bina_service: Optional[BinaOcrService] = None


def get_bina_service() -> BinaOcrService:
    global _bina_service
    if _bina_service is None:
        _bina_service = BinaOcrService()
    return _bina_service
