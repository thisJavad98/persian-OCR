"""High-accuracy AI OCR for Persian / any-script document images.

Quality strategy (local or cloud):
  1) Enhance image for ink clarity
  2) Optional classic OCR draft (Paddle) as hints — never final answer alone
  3) Multi-tile vision transcription in PLAIN TEXT (more reliable than JSON-only)
  4) Structure + proofread pass against the full page
  5) Quality gate — retry tiles if transcript looks empty/garbage
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.services.cloud_ai import (
    CloudAiClient,
    CloudAiConfig,
    get_cloud_ai,
    parse_json_object,
    resolve_cloud_config,
)

logger = logging.getLogger(__name__)

PLAIN_OCR_PROMPT = """OCR this image. Transcribe EVERY visible word exactly.

Rules:
- Output ONLY the transcript text. No markdown. No explanations.
- Keep Persian/Farsi/Arabic in normal reading order.
- Keep digits, punctuation, Latin, and line breaks.
- Do not invent text. Do not summarize.
- If handwriting/Nasta'liq, read carefully letter by letter.
"""

STRUCTURE_PROMPT = """You are an OCR post-processor. Turn the RAW transcript into clean structured JSON.
Fix obvious OCR letter mistakes using context, but do NOT invent missing people or sentences.

RAW TRANSCRIPT:
{raw}

Return ONLY JSON:
{{
  "text": "cleaned full transcript with line breaks",
  "lines": ["line 1", "line 2"],
  "words": ["word1", "word2"],
  "sentences": ["sentence 1"],
  "confidence": 0.0
}}
"""

VERIFY_PROMPT = """Compare the IMAGE with the DRAFT. Produce the most accurate full transcript.

DRAFT:
{draft}

Optional classic-OCR hints (may be noisy):
{hints}

Return ONLY JSON:
{{
  "text": "exact page transcript",
  "lines": ["..."],
  "words": ["..."],
  "sentences": ["..."],
  "confidence": 0.0
}}

Rules:
- Prefer what you SEE in the image over the draft when they conflict.
- Keep all readable words/numbers.
- Persian in logical reading order.
- No markdown outside JSON.
"""


@dataclass
class AiOcrResult:
    text: str
    lines: List[str] = field(default_factory=list)
    words: List[str] = field(default_factory=list)
    sentences: List[str] = field(default_factory=list)
    confidence: float = 0.0
    engine: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class AiOcrService:
    def __init__(self) -> None:
        self._ready: Optional[bool] = None
        self._engines: List[str] = []
        self._init_error: Optional[str] = None
        self._ollama_model: Optional[str] = None

    @property
    def ready(self) -> bool:
        return bool(self.engines)

    @property
    def engines(self) -> List[str]:
        if self._ready is None:
            self.warmup()
        return list(self._engines)

    @property
    def init_error(self) -> Optional[str]:
        return self._init_error

    def warmup(self) -> None:
        engines: List[str] = []
        errors: List[str] = []

        cloud = get_cloud_ai()
        if cloud.available:
            engines.append(cloud.label)
        for cfg in _all_cloud_configs():
            label = f"{cfg.provider}:{cfg.model}"
            if label not in engines:
                engines.append(label)

        ollama = _pick_ollama_vision_model()
        if ollama:
            self._ollama_model = ollama
            engines.append(f"ollama:{ollama}")
        else:
            errors.append("ollama vision model not available")

        self._engines = engines
        self._ready = bool(engines)
        self._init_error = None if engines else "; ".join(errors) or "no AI provider configured"
        logger.info("AI OCR ready: %s", ", ".join(engines) if engines else self._init_error)

    def extract(self, image: Image.Image) -> AiOcrResult:
        if not self.ready:
            self.warmup()
        if not self.ready:
            raise RuntimeError(self._init_error or "No AI OCR provider available")

        enhanced = _prepare_image(image)
        hints = _classic_draft_hints(enhanced)
        engine_chain: List[str] = []

        # 1) Multi-tile plain-text vision OCR (best recall for local VL models).
        tile_texts, tile_engines = self._transcribe_tiles(enhanced)
        engine_chain.extend(tile_engines)
        merged_raw = _merge_tile_texts(tile_texts)

        # 2) If first pass is garbage, force denser tiles and retry.
        if _looks_weak(merged_raw, enhanced.size):
            logger.warning("Weak first OCR pass; retrying with denser tiles")
            dense_texts, dense_engines = self._transcribe_tiles(enhanced, dense=True)
            engine_chain.extend([e + "/dense" for e in dense_engines])
            merged_raw = _merge_tile_texts(tile_texts + dense_texts)

        if hints:
            merged_raw = _merge_tile_texts([merged_raw, hints])

        # 3) Structure into JSON via text model / vision verify.
        structured = self._structure_and_verify(enhanced, merged_raw, hints=hints)
        engine_chain.append(structured["engine"])
        payload = structured["data"]

        normalized = _normalize_payload(payload)
        normalized["text"] = _dedupe_repetition(normalized["text"])
        merged_raw = _dedupe_repetition(merged_raw)

        candidates = [
            normalized["text"],
            merged_raw,
            _dedupe_repetition(hints),
        ]
        best_text = max(candidates, key=lambda t: _quality_score(t, enhanced.size))
        if best_text.strip() and best_text.strip() != normalized["text"].strip():
            normalized = _normalize_payload({"text": best_text, "confidence": 0.7})

        if _looks_like_loop(normalized["text"]) or _looks_weak(normalized["text"], enhanced.size):
            # Prefer classic hints over hallucinated loops when both are weak.
            if hints and _quality_score(hints, enhanced.size) > _quality_score(
                normalized["text"], enhanced.size
            ):
                normalized = _normalize_payload({"text": _dedupe_repetition(hints), "confidence": 0.55})

        confidence = _score_confidence(
            normalized["text"], enhanced.size, normalized.get("confidence")
        )
        warning = None
        if not get_cloud_ai().available and (
            _looks_like_loop(normalized["text"]) or confidence < 0.6
        ):
            warning = (
                "کیفیت مدل محلی کافی نیست. برای دقت بالا OPENAI_API_KEY یا ANTHROPIC/GEMINI "
                "را در back/.env تنظیم کنید (پیشنهاد: gpt-4o)."
            )

        return AiOcrResult(
            text=normalized["text"],
            lines=normalized["lines"],
            words=normalized["words"],
            sentences=normalized["sentences"],
            confidence=confidence,
            engine="+".join(engine_chain),
            details={
                "mode": "ai-high-accuracy",
                "providers": engine_chain,
                "hints_used": bool(hints),
                "raw_transcript": merged_raw[:4000],
                "warning": warning,
                "cloud_recommended": not get_cloud_ai().available,
            },
        )

    def _transcribe_tiles(
        self, image: Image.Image, *, dense: bool = False
    ) -> Tuple[List[str], List[str]]:
        crops = _page_tiles(image, dense=dense)
        texts: List[str] = []
        engines: List[str] = []

        def run_one(label: str, crop: Image.Image) -> Tuple[str, str, str]:
            text, engine = self._plain_ocr(crop, label=label)
            return label, text, engine

        # Cloud can parallelize; local Ollama VL is memory-heavy — stay sequential.
        parallel = get_cloud_ai().available and os.getenv("OCR_PARALLEL_TILES", "1") != "0"
        ordered: Dict[str, Tuple[str, str]] = {}
        if parallel and len(crops) > 1:
            workers = min(2, len(crops))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(run_one, label, crop) for label, crop in crops]
                for fut in as_completed(futures):
                    label, text, engine = fut.result()
                    ordered[label] = (text, engine)
        else:
            for label, crop in crops:
                _label, text, engine = run_one(label, crop)
                ordered[label] = (text, engine)

        for label, _crop in crops:
            text, engine = ordered.get(label, ("", ""))
            if text.strip():
                texts.append(text.strip())
            if engine and engine not in engines:
                engines.append(engine)
        return texts, engines

    def _plain_ocr(self, image: Image.Image, *, label: str) -> Tuple[str, str]:
        prompt = PLAIN_OCR_PROMPT + f"\nRegion: {label}."
        cloud = get_cloud_ai()
        if cloud.available:
            raw = cloud.complete_vision(
                prompt,
                image,
                system="You are a precise OCR engine. Output only the transcript.",
                json_mode=False,
                timeout=120.0,
                max_tokens=3072,
            )
            return _strip_code_fence(raw), cloud.label
        if not self._ollama_model:
            raise RuntimeError("No vision model for plain OCR")
        raw = _ollama_vision_text(image, prompt, self._ollama_model, json_mode=False)
        return _strip_code_fence(raw), f"ollama:{self._ollama_model}"

    def _structure_and_verify(
        self, image: Image.Image, raw_text: str, *, hints: str
    ) -> Dict[str, Any]:
        draft = raw_text.strip() or hints
        cloud = get_cloud_ai()
        verify_on = os.getenv("OCR_AI_VERIFY", "1") != "0"

        if cloud.available and verify_on:
            prompt = VERIFY_PROMPT.format(
                draft=draft[:6000] or "(empty)",
                hints=(hints[:3000] or "(none)"),
            )
            raw = cloud.complete_vision(
                prompt,
                image,
                system="Proofread OCR against the image. Return only JSON.",
                json_mode=True,
                timeout=120.0,
                max_tokens=4096,
            )
            data = parse_json_object(raw)
            if data:
                return {"engine": cloud.label + "/verify", "data": data, "raw": raw}

        # Local path: structure with text prompt (no image) then optional vision verify.
        structure_prompt = STRUCTURE_PROMPT.format(raw=draft[:8000] or "(empty)")
        if cloud.available:
            raw = cloud.complete_text(
                structure_prompt,
                system="Return only JSON for OCR structuring.",
                json_mode=True,
                timeout=60.0,
                max_tokens=3072,
            )
            data = parse_json_object(raw)
            if data:
                return {"engine": cloud.label + "/structure", "data": data, "raw": raw}

        if self._ollama_model and verify_on:
            prompt = VERIFY_PROMPT.format(
                draft=draft[:5000] or "(empty)",
                hints=(hints[:2500] or "(none)"),
            )
            data, raw = _ollama_vision_json(image, prompt, self._ollama_model)
            if data and str(data.get("text") or "").strip():
                return {"engine": f"ollama:{self._ollama_model}/verify", "data": data, "raw": raw}

        # Last resort: build structure locally from raw text.
        return {
            "engine": "local-structure",
            "data": {
                "text": draft,
                "lines": [ln for ln in draft.splitlines() if ln.strip()],
                "confidence": 0.75,
            },
            "raw": draft,
        }


def _prepare_image(image: Image.Image) -> Image.Image:
    """Upscale + contrast so handwriting strokes are clearer for VL models."""
    # Local 7B on 16GB RAM: keep side modest. Cloud can go higher.
    cloud = False
    try:
        cloud = get_cloud_ai().available
    except Exception:
        cloud = False
    default_side = "2048" if cloud else "1400"
    max_side = int(os.getenv("OCR_MAX_IMAGE_SIDE", default_side) or default_side)
    min_side = min(1200 if cloud else 1000, max_side)
    try:
        from app.services.preprocess import enhance_for_ocr

        return enhance_for_ocr(
            image.convert("RGB"), min_side=min_side, max_side=max_side
        )
    except Exception:
        rgb = image.convert("RGB")
        w, h = rgb.size
        shortest = min(w, h)
        if shortest < min_side:
            scale = min_side / float(shortest)
            if max(w, h) * scale > max_side:
                scale = max_side / float(max(w, h))
            rgb = rgb.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        gray = ImageOps.autocontrast(rgb.convert("L"))
        gray = ImageEnhance.Contrast(gray).enhance(1.35)
        gray = gray.filter(ImageFilter.UnsharpMask(radius=1.4, percent=140, threshold=2))
        return Image.merge("RGB", (gray, gray, gray))


def _classic_draft_hints(image: Image.Image) -> str:
    """Optional PaddleOCR-fa draft used only as hints for the AI."""
    if os.getenv("OCR_CLASSIC_HINTS", "1") == "0":
        return ""
    try:
        import tempfile

        import cv2
        import numpy as np
        from paddleocr import PaddleOCR
    except Exception:
        return ""

    try:
        # Lazy singleton
        global _paddle
        if "_paddle" not in globals() or _paddle is None:
            _paddle = PaddleOCR(
                lang="fa",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        arr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            path = handle.name
            cv2.imwrite(path, arr)
        try:
            outputs = list(_paddle.predict(path))
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        lines: List[str] = []
        for page in outputs:
            payload = page.json() if hasattr(page, "json") and callable(page.json) else getattr(page, "json", page)
            if isinstance(payload, dict):
                payload = payload.get("res", payload)
            texts = list((payload or {}).get("rec_texts") or [])
            for text in texts:
                cleaned = str(text or "").strip()
                if cleaned:
                    lines.append(cleaned)
        return "\n".join(lines[:200])
    except Exception as exc:
        logger.debug("classic hints unavailable: %s", exc)
        return ""


_paddle = None


def _page_tiles(image: Image.Image, *, dense: bool = False) -> List[Tuple[str, Image.Image]]:
    width, height = image.size
    tiles: List[Tuple[str, Image.Image]] = [("full", image)]
    if height < 900 and not dense:
        return tiles

    if dense or height >= 1400:
        band = int(height * (0.40 if dense else 0.48))
        step = int(height * (0.28 if dense else 0.38))
        tops = [0]
        t = step
        while t < height - band * 0.4:
            tops.append(t)
            t += step
        tops.append(max(0, height - band))
    else:
        band = int(height * 0.6)
        tops = [0, max(0, height - band)]

    # Local Ollama: fewer tiles to avoid RAM thrash / 500s.
    max_tiles = 7 if dense else 4
    if not get_cloud_ai().available:
        max_tiles = 4 if dense else 3

    seen = set()
    for index, top in enumerate(tops, start=1):
        top = max(0, min(int(top), height - 1))
        bottom = min(height, top + band)
        key = (top, bottom)
        if key in seen or bottom - top < 120:
            continue
        seen.add(key)
        if top == 0 and bottom >= height - 2:
            continue
        tiles.append((f"tile-{index}", image.crop((0, top, width, bottom))))
        if len(tiles) >= max_tiles:
            break
    return tiles


def _merge_tile_texts(parts: Sequence[str]) -> str:
    lines: List[str] = []
    seen = set()
    for part in parts:
        for line in str(part or "").splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            # Drop obvious JSON junk / markdown fences from weak models.
            if cleaned.startswith("{") or cleaned.startswith("```"):
                continue
            key = re.sub(r"\s+", "", cleaned)
            if key in seen:
                continue
            seen.add(key)
            lines.append(cleaned)
    return "\n".join(lines)


def _persian_signal(text: str) -> int:
    return len(re.findall(r"[\u0600-\u06FFA-Za-z0-9۰-۹]", text or ""))


def _looks_weak(text: str, size: Tuple[int, int]) -> bool:
    if _looks_like_loop(text):
        return True
    signal = _persian_signal(text)
    width, height = size
    area = max(width * height, 1)
    # Large page should yield more characters; tiny output is almost always a failure.
    expected = 40 if area < 1_000_000 else 80 if area < 3_000_000 else 120
    if signal < expected:
        return True
    # Mostly punctuation / commas like previous bad outputs.
    letters = len(re.findall(r"[\u0600-\u06FFa-zA-Z]", text or ""))
    if letters < 12:
        return True
    return False


def _looks_like_loop(text: str) -> bool:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) >= 12:
        # Same short token repeated many times (e.g. ۱۳۹۹ x100).
        counts: Dict[str, int] = {}
        for line in lines:
            counts[line] = counts.get(line, 0) + 1
        top = max(counts.values()) if counts else 0
        if top >= max(8, int(len(lines) * 0.45)):
            return True
    # Inline repetition
    compact = re.sub(r"\s+", "", text or "")
    if len(compact) >= 40:
        for n in (3, 4, 5, 6, 8, 10):
            if len(compact) < n * 6:
                continue
            chunk = compact[:n]
            if chunk and compact.count(chunk) >= 8:
                return True
    return False


def _dedupe_repetition(text: str) -> str:
    if not text:
        return ""
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: List[str] = []
    prev = None
    streak = 0
    for line in lines:
        key = line.strip()
        if key and key == prev:
            streak += 1
            if streak >= 2:
                continue
        else:
            streak = 0
            prev = key
        out.append(line)
    cleaned = "\n".join(out).strip()
    # Collapse runaway identical tokens separated by newlines already handled;
    # also collapse "a a a a" style.
    cleaned = re.sub(r"(\S+)(?:\s+\1){4,}", r"\1 \1", cleaned)
    return cleaned


def _quality_score(text: str, size: Tuple[int, int]) -> float:
    if not text or not str(text).strip():
        return -1.0
    if _looks_like_loop(text):
        return 0.0
    signal = float(_persian_signal(text))
    letters = float(len(re.findall(r"[\u0600-\u06FFa-zA-Z]", text)))
    unique_ratio = len(set(text.split())) / max(len(text.split()), 1)
    penalty = 0.0 if letters >= 20 else -50.0
    return signal + letters * 0.5 + unique_ratio * 40 + penalty


def _score_confidence(text: str, size: Tuple[int, int], reported: Any) -> float:
    try:
        base = float(reported or 0.8)
    except (TypeError, ValueError):
        base = 0.8
    if _looks_weak(text, size):
        return min(base, 0.45)
    signal = _persian_signal(text)
    if signal >= 200:
        return max(base, 0.9)
    if signal >= 80:
        return max(base, 0.82)
    return max(0.55, min(base, 0.75))


def _strip_code_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:\w+)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    # If model still returned JSON, lift text field.
    if cleaned.startswith("{"):
        data = parse_json_object(cleaned)
        if data.get("text"):
            return str(data["text"])
        if data.get("lines"):
            return "\n".join(str(x) for x in data["lines"])
    return cleaned.strip()


def _all_cloud_configs() -> List[CloudAiConfig]:
    configs: List[CloudAiConfig] = []
    seen = set()
    primary = resolve_cloud_config()
    if primary:
        configs.append(primary)
        seen.add(primary.provider)
    mapping = [
        ("openai", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4o"),
        ("anthropic", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        ("gemini", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-2.0-flash"),
    ]
    for provider, key_name, model_name, default_model in mapping:
        if provider in seen:
            continue
        key = (os.getenv(key_name) or "").strip()
        if provider == "gemini" and not key:
            key = (os.getenv("GOOGLE_API_KEY") or "").strip()
        if not key:
            continue
        configs.append(
            CloudAiConfig(
                provider=provider,
                model=(os.getenv(model_name) or default_model).strip(),
                api_key=key,
            )
        )
        seen.add(provider)
    return configs


def _pick_ollama_vision_model() -> Optional[str]:
    base = (os.getenv("OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
    preferred = os.getenv("VISION_OCR_MODEL", "qwen2.5vl:7b")
    try:
        response = httpx.get(f"{base}/api/tags", timeout=3.0)
        response.raise_for_status()
        models = [m.get("name", "") for m in response.json().get("models", [])]
    except Exception:
        return None

    def resolve(candidate: str) -> Optional[str]:
        for name in models:
            if name == candidate or name.startswith(candidate + "-") or name.startswith(candidate + ":"):
                return name
            if candidate in name:
                return name
        return None

    for candidate in (
        preferred,
        "qwen2.5vl:7b",
        "qwen2.5vl:32b",
        "qwen2.5vl:72b",
        "qwen2.5vl:3b",
        "llama3.2-vision",
        "llava",
    ):
        hit = resolve(candidate)
        if hit:
            return hit
    for name in models:
        if "vl" in name or "vision" in name:
            return name
    return None


def _encode_image(image: Image.Image, *, max_side: Optional[int] = None) -> str:
    if max_side is None:
        max_side = int(os.getenv("OCR_VISION_MAX_SIDE", "1400") or "1400")
    rgb = image.convert("RGB")
    w, h = rgb.size
    scale = min(1.0, max_side / float(max(w, h)))
    if scale < 1.0:
        rgb = rgb.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    buf = BytesIO()
    rgb.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _ollama_vision_text(
    image: Image.Image, prompt: str, model: str, *, json_mode: bool
) -> str:
    base = (os.getenv("OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
    sides = [
        int(os.getenv("OCR_VISION_MAX_SIDE", "1400") or "1400"),
        1024,
        768,
    ]
    last_error: Optional[Exception] = None
    for side in sides:
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "images": [_encode_image(image, max_side=side)],
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": int(os.getenv("OCR_VISION_NUM_PREDICT", "2048") or "2048"),
                "repeat_penalty": 1.25,
            },
        }
        if json_mode:
            payload["format"] = "json"
        try:
            with httpx.Client(timeout=300.0) as client:
                response = client.post(f"{base}/api/generate", json=payload)
                response.raise_for_status()
                return (response.json().get("response") or "").strip()
        except Exception as exc:
            last_error = exc
            logger.warning("Ollama vision failed at max_side=%s: %s", side, exc)
            continue
    raise RuntimeError(f"Ollama vision failed: {last_error}")


def _ollama_vision_json(
    image: Image.Image, prompt: str, model: str
) -> Tuple[Dict[str, Any], str]:
    raw = _ollama_vision_text(image, prompt, model, json_mode=True)
    return parse_json_object(raw), raw


def _clean_list(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = values.splitlines()
    out: List[str] = []
    seen = set()
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _normalize_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    text = str(data.get("text") or "").strip()
    lines = _clean_list(data.get("lines"))
    words = _clean_list(data.get("words"))
    sentences = _clean_list(data.get("sentences"))
    if not lines and text:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not text and lines:
        text = "\n".join(lines)
    if not words and text:
        words = re.findall(
            r"[\u0600-\u06FF]{1,}(?:[‌\-][\u0600-\u06FF]+)*|[A-Za-z0-9۰-۹]{1,}",
            text,
        )
    if not sentences and text:
        parts = re.split(r"(?<=[.!?؟۔])\s+|\n{2,}", text)
        sentences = [p.strip() for p in parts if p.strip()]
    try:
        confidence = float(data.get("confidence") or 0.85)
    except (TypeError, ValueError):
        confidence = 0.85
    return {
        "text": text,
        "lines": lines,
        "words": words,
        "sentences": sentences,
        "confidence": confidence,
    }


_service: Optional[AiOcrService] = None


def get_ai_ocr() -> AiOcrService:
    global _service
    if _service is None:
        _service = AiOcrService()
    return _service


def reset_ai_ocr() -> None:
    global _service
    _service = None
