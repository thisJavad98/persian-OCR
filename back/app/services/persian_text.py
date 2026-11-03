"""Persian / Nasta'liq text cleanup: keep meaningful script, drop OCR noise."""

from __future__ import annotations

import re
from typing import List

# Persian letters + Arabic presentation that may appear, ZWNJ, digits, punctuation.
_PERSIAN_CHAR = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF"
    r"\u200c\u200d"
    r"0-9۰-۹"
    r"\s"
    r"\.,،؛:!؟\-\(\)\[\]«»\"'/٪%]"
)
_HAS_PERSIAN_LETTER = re.compile(r"[\u0600-\u06FF]")
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f]")
_MULTI_SPACE = re.compile(r"[ \t\u200f\u200e]+")
_MULTI_NL = re.compile(r"\n{3,}")

_LTR_RUN = re.compile(r"[A-Za-z0-9 :*./%+\-]")

_LETTER_MAP = {
    "ي": "ی",
    "ك": "ک",
    "ة": "ه",
    "ؤ": "و",
    "ئ": "ی",
    "إ": "ا",
    "أ": "ا",
    "آ": "آ",
    "ٱ": "ا",
    "ۀ": "ه",
    "٠": "۰",
    "١": "۱",
    "٢": "۲",
    "٣": "۳",
    "٤": "۴",
    "٥": "۵",
    "٦": "۶",
    "٧": "۷",
    "٨": "۸",
    "٩": "۹",
}


def pred_reverse(text: str) -> str:
    """Convert visual-order Arabic/Persian OCR output to logical reading order."""
    segments: List[str] = []
    current_ltr = ""
    for character in text:
        if _LTR_RUN.search(character):
            current_ltr += character
            continue
        if current_ltr:
            segments.append(current_ltr)
            current_ltr = ""
        segments.append(character)
    if current_ltr:
        segments.append(current_ltr)
    return "".join(reversed(segments))


def normalize_persian(text: str) -> str:
    if not text:
        return ""
    for src, dst in _LETTER_MAP.items():
        text = text.replace(src, dst)
    text = _CJK.sub("", text)
    kept = "".join(ch for ch in text if _PERSIAN_CHAR.match(ch) or ch in "\n")
    kept = _MULTI_SPACE.sub(" ", kept)
    kept = _MULTI_NL.sub("\n\n", kept)
    return kept.strip()


def is_meaningful_persian(text: str, min_letters: int = 2) -> bool:
    """Reject empty, CJK, or Latin-only OCR garbage."""
    cleaned = normalize_persian(text)
    if not cleaned:
        return False
    if _CJK.search(text):
        return False
    letters = _HAS_PERSIAN_LETTER.findall(cleaned)
    if len(letters) < min_letters:
        # Allow pure numbers (IDs, dates) with enough digits.
        digits = re.findall(r"[0-9۰-۹]", cleaned)
        return len(digits) >= 2 and len(cleaned) <= 24
    # Too many non-letters relative to Persian content → noise.
    ratio = len(letters) / max(len(re.sub(r"\s", "", cleaned)), 1)
    return ratio >= 0.35


def filter_meaningful_lines(texts: List[str]) -> List[str]:
    out: List[str] = []
    for text in texts:
        cleaned = normalize_persian(text)
        if is_meaningful_persian(cleaned):
            out.append(cleaned)
    return out


_hazm_normalizer = None


def hazm_normalize(text: str) -> str:
    global _hazm_normalizer
    text = normalize_persian(text)
    if not text:
        return ""
    try:
        if _hazm_normalizer is None:
            from hazm import Normalizer

            _hazm_normalizer = Normalizer()
        return _hazm_normalizer.normalize(text)
    except Exception:
        return text
