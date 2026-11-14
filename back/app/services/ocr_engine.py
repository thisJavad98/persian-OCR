"""Compatibility facade — OCR is AI-only via ai_ocr."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PIL import Image

from app.services.ai_ocr import AiOcrResult, get_ai_ocr


@dataclass
class LineResult:
    text: str
    confidence: float
    box: Optional[List[List[float]]] = None
    row: Optional[int] = None


@dataclass
class WordResult:
    text: str
    confidence: float
    box: Optional[List[List[float]]] = None
    row: int = 0
    line_index: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "box": self.box,
            "row": self.row,
            "line_index": self.line_index,
        }


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
    sentences: List[str] = field(default_factory=list)


class PersianOcrService:
    """Thin wrapper around AiOcrService for existing imports."""

    def __init__(self) -> None:
        self._ai = get_ai_ocr()

    @property
    def engines(self) -> List[str]:
        return self._ai.engines

    @property
    def ready(self) -> bool:
        return self._ai.ready

    @property
    def init_error(self) -> Optional[str]:
        return self._ai.init_error

    def warmup(self) -> None:
        self._ai.warmup()

    def extract(self, image: Image.Image) -> OcrResult:
        result = self._ai.extract(image)
        return _from_ai(result)


def _from_ai(result: AiOcrResult) -> OcrResult:
    conf = float(result.confidence or 0.9)
    lines = [
        LineResult(text=line, confidence=conf, row=index)
        for index, line in enumerate(result.lines, start=1)
    ]
    words = [
        WordResult(text=word, confidence=conf, row=0, line_index=index)
        for index, word in enumerate(result.words)
    ]
    details = dict(result.details or {})
    details["sentences"] = list(result.sentences or [])
    return OcrResult(
        text=result.text,
        lines=lines,
        confidence=conf,
        engine=result.engine,
        details=details,
        words=words,
        sentences=list(result.sentences or []),
        death_records=None,
        table_rows=None,
    )


_ocr_service: Optional[PersianOcrService] = None


def get_ocr_service() -> PersianOcrService:
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = PersianOcrService()
    return _ocr_service


def reset_ocr_service() -> None:
    global _ocr_service
    from app.services.ai_ocr import reset_ai_ocr

    reset_ai_ocr()
    _ocr_service = None
