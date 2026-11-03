"""Persian name similarity and final-name resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence, Tuple

from app.services.persian_text import hazm_normalize, normalize_persian

_SPACE = re.compile(r"\s+")


def _canon(name: str) -> str:
    text = hazm_normalize(normalize_persian(name))
    text = text.replace("آ", "ا").replace("‌", "")
    text = _SPACE.sub(" ", text).strip()
    return text


def similarity_percent(a: str, b: str) -> float:
    ca, cb = _canon(a), _canon(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 100.0
    return round(SequenceMatcher(None, ca, cb).ratio() * 100.0, 1)


@dataclass
class NameCandidate:
    name: str
    similarity: float


@dataclass
class ResolvedName:
    final_name: str
    confidence: float
    alternatives: List[NameCandidate]


def resolve_name(
    primary: str,
    candidates: Sequence[str] = (),
    *,
    threshold: float = 0.0,
) -> ResolvedName:
    """Pick one valid final name; attach ALL alternatives with similarity %."""
    pool: List[str] = []
    for value in [primary, *candidates]:
        cleaned = hazm_normalize(normalize_persian(value))
        if cleaned and cleaned not in pool:
            pool.append(cleaned)

    if not pool:
        return ResolvedName(final_name="", confidence=0.0, alternatives=[])

    # Score each candidate by average similarity to others + length stability.
    scored: List[Tuple[float, str]] = []
    for name in pool:
        if len(pool) == 1:
            scored.append((100.0, name))
            continue
        sims = [similarity_percent(name, other) for other in pool if other != name]
        avg = sum(sims) / len(sims) if sims else 100.0
        scored.append((avg + min(len(name), 20) * 0.1, name))
    scored.sort(reverse=True)
    final = scored[0][1]

    alternatives: List[NameCandidate] = []
    for name in pool:
        if name == final:
            continue
        sim = similarity_percent(final, name)
        if sim >= threshold:
            alternatives.append(NameCandidate(name=name, similarity=sim))
    alternatives.sort(key=lambda item: item.similarity, reverse=True)

    # Confidence from closeness of top alternatives.
    if alternatives:
        top = alternatives[0].similarity
        confidence = max(0.8, min(0.99, top / 100.0))
    else:
        confidence = 0.95 if len(pool) == 1 else 0.9

    return ResolvedName(final_name=final, confidence=confidence, alternatives=alternatives)


def find_similar_pairs(
    names: Sequence[str], *, threshold: float = 0.0
) -> List[Dict[str, object]]:
    """Return pairwise similarity for every distinct name pair (all rates)."""
    cleaned = []
    for name in names:
        value = hazm_normalize(normalize_persian(name))
        if value and value not in cleaned:
            cleaned.append(value)

    pairs: List[Dict[str, object]] = []
    for i, left in enumerate(cleaned):
        for right in cleaned[i + 1 :]:
            sim = similarity_percent(left, right)
            if sim >= threshold:
                pairs.append({"left": left, "right": right, "similarity": sim})
    pairs.sort(key=lambda item: float(item["similarity"]), reverse=True)
    return pairs


def row_similarity_matrix(
    named_rows: Sequence[Tuple[int, str]],
) -> List[Dict[str, object]]:
    """Full row-to-row similarity list: every row vs every other row."""
    cleaned: List[Tuple[int, str]] = []
    for row_index, name in named_rows:
        value = hazm_normalize(normalize_persian(name or ""))
        if value:
            cleaned.append((int(row_index), value))

    rows: List[Dict[str, object]] = []
    for i, (left_idx, left) in enumerate(cleaned):
        for right_idx, right in cleaned[i + 1 :]:
            rows.append(
                {
                    "left_row": left_idx,
                    "left": left,
                    "right_row": right_idx,
                    "right": right,
                    "similarity": similarity_percent(left, right),
                }
            )
    rows.sort(key=lambda item: float(item["similarity"]), reverse=True)
    return rows
