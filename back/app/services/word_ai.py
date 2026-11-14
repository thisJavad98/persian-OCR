"""OCR AI polish for high-quality Persian / Nasta'liq Word export."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence

import httpx

from app.services.cloud_ai import get_cloud_ai
from app.services.name_agent import get_name_agent
from app.services.persian_text import (
    has_persian_letters,
    hazm_normalize,
    is_meaningful_persian,
    normalize_persian,
)

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("WORD_AI_MODEL", os.getenv("NAME_AGENT_MODEL", "qwen2.5:1.5b"))
FALLBACK_MODEL = os.getenv("VISION_OCR_MODEL", "qwen2.5vl:3b")


def polish_for_word(
    *,
    full_text: str,
    lines: Sequence[str] = (),
    records: Optional[List[Dict[str, Any]]] = None,
    words: Optional[Sequence[str]] = None,
    timeout: float = 45.0,
) -> Dict[str, Any]:
    """
    Build a Word-ready payload:
    - AI-cleaned Persian paragraphs (when Ollama is up)
    - validated Iranian words/names (prefer Bina-detected words)
    - structured row lines for the document body
    """
    records = list(records or [])
    bina_words = [
        hazm_normalize(normalize_persian(str(w)))
        for w in (words or [])
        if str(w).strip() and has_persian_letters(str(w))
    ]
    cleaned_lines = _unique_lines(list(lines) + list(bina_words) + str(full_text or "").splitlines())
    for rec in records:
        raw = str(rec.get("raw_line") or "")
        if raw:
            cleaned_lines.append(hazm_normalize(normalize_persian(raw)))
        deceased = (rec.get("deceased_name") or {}).get("final_name") or ""
        if deceased:
            cleaned_lines.append(hazm_normalize(normalize_persian(deceased)))
    cleaned_lines = _unique_lines(cleaned_lines)

    # Lexicon / name-agent validation first (always available).
    agent = get_name_agent()
    name_pool: List[str] = []
    for rec in records:
        for key in ("deceased_name", "father_name", "physician_name"):
            blob = rec.get(key) or {}
            name = str(blob.get("final_name") or "")
            if name:
                name_pool.append(name)
    # Prefer letter-bearing OCR tokens (Bina / classic) over digit noise.
    if bina_words:
        name_pool.extend(bina_words)
    for line in cleaned_lines:
        for token in re.findall(r"[\u0600-\u06FF]{2,}", line):
            if has_persian_letters(token, min_letters=2):
                name_pool.append(token)
    analysis = agent.analyze_names(name_pool)

    structured_rows = [_format_record_line(rec) for rec in records]
    structured_rows = [row for row in structured_rows if row]

    ai_doc = _ai_polish_document(
        lines=cleaned_lines[:80],
        records=structured_rows[:40],
        timeout=timeout,
        model_hint=DEFAULT_MODEL,
    )

    paragraphs: List[str] = []
    if ai_doc.get("paragraphs"):
        paragraphs = [
            hazm_normalize(normalize_persian(str(p)))
            for p in ai_doc["paragraphs"]
            if str(p).strip()
        ]
    if not paragraphs:
        # Fallback: clean OCR lines as Word body.
        paragraphs = [
            line
            for line in cleaned_lines
            if is_meaningful_persian(line, min_letters=1) or re.search(r"\d", line)
        ]

    title = hazm_normalize(
        normalize_persian(str(ai_doc.get("title") or "خروجی OCR — خط‌خوان"))
    )
    words = list(analysis.valid_words)
    for extra in ai_doc.get("words") or []:
        w = hazm_normalize(normalize_persian(str(extra)))
        if w and w not in words:
            words.append(w)

    return {
        "title": title,
        "paragraphs": paragraphs,
        "structured_rows": structured_rows,
        "valid_words": words,
        "ai_available": bool(ai_doc.get("ai_available")),
        "model": ai_doc.get("model") or analysis.details.get("agent_model") or "lexicon",
        "notes": hazm_normalize(
            normalize_persian(
                str(
                    ai_doc.get("notes")
                    or "متن با عامل OCR AI برای خروجی Word پاک‌سازی شده است."
                )
            )
        ),
    }


def _format_record_line(rec: Dict[str, Any]) -> str:
    deceased = (rec.get("deceased_name") or {}).get("final_name") or ""
    father = (rec.get("father_name") or {}).get("final_name") or ""
    physician = (rec.get("physician_name") or {}).get("final_name") or ""
    national_id = rec.get("national_id") or ""
    cause = rec.get("cause_of_death") or ""
    raw = rec.get("raw_line") or ""
    parts = [
        f"ردیف {rec.get('row_index') or ''}".strip(),
        deceased and f"متوفی: {deceased}",
        national_id and f"کد ملی: {national_id}",
        father and f"پدر: {father}",
        cause and f"علت: {cause}",
        physician and f"پزشک: {physician}",
        (not deceased and raw) and f"متن: {raw}",
    ]
    return " | ".join(p for p in parts if p)


def _unique_lines(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        cleaned = hazm_normalize(normalize_persian(str(value or "")))
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _ai_polish_document(
    *,
    lines: Sequence[str],
    records: Sequence[str],
    timeout: float,
    model_hint: str,
) -> Dict[str, Any]:
    if os.getenv("WORD_AI", "1") == "0":
        return {"ai_available": False}

    model = _pick_model(model_hint)
    if not model:
        return {"ai_available": False}

    sample_lines = "\n".join(f"- {line}" for line in lines[:40])
    sample_rows = "\n".join(f"- {row}" for row in records[:25])
    prompt = f"""You are a document editor for OCR Word export of ANY image content.
Clean OCR noise into a faithful Word transcript. Preserve ALL visible content —
words, numbers, names, dates, headings, table cells. Do not invent content.
Do not reduce the page to only names.

OCR lines:
{sample_lines or '-'}

Optional structured rows (only if present):
{sample_rows or '-'}

Return ONLY JSON:
{{
  "title": "short document title matching the page",
  "paragraphs": ["clean paragraph 1 matching page content", "paragraph 2"],
  "words": ["important words/tokens from the page"],
  "notes": "one short note about cleanup"
}}

Rules:
- paragraphs must mirror the page content (not a name-only summary).
- Keep digits, codes, Latin, and Persian as they appear when readable.
- RTL logical order for Persian/Arabic; no Chinese garbage.
- If structured rows exist, include them as paragraphs too — in addition to full text.
"""
    try:
        cloud = get_cloud_ai()
        if cloud.available:
            data = cloud.complete_json(
                prompt,
                system=(
                    "You clean Persian Nasta'liq OCR into Word-ready text and valid names. "
                    "Return only JSON."
                ),
                timeout=timeout,
                max_tokens=2400,
            )
            data["ai_available"] = True
            data["model"] = cloud.label
            return data

        if not model:
            return {"ai_available": False}
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{OLLAMA_URL.rstrip('/')}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.0, "num_predict": 1800},
                },
            )
            response.raise_for_status()
            raw = (response.json().get("response") or "").strip()
        data = _parse_json(raw)
        data["ai_available"] = True
        data["model"] = model
        return data
    except Exception as exc:
        logger.debug("Word AI polish failed: %s", exc)
        return {"ai_available": False, "model": model}


def _pick_model(preferred: str) -> Optional[str]:
    if get_cloud_ai().available:
        return get_cloud_ai().label
    try:
        response = httpx.get(f"{OLLAMA_URL.rstrip('/')}/api/tags", timeout=3.0)
        response.raise_for_status()
        models = [m.get("name", "") for m in response.json().get("models", [])]
    except Exception:
        return None
    for candidate in (preferred, FALLBACK_MODEL, "qwen2.5vl:3b"):
        for name in models:
            if candidate in name or name.startswith(candidate.split(":")[0]):
                return name
    return None


def _parse_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
