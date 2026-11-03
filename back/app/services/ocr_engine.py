"""Persian / Nasta'liq OCR: vision + Bina boxes + Paddle/EasyOCR Persian text."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any, List, Optional

import cv2
import numpy as np
from PIL import Image

from app.config import Settings, get_settings
from app.services.bina_ocr import WordResult, get_bina_service
from app.services.persian_text import (
    has_persian_letters,
    hazm_normalize,
    is_digits_only,
    is_meaningful_persian,
    normalize_persian,
    pred_reverse,
)
from app.services.preprocess import prepare_image
from app.services.vision_ocr import get_vision_ocr

logger = logging.getLogger(__name__)

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

_ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
_DIGITS_ONLY = re.compile(r"^[\s0-9۰-۹:.\-_/]+$")


@dataclass
class LineResult:
    text: str
    confidence: float
    box: Optional[List[List[float]]] = None
    row: Optional[int] = None


@dataclass
class OcrResult:
    text: str
    lines: List[LineResult]
    confidence: float
    engine: str
    details: dict = field(default_factory=dict)
    table_rows: Optional[List[List[str]]] = None
    death_records: Optional[dict] = None
    words: List[WordResult] = field(default_factory=list)


class PersianOcrService:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._easy = None
        self._paddle = None
        self._vision_ok = False
        self._bina_ok = False
        self._lock = threading.Lock()
        self._ready = False
        self._init_error: Optional[str] = None

    @property
    def engines(self) -> List[str]:
        names: List[str] = []
        if self._vision_ok:
            names.append("vision-nastaliq")
        if self._bina_ok:
            names.append(get_bina_service().engine_name)
        if self._paddle is not None:
            names.append("paddleocr-fa")
        if self._easy is not None:
            names.append("easyocr-fa")
        return names

    @property
    def ready(self) -> bool:
        return bool(self.engines) and (
            self._vision_ok or self._bina_ok or self._paddle is not None or self._easy is not None
        )

    @property
    def init_error(self) -> Optional[str]:
        return self._init_error

    def warmup(self) -> None:
        with self._lock:
            if self._ready and self.engines:
                return
            errors: List[str] = []

            try:
                vision = get_vision_ocr()
                self._vision_ok = vision.available()
                if self._vision_ok:
                    logger.info("Vision Nasta'liq OCR ready (%s)", vision.model)
                else:
                    errors.append("vision: ollama model not available")
            except Exception as exc:
                errors.append(f"vision: {exc}")
                logger.exception("Vision OCR init failed")

            try:
                bina = get_bina_service()
                bina.warmup()
                self._bina_ok = bina.ready
                if self._bina_ok:
                    logger.info("Bina word OCR ready (%s)", bina.engine_name)
                else:
                    errors.append(bina.init_error or "bina: models not ready")
            except Exception as exc:
                errors.append(f"bina: {exc}")
                logger.exception("Bina OCR init failed")

            try:
                from paddleocr import PaddleOCR

                # Do not pass text_*_model_name here — that ignores lang=fa and loads
                # the Chinese medium recognizer, which turns Persian into digit noise.
                self._paddle = PaddleOCR(
                    lang="fa",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    text_det_limit_side_len=min(1600, self.settings.ocr_max_image_side),
                    text_rec_score_thresh=0.5,
                )
                logger.info("PaddleOCR-fa ready (arabic_PP-OCRv5 recognizer)")
            except Exception as exc:
                errors.append(f"paddleocr: {exc}")
                logger.exception("PaddleOCR init failed")

            try:
                import easyocr

                langs = self.settings.language_list or ["fa", "en"]
                self._easy = easyocr.Reader(langs, gpu=self.settings.ocr_use_gpu, verbose=False)
                logger.info("EasyOCR-fa ready")
            except Exception as exc:
                errors.append(f"easyocr: {exc}")
                logger.exception("EasyOCR init failed")

            self._ready = bool(self.engines)
            self._init_error = "; ".join(errors) if errors else None

    def extract(self, image: Image.Image) -> OcrResult:
        self.warmup()
        if not self.engines:
            raise RuntimeError(self._init_error or "OCR engine is not available")

        min_conf = self.settings.ocr_min_confidence

        bina_result = None
        if self._bina_ok:
            try:
                bina_result = get_bina_service().extract(image)
            except Exception:
                logger.exception("Bina OCR failed")

        classic = self._run_classic(image, min_conf)

        # 1) Vision semantic path for deceased-list structure.
        if self._vision_ok:
            try:
                vision = get_vision_ocr().extract(image)
                death = vision.death_extract
                has_records = bool(death and death.records)
                has_text = bool(vision.text and is_meaningful_persian(vision.text, min_letters=1))
                if has_records or has_text:
                    return self._merge_vision_with_detectors(
                        vision=vision,
                        death=death,
                        bina_result=bina_result,
                        classic=classic,
                        min_conf=min_conf,
                    )
            except Exception:
                logger.exception("Vision OCR failed; falling back to detectors")

        # 2) Classic Persian engines + Bina boxes.
        merged = self._merge_detectors(bina_result, classic, min_conf)
        if merged is not None:
            return merged

        return OcrResult(
            text="",
            lines=[],
            confidence=0.0,
            engine="+".join(self.engines) or "none",
            details={"min_confidence": min_conf, "mode": "empty"},
            words=[],
        )

    def _run_classic(self, image: Image.Image, min_conf: float) -> Optional[OcrResult]:
        if self._paddle is None and self._easy is None:
            return None
        prepared = prepare_image(image, max_side=self.settings.ocr_max_image_side)
        candidates: List[OcrResult] = []
        if self._paddle is not None:
            candidates.append(self._run_paddle(prepared.color_bgr, "color"))
            candidates.append(self._run_paddle(prepared.enhanced_bgr, "enhanced"))
        if self._easy is not None:
            candidates.append(self._run_easyocr(prepared.enhanced_bgr, "enhanced"))
        return _merge_exportable_lines(candidates, min_conf)

    def _merge_vision_with_detectors(
        self,
        *,
        vision: Any,
        death: Any,
        bina_result: Any,
        classic: Optional[OcrResult],
        min_conf: float,
    ) -> OcrResult:
        source_lines = list(vision.lines or [])
        if death and death.summary_text:
            source_lines.extend(death.summary_text.splitlines())
        if vision.text:
            source_lines.extend(vision.text.splitlines())
        if death:
            for rec in death.records:
                if rec.raw_line:
                    source_lines.append(rec.raw_line)

        seen = set()
        lines: List[LineResult] = []
        for line in source_lines:
            cleaned = hazm_normalize(line or "")
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            lines.append(
                LineResult(text=cleaned, confidence=max(vision.confidence, min_conf))
            )

        # Prefer Persian letter lines from classic engines over digit-only Bina noise.
        if classic:
            for item in classic.lines:
                if item.text in seen:
                    continue
                if has_persian_letters(item.text) or not _is_digit_noise(item.text):
                    seen.add(item.text)
                    lines.append(item)

        if bina_result:
            for item in bina_result.lines:
                text = item.text
                if text in seen:
                    continue
                # Keep Bina geometry only when it carries Persian letters (not bare IDs).
                if has_persian_letters(text):
                    seen.add(text)
                    lines.append(
                        LineResult(
                            text=text,
                            confidence=item.confidence,
                            box=item.box,
                            row=item.row,
                        )
                    )

        words = _build_words(
            classic_lines=(classic.lines if classic else []),
            bina_words=(bina_result.words if bina_result else []),
            vision_lines=lines,
            min_conf=min_conf,
        )

        text = hazm_normalize(
            (death.summary_text if death and death.summary_text else vision.text)
            or "\n".join(line.text for line in lines)
        )
        if classic and classic.text and _persian_letter_count(classic.text) > _persian_letter_count(
            text
        ):
            text = classic.text

        engines = [f"vision-nastaliq/{vision.model}"]
        if bina_result:
            engines.append(bina_result.engine)
        if classic:
            engines.append(classic.engine.split("/")[0])

        return OcrResult(
            text=text,
            lines=lines,
            confidence=max(float(vision.confidence), min_conf),
            engine="+".join(engines),
            details={
                "mode": "vision+detectors",
                "names": vision.names,
                "min_confidence": min_conf,
                "record_count": len(death.records) if death else 0,
                "line_count": len(lines),
                "word_count": len(words),
                "passes": (vision.raw or {}).get("passes"),
                "death_details": (death.details if death else {}),
                "bina": (bina_result.details if bina_result else {}),
                "classic_engine": classic.engine if classic else None,
            },
            table_rows=None,
            death_records=death.as_dict() if death else None,
            words=words,
        )

    def _merge_detectors(
        self,
        bina_result: Any,
        classic: Optional[OcrResult],
        min_conf: float,
    ) -> Optional[OcrResult]:
        if classic is None and bina_result is None:
            return None

        lines: List[LineResult] = []
        engines: List[str] = []
        if classic:
            engines.append(classic.engine)
            lines.extend(classic.lines)
        if bina_result:
            engines.append(bina_result.engine)
            for item in bina_result.lines:
                if has_persian_letters(item.text):
                    lines.append(
                        LineResult(
                            text=item.text,
                            confidence=item.confidence,
                            box=item.box,
                            row=item.row,
                        )
                    )

        # Deduplicate preferring Persian letters + confidence.
        lines = _dedupe_lines(lines)
        words = _build_words(
            classic_lines=(classic.lines if classic else []),
            bina_words=(bina_result.words if bina_result else []),
            vision_lines=lines,
            min_conf=min_conf,
        )
        text = "\n".join(line.text for line in lines).strip()
        if not text and classic:
            text = classic.text
        if not text and bina_result and has_persian_letters(bina_result.text):
            text = bina_result.text

        confidence = (
            float(sum(line.confidence for line in lines) / len(lines)) if lines else 0.0
        )
        return OcrResult(
            text=text,
            lines=lines,
            confidence=confidence,
            engine="merged/" + "+".join(_short_engine(e) for e in engines),
            details={
                "mode": "detectors-merged",
                "min_confidence": min_conf,
                "line_count": len(lines),
                "word_count": len(words),
                "bina": (bina_result.details if bina_result else {}),
            },
            words=words,
        )

    def _run_easyocr(self, image_bgr: np.ndarray, variant: str) -> OcrResult:
        assert self._easy is not None
        detections = self._easy.readtext(
            image_bgr,
            detail=1,
            paragraph=False,
            decoder="beamsearch",
            beamWidth=8,
            batch_size=1,
            contrast_ths=0.05,
            adjust_contrast=0.7,
            text_threshold=0.55,
            low_text=0.35,
            link_threshold=0.25,
            canvas_size=3200,
            mag_ratio=1.8,
            slope_ths=0.2,
            ycenter_ths=0.5,
            height_ths=0.5,
            width_ths=0.7,
            add_margin=0.12,
        )

        lines: List[LineResult] = []
        for item in detections:
            if len(item) < 3:
                continue
            box, raw_text, score = item[0], item[1], float(item[2])
            # EasyOCR fa already emits logical order — do not pred_reverse.
            text = _normalize_ocr_token(str(raw_text), visual_order=False)
            if not is_meaningful_persian(text):
                continue
            lines.append(
                LineResult(
                    text=hazm_normalize(text),
                    confidence=score,
                    box=[[float(x), float(y)] for x, y in box],
                )
            )

        lines = sort_rtl_lines(lines)
        text = "\n".join(line.text for line in lines).strip()
        confidence = (
            float(sum(line.confidence for line in lines) / len(lines)) if lines else 0.0
        )
        return OcrResult(
            text=text,
            lines=lines,
            confidence=confidence,
            engine=f"easyocr-fa/{variant}",
            details={"variant": variant, "line_count": len(lines)},
        )

    def _run_paddle(self, image_bgr: np.ndarray, variant: str) -> OcrResult:
        assert self._paddle is not None
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temp_path = handle.name
            cv2.imwrite(temp_path, image_bgr)

        try:
            outputs = list(self._paddle.predict(temp_path))
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

        lines: List[LineResult] = []
        for page in outputs:
            payload = _paddle_payload(page)
            texts = [str(value) for value in payload.get("rec_texts", [])]
            scores = [float(value) for value in payload.get("rec_scores", [0.0] * len(texts))]
            boxes = payload.get("rec_polys") or payload.get("rec_boxes") or []

            for index, raw_text in enumerate(texts):
                # arabic_PP-OCRv5 (lang=fa) returns logical Persian; reversing mangled names
                # into digit-looking / reversed tokens like یلع instead of علی.
                text = _normalize_ocr_token(raw_text, visual_order=False)
                if not is_meaningful_persian(text):
                    continue
                box = _normalize_box(boxes[index]) if index < len(boxes) else None
                score = scores[index] if index < len(scores) else 0.0
                lines.append(LineResult(text=hazm_normalize(text), confidence=score, box=box))

        lines = sort_rtl_lines(lines)
        text = "\n".join(line.text for line in lines).strip()
        confidence = (
            float(sum(line.confidence for line in lines) / len(lines)) if lines else 0.0
        )
        return OcrResult(
            text=text,
            lines=lines,
            confidence=confidence,
            engine=f"paddleocr-fa/{variant}",
            details={"variant": variant, "line_count": len(lines)},
        )


def _build_words(
    *,
    classic_lines: List[LineResult],
    bina_words: List[WordResult],
    vision_lines: List[LineResult],
    min_conf: float,
) -> List[WordResult]:
    """Prefer Persian-letter tokens from classic OCR; keep Bina boxes when text matches."""
    pool: List[WordResult] = []

    for line in classic_lines + vision_lines:
        for token in _split_tokens(line.text):
            if not token or not has_persian_letters(token, min_letters=2):
                continue
            if line.confidence < min_conf:
                continue
            pool.append(
                WordResult(
                    text=token,
                    confidence=line.confidence,
                    box=line.box,
                    row=int(line.row or 0),
                )
            )

    for word in bina_words:
        if not has_persian_letters(word.text, min_letters=2):
            continue
        if word.confidence < min_conf:
            continue
        pool.append(word)

    # Deduplicate by text, keep highest confidence / boxed entry.
    best: dict[str, WordResult] = {}
    for word in pool:
        key = word.text
        prev = best.get(key)
        if prev is None:
            best[key] = word
            continue
        score = (1 if word.box else 0, word.confidence, has_persian_letters(word.text))
        prev_score = (1 if prev.box else 0, prev.confidence, has_persian_letters(prev.text))
        if score >= prev_score:
            best[key] = word
    ordered = sorted(
        best.values(),
        key=lambda w: (w.row, -(w.confidence), w.text),
    )
    return ordered


def _split_tokens(text: str) -> List[str]:
    cleaned = hazm_normalize(normalize_persian(text or ""))
    if not cleaned:
        return []
    parts = re.findall(
        r"[\u0600-\u06FF]{2,}(?:[‌\-][\u0600-\u06FF]+)*|[0-9۰-۹]{2,}",
        cleaned,
    )
    return [hazm_normalize(p) for p in parts if p.strip()]


def _is_digit_noise(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    if has_persian_letters(cleaned):
        return False
    if is_digits_only(cleaned):
        return True
    return bool(_DIGITS_ONLY.match(cleaned))


def _persian_letter_count(text: str) -> int:
    return len(_ARABIC_SCRIPT.findall(text or ""))


def _short_engine(name: str) -> str:
    return (
        name.split("/")[0]
        .replace("easyocr-fa", "easy")
        .replace("paddleocr-fa", "paddle")
        .replace("bina-0.2-bootstrap", "bina")
        .replace("bina-0.2", "bina")
    )


def _dedupe_lines(lines: List[LineResult]) -> List[LineResult]:
    pool = sorted(lines, key=lambda line: line.confidence, reverse=True)
    unique: List[LineResult] = []
    for line in pool:
        cx, cy, height = _line_center(line)
        duplicate = False
        for kept in list(unique):
            kx, ky, kh = _line_center(kept)
            if abs(cy - ky) <= 0.55 * max(height, kh) and abs(cx - kx) <= 1.2 * max(height, kh):
                if (
                    _persian_letter_count(line.text) > _persian_letter_count(kept.text)
                    or (
                        len(line.text) > len(kept.text)
                        and line.confidence >= kept.confidence
                    )
                ):
                    unique.remove(kept)
                    unique.append(line)
                duplicate = True
                break
        if not duplicate:
            unique.append(line)
    return sort_rtl_lines(unique)


def _line_center(line: LineResult) -> tuple:
    if not line.box:
        return (0.0, 0.0, 1.0)
    xs = [point[0] for point in line.box]
    ys = [point[1] for point in line.box]
    return (sum(xs) / len(xs), sum(ys) / len(ys), max(max(ys) - min(ys), 1.0))


def _merge_exportable_lines(
    candidates: List[OcrResult], min_confidence: float
) -> Optional[OcrResult]:
    pool: List[LineResult] = []
    engines: List[str] = []
    for candidate in candidates:
        engines.append(candidate.engine)
        for line in candidate.lines:
            if line.confidence >= min_confidence and is_meaningful_persian(line.text):
                # Prefer letter-bearing lines; still keep high-conf IDs.
                pool.append(line)

    if not pool:
        scored = [
            c
            for c in candidates
            if c.lines and _persian_letter_count(c.text) > 0
        ] or [c for c in candidates if c.lines]
        if not scored:
            return None
        best = max(
            scored,
            key=lambda item: (
                _persian_letter_count(item.text),
                item.confidence,
                len(item.text),
            ),
        )
        pool = [
            line
            for line in best.lines
            if line.confidence >= min_confidence and is_meaningful_persian(line.text)
        ]
        engines = [best.engine]
        if not pool:
            return OcrResult(
                text="",
                lines=[],
                confidence=0.0,
                engine=best.engine,
                details={"confidence_floor_applied": True, "line_count": 0},
            )

    ordered = _dedupe_lines(pool)
    text = "\n".join(line.text for line in ordered).strip()
    confidence = float(sum(line.confidence for line in ordered) / len(ordered))
    short = sorted({_short_engine(name) for name in engines})
    return OcrResult(
        text=text,
        lines=ordered,
        confidence=confidence,
        engine="merged/" + "+".join(short),
        details={
            "confidence_floor_applied": True,
            "line_count": len(ordered),
            "source_engines": engines,
        },
    )


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


def _normalize_ocr_token(text: str, visual_order: bool = False) -> str:
    text = normalize_persian(text)
    if visual_order and _ARABIC_SCRIPT.search(text):
        text = pred_reverse(text)
    return hazm_normalize(text)


def sort_rtl_lines(lines: List[LineResult]) -> List[LineResult]:
    if not lines:
        return []

    enriched: List[tuple] = []
    for line in lines:
        if not line.box:
            enriched.append((0.0, 0.0, 1.0, line))
            continue
        ys = [point[1] for point in line.box]
        xs = [point[0] for point in line.box]
        y_center = sum(ys) / len(ys)
        x_center = sum(xs) / len(xs)
        height = max(ys) - min(ys) or 1.0
        enriched.append((y_center, x_center, height, line))

    enriched.sort(key=lambda item: item[0])
    rows: List[List[tuple]] = []
    for item in enriched:
        if not rows:
            rows.append([item])
            continue
        row = rows[-1]
        mean_y = sum(part[0] for part in row) / len(row)
        mean_h = sum(part[2] for part in row) / len(row)
        if abs(item[0] - mean_y) <= 0.55 * max(item[2], mean_h):
            row.append(item)
        else:
            rows.append([item])

    ordered: List[LineResult] = []
    for row in rows:
        row.sort(key=lambda item: item[1], reverse=True)
        for _, _, _, line in row:
            ordered.append(line)
    return ordered


_ocr_service: Optional[PersianOcrService] = None


def get_ocr_service() -> PersianOcrService:
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = PersianOcrService()
    return _ocr_service
