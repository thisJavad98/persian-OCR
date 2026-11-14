"""Semantic Persian / Nasta'liq OCR for deceased-list documents.

Prefers cloud vision (OpenAI / Anthropic / Gemini) when configured; falls back
to local Ollama vision models.
"""

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

from app.services.cloud_ai import get_cloud_ai
from app.services.death_records import (
    DeathExtractResult,
    build_death_extract,
    merge_death_extracts,
)
from app.services.persian_text import (
    hazm_normalize,
    normalize_persian,
    pred_reverse,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen2.5vl:3b"
OLLAMA_URL = "http://127.0.0.1:11434"

_PROMPT = """You are an expert OCR / document transcription system for ANY image content.

Your job is FAITHFUL, COMPLETE transcription of EVERYTHING visible in the image —
printed or handwritten, Persian/Farsi (including Nasta'liq), Arabic, Latin, digits,
punctuation, tables, headers, stamps, notes, and labels. Do NOT summarize. Do NOT invent.

Return ONLY valid JSON (no markdown):
{
  "document_type": "general",
  "text": "FULL page transcript, line breaks preserved, reading order top-to-bottom",
  "lines": ["every visible text line in order", "line 2", "..."],
  "words": ["every visible word/token in reading order"],
  "confidence": 0.0,
  "row_count_estimate": 0,
  "records": [],
  "names": []
}

Hard rules:
- "text" MUST be a near-exact transcript of the page as written (same wording/numbers).
- "lines" MUST list EVERY visible text line (headers, body, footnotes, stamps, numbers).
- "words" MUST list visible words/tokens (Persian, Latin, digits) without dropping content.
- Preserve original wording; fix only obvious OCR letter confusions when certain.
- Keep digits, codes, dates, punctuation, and short tokens — do not filter them out.
- Output Persian/Arabic in LOGICAL reading order (not visual-reversed glyphs).
- Scan thoroughly: top-to-bottom, faint text, crowded areas, edges, multi-column if any.
- Do NOT invent people, rows, or fields that are not visible.
- Do NOT output Chinese garbage or unrelated filler.
- Set document_type to "death_list" ONLY if the image is clearly a deceased / متوفیان list.
  For death_list images ALSO fill records[] with one object per person:
  {
    "row_index": 1,
    "deceased_name": "...",
    "deceased_name_alternatives": [],
    "national_id": "",
    "father_name": "",
    "father_name_alternatives": [],
    "cause_of_death": "",
    "physician_name": "",
    "physician_name_alternatives": [],
    "confidence": 0.0,
    "raw_line": "full visible text of that row"
  }
  and set row_count_estimate / names accordingly.
- For all other documents: document_type="general", records=[], names=[].
- confidence is 0..1 for overall transcription quality.
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
        self._cloud_label: str = ""

    def available(self) -> bool:
        cloud = get_cloud_ai()
        if cloud.available:
            self._cloud_label = cloud.label
            self.model = cloud.label
            self._ready = True
            return True
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
            raise RuntimeError("Vision OCR is not available (cloud AI key or Ollama required)")

        import os

        rgb = image.convert("RGB")
        backend = "cloud" if get_cloud_ai().available else "ollama"
        # Fast+accurate default: one full-page pass. Extra tiles only when needed.
        max_passes = int(os.getenv("OCR_VISION_MAX_PASSES", "1") or "1")
        crops = _page_crops(rgb, max_passes=max_passes, backend=backend)
        parsed_parts: List[Dict[str, Any]] = []
        raw_blobs: List[str] = []

        def _run_crop(label: str, crop: Image.Image) -> Tuple[Dict[str, Any], str]:
            if backend == "cloud":
                return self._run_cloud(crop, pass_label=label)
            return self._run_once(crop, pass_label=label)

        # First pass is always the full page (crops[0]).
        first_label, first_crop = crops[0]
        first_parsed, first_raw = _run_crop(first_label, first_crop)
        parsed_parts.append(first_parsed)
        raw_blobs.append(first_raw)

        # Adaptive extra passes: only if first result looks thin on a tall page.
        extra = crops[1:]
        if extra and _needs_extra_vision_pass(first_parsed, rgb.size):
            from concurrent.futures import ThreadPoolExecutor, as_completed

            workers = min(2, len(extra))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_run_crop, label, crop): label for label, crop in extra
                }
                for fut in as_completed(futures):
                    parsed, raw_text = fut.result()
                    parsed_parts.append(parsed)
                    raw_blobs.append(raw_text)
        elif max_passes > 1 and extra and os.getenv("OCR_VISION_FORCE_TILES", "0") == "1":
            for label, crop in extra:
                parsed, raw_text = _run_crop(label, crop)
                parsed_parts.append(parsed)
                raw_blobs.append(raw_text)

        # Prefer richest full-page transcript across passes; keep ALL unique lines/words.
        best_parsed = max(
            parsed_parts,
            key=lambda part: (
                len(str(part.get("text") or "")),
                len(part.get("lines") or []),
                len(part.get("records") or []),
            ),
        ) if parsed_parts else {}

        all_lines: List[str] = []
        seen_lines = set()
        all_words: List[str] = []
        seen_words = set()
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
            for word in part.get("words") or []:
                cleaned = hazm_normalize(normalize_persian(str(word)))
                if cleaned and cleaned not in seen_words:
                    seen_words.add(cleaned)
                    all_words.append(cleaned)

        full_text = hazm_normalize(
            normalize_persian(str(best_parsed.get("text") or ""))
        )
        if not full_text and all_lines:
            full_text = "\n".join(all_lines)

        death_extract = None
        if _looks_like_death_list(parsed_parts, best_parsed):
            extracts = [
                build_death_extract(
                    _normalize_parsed_records(part),
                    overall_confidence=float(part.get("confidence") or 0.85),
                )
                for part in parsed_parts
                if _part_has_death_signal(part)
            ]
            if extracts:
                death_extract = merge_death_extracts(extracts)
                for rec in death_extract.records:
                    if rec.raw_line and rec.raw_line not in seen_lines:
                        seen_lines.add(rec.raw_line)
                        all_lines.append(rec.raw_line)
                # Prefer the literal page transcript over the death summary template.
                if not full_text and death_extract.summary_text:
                    full_text = death_extract.summary_text

        combined: Dict[str, Any] = {
            "document_type": (
                "death_list"
                if death_extract and death_extract.records
                else str(best_parsed.get("document_type") or "general")
            ),
            "text": full_text,
            "lines": all_lines,
            "words": all_words,
            "names": list(best_parsed.get("names") or []),
            "confidence": float(best_parsed.get("confidence") or 0.85),
            "row_count_estimate": max(
                int(best_parsed.get("row_count_estimate") or 0),
                len(death_extract.records) if death_extract else 0,
                len(all_lines),
            ),
            "records": (
                death_extract.as_dict().get("records")
                if death_extract
                else []
            ),
        }
        if death_extract and not combined["names"]:
            combined["names"] = [
                rec.deceased_name.final_name
                for rec in death_extract.records
                if rec.deceased_name.final_name
            ]
            combined["confidence"] = max(
                combined["confidence"], death_extract.confidence or 0.0
            )

        result = _to_result(
            combined,
            model=self.model,
            raw={
                "responses": raw_blobs,
                "passes": len(crops),
                "line_count": len(all_lines),
                "word_count": len(all_words),
                "backend": backend,
                "document_type": combined.get("document_type"),
            },
            death_extract=death_extract,
        )
        return result

    def _run_cloud(self, image: Image.Image, *, pass_label: str) -> Tuple[Dict[str, Any], str]:
        cloud = get_cloud_ai()
        prompt = (
            _PROMPT
            + f"\nPass label: {pass_label}. Transcribe every visible text in this crop exactly."
        )
        system = (
            "You are a high-accuracy OCR engine for any document image. "
            "Transcribe all visible text faithfully. Return ONLY valid JSON."
        )
        raw_text = cloud.complete_vision(
            prompt,
            image,
            system=system,
            json_mode=True,
            timeout=min(self.timeout, 120.0),
            max_tokens=4096,
        )
        self.model = cloud.label
        return _parse_json_response(raw_text), raw_text

    def _run_once(self, image: Image.Image, *, pass_label: str) -> Tuple[Dict[str, Any], str]:
        import os

        buffered = BytesIO()
        rgb = image.convert("RGB")
        # Smaller side = much faster local VL; 1536 keeps most document detail.
        max_side = int(os.getenv("OCR_VISION_MAX_SIDE", "1536") or "1536")
        w, h = rgb.size
        scale = min(1.0, max_side / float(max(w, h)))
        if scale < 1.0:
            rgb = rgb.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS
            )
        rgb.save(buffered, format="JPEG", quality=88)
        b64 = base64.b64encode(buffered.getvalue()).decode("ascii")

        prompt = (
            _PROMPT
            + f"\nPass label: {pass_label}. Transcribe every visible text in this crop exactly."
        )
        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.0,
                "num_predict": int(os.getenv("OCR_VISION_NUM_PREDICT", "3072") or "3072"),
            },
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
            body = response.json()
        raw_text = body.get("response") or ""
        return _parse_json_response(raw_text), raw_text


def _needs_extra_vision_pass(parsed: Dict[str, Any], size: Tuple[int, int]) -> bool:
    """Decide whether extra tiles are worth the latency."""
    width, height = size
    if height < 1400:
        return False
    text = str(parsed.get("text") or "").strip()
    lines = parsed.get("lines") or []
    words = parsed.get("words") or []
    records = parsed.get("records") or []
    # Strong first pass → stop (keeps accuracy without multi-minute tiling).
    if len(text) >= 180 or len(lines) >= 8 or len(words) >= 20 or len(records) >= 3:
        return False
    # Thin result on a tall page → one more pass can recover missed rows.
    return len(text) < 80 and len(lines) < 4


def _page_crops(
    image: Image.Image,
    *,
    max_passes: int = 1,
    backend: str = "ollama",
) -> List[Tuple[str, Image.Image]]:
    """Full page first; optional overlapping tiles only when max_passes > 1."""
    crops: List[Tuple[str, Image.Image]] = [("full", image)]
    if max_passes <= 1:
        return crops

    width, height = image.size
    if height < 900:
        return crops

    # Cloud models usually read full pages well — at most one extra mid/bottom tile.
    if backend == "cloud" or max_passes == 2:
        band = int(height * 0.55)
        tops = [max(0, height - band)]
    elif height >= 1600:
        band = int(height * 0.42)
        step = int(height * 0.32)
        tops = [step, max(0, height - band)]
    else:
        band = int(height * 0.58)
        tops = [max(0, int(height * 0.35))]

    seen = {(0, height)}
    for index, top in enumerate(tops, start=1):
        if len(crops) >= max_passes:
            break
        top = max(0, min(top, height - 1))
        bottom = min(height, top + band)
        key = (top, bottom)
        if key in seen or bottom - top < 160:
            continue
        seen.add(key)
        crops.append((f"tile-{index}", image.crop((0, top, width, bottom))))
    return crops


def _part_has_death_signal(part: Dict[str, Any]) -> bool:
    doc_type = str(part.get("document_type") or "").lower()
    if doc_type in {"death_list", "deceased", "متوفیان", "فهرست متوفیان"}:
        return True
    records = part.get("records") or []
    if not isinstance(records, list) or not records:
        return False
    # Require at least one record with a death-ish field, not just raw noise.
    for item in records:
        if not isinstance(item, dict):
            continue
        if any(
            str(item.get(key) or "").strip()
            for key in (
                "deceased_name",
                "national_id",
                "father_name",
                "cause_of_death",
                "physician_name",
                "raw_line",
            )
        ):
            return True
    return False


def _looks_like_death_list(
    parsed_parts: List[Dict[str, Any]], best_parsed: Dict[str, Any]
) -> bool:
    if _part_has_death_signal(best_parsed):
        return True
    return any(_part_has_death_signal(part) for part in parsed_parts)


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

    # Only build death extract when the page is a deceased list — never invent people
    # from arbitrary document lines.
    if death_extract is None and _part_has_death_signal(parsed):
        death_extract = build_death_extract(parsed, overall_confidence=confidence)

    lines_raw = parsed.get("lines") or []
    if isinstance(lines_raw, str):
        lines_raw = [part for part in lines_raw.splitlines() if part.strip()]
    # Keep nearly all lines for general OCR (digits, Latin, short tokens).
    lines = [
        _logical_persian(str(item))
        for item in lines_raw
        if str(item or "").strip()
    ]
    lines = [line for line in lines if line]
    if not lines and death_extract and death_extract.summary_text:
        lines = death_extract.summary_text.splitlines()

    text = _logical_persian(str(parsed.get("text") or ""))
    if not text and lines:
        text = "\n".join(lines)
    if not text and death_extract and death_extract.summary_text:
        text = death_extract.summary_text

    names = [
        _logical_persian(str(n))
        for n in (parsed.get("names") or [])
        if str(n or "").strip()
    ]
    names = [n for n in names if n]
    if not names and death_extract:
        names = [
            rec.deceased_name.final_name
            for rec in death_extract.records
            if rec.deceased_name.final_name
        ]

    if text and confidence < 0.8:
        confidence = max(confidence, 0.8)
    if death_extract and death_extract.records:
        confidence = max(confidence, death_extract.confidence, 0.8)

    return VisionOcrResult(
        text=text,
        lines=lines or [line for line in text.splitlines() if line.strip()],
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
