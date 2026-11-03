"""Semantic Persian / Nasta'liq OCR for deceased-list documents via Ollama."""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import httpx
from PIL import Image

from app.services.death_records import (
    DeathExtractResult,
    build_death_extract,
    merge_death_extracts,
)
from app.services.persian_text import (
    filter_meaningful_lines,
    hazm_normalize,
    normalize_persian,
    pred_reverse,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen2.5vl:3b"
OLLAMA_URL = "http://127.0.0.1:11434"

_PROMPT = """You are an expert forensic document reader for Persian (Farsi) Nasta'liq handwriting.

This image is a LIST OF DECEASED PEOPLE. Your job is COMPLETE recall:
extract EVERY person / EVERY row / EVERY item visible in the image. Do not skip rows.

For EACH deceased person extract:
- deceased_name (نام متوفی)
- national_id (کد ملی / شماره شناسنامه) digits only when visible
- father_name (نام پدر)
- cause_of_death (علت فوت)
- physician_name (نام پزشک معالج / پزشک)

Return ONLY valid JSON (no markdown):
{
  "row_count_estimate": 0,
  "records": [
    {
      "row_index": 1,
      "deceased_name": "نام کامل متوفی",
      "deceased_name_alternatives": ["نام مشابه در صورت ابهام"],
      "national_id": "0012345678",
      "father_name": "نام پدر",
      "father_name_alternatives": [],
      "cause_of_death": "علت فوت",
      "physician_name": "نام پزشک",
      "physician_name_alternatives": [],
      "confidence": 0.0,
      "raw_line": "متن خام همان ردیف"
    }
  ],
  "text": "خلاصه همه ردیف‌ها",
  "lines": ["خط ۱", "خط ۲"],
  "names": ["همه نام‌ها"],
  "confidence": 0.0
}

Hard rules:
- Detect ALL items on the image. records length must match the number of people/rows you can see.
- Set row_count_estimate to the count of people/rows you can see BEFORE writing records.
- Then emit one records[] entry per person — records.length MUST equal row_count_estimate.
- If a field is unreadable, keep the record and leave that field empty — NEVER drop the whole row.
- Put the full visible text of that row into raw_line even when fields are partial.
- Also fill "lines" with EVERY visible text line on the page (headers, notes, names, numbers).
- Also fill "text" with the complete page transcript.
- Scan top-to-bottom thoroughly, including faint, crowded, or edge rows.
- Output Persian in LOGICAL reading order.
- If a name is ambiguous, put best name in deceased_name and near matches in *_alternatives.
- Do not invent people that are not visible.
- Do not output Chinese or Latin garbage.
- confidence is 0..1.
"""


@dataclass
class VisionOcrResult:
    text: str
    lines: List[str] = field(default_factory=list)
    table: List[List[str]] = field(default_factory=list)
    names: List[str] = field(default_factory=list)
    confidence: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)
    model: str = DEFAULT_MODEL
    death_extract: Optional[DeathExtractResult] = None


class VisionPersianOcr:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = OLLAMA_URL,
        timeout: float = 300.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._ready: Optional[bool] = None

    def available(self) -> bool:
        if self._ready is not None:
            return self._ready
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            response.raise_for_status()
            models = [m.get("name", "") for m in response.json().get("models", [])]
            self._ready = any(
                self.model in name or name.startswith(self.model.split(":")[0])
                for name in models
            )
            if not self._ready and models:
                for name in models:
                    if "vl" in name or "vision" in name or "llava" in name:
                        self.model = name
                        self._ready = True
                        break
        except Exception as exc:
            logger.warning("Ollama not available: %s", exc)
            self._ready = False
        return bool(self._ready)

    def extract(self, image: Image.Image) -> VisionOcrResult:
        if not self.available():
            raise RuntimeError("Vision OCR (Ollama) is not available")

        rgb = image.convert("RGB")
        crops = _page_crops(rgb)
        parsed_parts: List[Dict[str, Any]] = []
        raw_blobs: List[str] = []

        for label, crop in crops:
            parsed, raw_text = self._run_once(crop, pass_label=label)
            parsed_parts.append(parsed)
            raw_blobs.append(raw_text)

        # Merge all passes so no row is lost.
        extracts = [
            build_death_extract(
                _normalize_parsed_records(part),
                overall_confidence=float(part.get("confidence") or 0.85),
            )
            for part in parsed_parts
        ]
        death_extract = merge_death_extracts(extracts)

        # Prefer richest text/lines across passes; keep ALL unique lines.
        best_parsed = max(
            parsed_parts,
            key=lambda part: (
                len(part.get("records") or []),
                len(str(part.get("text") or "")),
            ),
        ) if parsed_parts else {}
        combined = dict(best_parsed)
        all_lines: List[str] = []
        seen_lines = set()
        for part in parsed_parts:
            for line in part.get("lines") or []:
                cleaned = hazm_normalize(normalize_persian(str(line)))
                if cleaned and cleaned not in seen_lines:
                    seen_lines.add(cleaned)
                    all_lines.append(cleaned)
            text_block = str(part.get("text") or "")
            for line in text_block.splitlines():
                cleaned = hazm_normalize(normalize_persian(line))
                if cleaned and cleaned not in seen_lines:
                    seen_lines.add(cleaned)
                    all_lines.append(cleaned)
        for rec in death_extract.records:
            if rec.raw_line and rec.raw_line not in seen_lines:
                seen_lines.add(rec.raw_line)
                all_lines.append(rec.raw_line)

        # Rebuild extract once more with full line list so supplemental rows appear.
        payload = death_extract.as_dict()
        payload["lines"] = all_lines
        payload["text"] = "\n".join(all_lines) if all_lines else death_extract.summary_text
        death_extract = build_death_extract(
            payload, overall_confidence=death_extract.confidence or 0.85
        )
        combined = death_extract.as_dict()
        combined["lines"] = all_lines
        combined["text"] = death_extract.summary_text or "\n".join(all_lines)
        combined["names"] = [
            rec.deceased_name.final_name
            for rec in death_extract.records
            if rec.deceased_name.final_name
        ]
        combined["confidence"] = death_extract.confidence or float(
            best_parsed.get("confidence") or 0.85
        )
        combined["row_count_estimate"] = max(
            int(best_parsed.get("row_count_estimate") or 0),
            len(death_extract.records),
            len(all_lines),
        )

        result = _to_result(
            combined,
            model=self.model,
            raw={"responses": raw_blobs, "passes": len(crops), "line_count": len(all_lines)},
            death_extract=death_extract,
        )
        return result

    def _run_once(self, image: Image.Image, *, pass_label: str) -> Tuple[Dict[str, Any], str]:
        buffered = BytesIO()
        rgb = image.convert("RGB")
        max_side = 2000
        w, h = rgb.size
        scale = min(1.0, max_side / float(max(w, h)))
        if scale < 1.0:
            rgb = rgb.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS
            )
        rgb.save(buffered, format="JPEG", quality=95)
        b64 = base64.b64encode(buffered.getvalue()).decode("ascii")

        prompt = _PROMPT + f"\nPass label: {pass_label}. Extract every visible person in this crop."
        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.0,
                "num_predict": 6144,
            },
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
            body = response.json()
        raw_text = body.get("response") or ""
        return _parse_json_response(raw_text), raw_text


def _page_crops(image: Image.Image) -> List[Tuple[str, Image.Image]]:
    """Full page + overlapping vertical tiles for dense lists."""
    crops: List[Tuple[str, Image.Image]] = [("full", image)]
    width, height = image.size
    # Tile early so short/medium lists still get multi-pass recall.
    if height < 500:
        return crops

    if height >= 1600:
        band = int(height * 0.38)
        step = int(height * 0.26)
        tops = [0, step, step * 2, max(0, height - band)]
    else:
        band = int(height * 0.58)
        step = int(height * 0.38)
        tops = [0, step, max(0, height - band)]

    seen = set()
    for index, top in enumerate(tops, start=1):
        top = max(0, min(top, height - 1))
        bottom = min(height, top + band)
        key = (top, bottom)
        if key in seen or bottom - top < 160:
            continue
        seen.add(key)
        crops.append((f"tile-{index}", image.crop((0, top, width, bottom))))
    return crops


def _parse_json_response(raw_text: str) -> Dict[str, Any]:
    text = raw_text.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return {"text": normalize_persian(text)}
    return {"text": normalize_persian(text)}


_COMMON_MARKERS = (
    "نام",
    "پدر",
    "پزشک",
    "علت",
    "فوت",
    "متوفی",
    "محمد",
    "علی",
    "حسین",
    "رضا",
)


def _score_persian_logic(text: str) -> int:
    score = 0
    for marker in _COMMON_MARKERS:
        if marker in text:
            score += 2
    for token in re.findall(r"[\u0600-\u06FF]{2,}", text):
        if token[-1] in "اهیةةکگ":
            score += 1
    return score


def _logical_persian(value: str) -> str:
    cleaned = normalize_persian(str(value or ""))
    if not cleaned:
        return ""
    persian_letters = len(re.findall(r"[\u0600-\u06FF]", cleaned))
    if persian_letters < 2:
        return hazm_normalize(cleaned)
    reversed_text = pred_reverse(cleaned)
    if _score_persian_logic(reversed_text) > _score_persian_logic(cleaned):
        cleaned = reversed_text
    return hazm_normalize(cleaned)


def _normalize_parsed_records(parsed: Dict[str, Any]) -> Dict[str, Any]:
    records = parsed.get("records")
    if not isinstance(records, list):
        return parsed
    normalized = []
    for item in records:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        for key in (
            "deceased_name",
            "father_name",
            "physician_name",
            "cause_of_death",
            "raw_line",
        ):
            if key in row and not isinstance(row[key], dict):
                row[key] = _logical_persian(str(row[key]))
        for key in (
            "deceased_name_alternatives",
            "father_name_alternatives",
            "physician_name_alternatives",
        ):
            alts = row.get(key) or []
            if isinstance(alts, list):
                row[key] = [_logical_persian(str(a)) for a in alts if str(a).strip()]
        normalized.append(row)
    parsed = dict(parsed)
    parsed["records"] = normalized
    return parsed


def _to_result(
    parsed: Dict[str, Any],
    model: str,
    raw: Dict[str, Any],
    death_extract: Optional[DeathExtractResult] = None,
) -> VisionOcrResult:
    parsed = _normalize_parsed_records(parsed)
    try:
        confidence = float(parsed.get("confidence", 0.85))
    except (TypeError, ValueError):
        confidence = 0.85
    confidence = max(0.0, min(confidence, 1.0))

    if death_extract is None:
        death_extract = build_death_extract(parsed, overall_confidence=confidence)

    lines_raw = parsed.get("lines") or []
    if isinstance(lines_raw, str):
        lines_raw = [part for part in lines_raw.splitlines() if part.strip()]
    lines = filter_meaningful_lines([_logical_persian(str(item)) for item in lines_raw])
    if not lines and death_extract.summary_text:
        lines = death_extract.summary_text.splitlines()

    text = _logical_persian(str(parsed.get("text") or "")) or death_extract.summary_text
    names = filter_meaningful_lines([_logical_persian(str(n)) for n in (parsed.get("names") or [])])
    if not names:
        names = [
            rec.deceased_name.final_name
            for rec in death_extract.records
            if rec.deceased_name.final_name
        ]

    if text and confidence < 0.8:
        confidence = max(confidence, 0.8)
    if death_extract.records:
        confidence = max(confidence, death_extract.confidence, 0.8)

    return VisionOcrResult(
        text=text,
        lines=lines or filter_meaningful_lines(text.splitlines()),
        table=[],
        names=names,
        confidence=confidence,
        raw=raw,
        model=model,
        death_extract=death_extract,
    )


_vision: Optional[VisionPersianOcr] = None


def get_vision_ocr() -> VisionPersianOcr:
    global _vision
    if _vision is None:
        import os

        model = os.getenv("VISION_OCR_MODEL", DEFAULT_MODEL)
        base = os.getenv("OLLAMA_URL", OLLAMA_URL)
        _vision = VisionPersianOcr(model=model, base_url=base)
    return _vision
