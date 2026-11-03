"""AI name agent: validate Nasta'liq OCR names against Iranian lexicon + Ollama."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import httpx

from app.services.iranian_names import (
    best_lexicon_matches,
    compare_to_lexicon,
    gender_of,
    is_known_iranian_name,
)
from app.services.name_similarity import resolve_name, similarity_percent
from app.services.persian_text import hazm_normalize, normalize_persian

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
# Prefer a small text model; fall back to vision model for text-only chat.
DEFAULT_TEXT_MODEL = os.getenv("NAME_AGENT_MODEL", "qwen2.5:1.5b")
FALLBACK_MODEL = os.getenv("VISION_OCR_MODEL", "qwen2.5vl:3b")


@dataclass
class ValidatedName:
    raw: str
    final_name: str
    gender: str = "unknown"
    is_valid_iranian: bool = False
    confidence: float = 0.0
    similarity: float = 0.0
    alternatives: List[Dict[str, Any]] = field(default_factory=list)
    source: str = "lexicon"  # lexicon | ai | hybrid


@dataclass
class NameAgentResult:
    names: List[ValidatedName]
    comparisons: List[Dict[str, Any]]
    valid_words: List[str]
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "names": [
                {
                    "raw": n.raw,
                    "final_name": n.final_name,
                    "gender": n.gender,
                    "is_valid_iranian": n.is_valid_iranian,
                    "confidence": n.confidence,
                    "similarity": n.similarity,
                    "alternatives": n.alternatives,
                    "source": n.source,
                }
                for n in self.names
            ],
            "comparisons": self.comparisons,
            "valid_words": self.valid_words,
            "details": self.details,
        }


class IranianNameAgent:
    """Lexicon + local Ollama agent for Iranian name correction / comparison."""

    def __init__(
        self,
        base_url: str = OLLAMA_URL,
        model: str = DEFAULT_TEXT_MODEL,
        timeout: float = 25.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._ready: Optional[bool] = None
        self._active_model: Optional[str] = None
        self._ai_enabled = os.getenv("NAME_AGENT_AI", "1") != "0"

    def available(self) -> bool:
        if self._ready is not None:
            return self._ready
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            response.raise_for_status()
            models = [m.get("name", "") for m in response.json().get("models", [])]
            for candidate in (self.model, FALLBACK_MODEL, "qwen2.5vl:3b"):
                if any(candidate in name or name.startswith(candidate.split(":")[0]) for name in models):
                    # Prefer exact-ish match.
                    for name in models:
                        if candidate in name or name.startswith(candidate.split(":")[0]):
                            self._active_model = name
                            break
                    self._ready = True
                    return True
            self._ready = False
        except Exception as exc:
            logger.warning("Name agent Ollama unavailable: %s", exc)
            self._ready = False
        return bool(self._ready)

    def validate_name(self, raw: str, *, role: str = "person") -> ValidatedName:
        cleaned = hazm_normalize(normalize_persian(raw or ""))
        if not cleaned:
            return ValidatedName(raw="", final_name="", confidence=0.0)

        matches = best_lexicon_matches(cleaned, limit=5, threshold=60.0)
        if matches and (matches[0].is_exact or matches[0].similarity >= 88.0):
            top = matches[0]
            return ValidatedName(
                raw=cleaned,
                final_name=top.name,
                gender=top.gender,
                is_valid_iranian=True,
                confidence=0.98 if top.is_exact else max(0.88, top.similarity / 100.0),
                similarity=float(top.similarity),
                alternatives=[
                    {"name": m.name, "similarity": m.similarity, "gender": m.gender}
                    for m in matches[1:4]
                ],
                source="lexicon",
            )

        ai_pick: Optional[str] = None
        # AI only for weak lexicon hits — keeps Nasta'liq cleanup fast on good matches.
        if (
            self._ai_enabled
            and self.available()
            and (not matches or matches[0].similarity < 88.0)
        ):
            ai_pick = self._ai_correct(cleaned, role=role, hints=[m.name for m in matches[:5]])

        pool = [cleaned]
        if matches:
            pool.extend(m.name for m in matches[:3])
        if ai_pick:
            pool.append(ai_pick)

        resolved = resolve_name(cleaned, pool[1:])
        final = resolved.final_name
        gender = gender_of(final)
        known = is_known_iranian_name(final)
        sim = 100.0 if known else (matches[0].similarity if matches else 0.0)

        # Prefer lexicon hit when AI drifts away from Persian names.
        if matches and matches[0].similarity >= 78.0:
            if not known or similarity_percent(final, matches[0].name) < matches[0].similarity:
                final = matches[0].name
                gender = matches[0].gender
                known = True
                sim = matches[0].similarity

        alts: List[Dict[str, Any]] = []
        seen = {final}
        for m in matches:
            if m.name in seen:
                continue
            seen.add(m.name)
            alts.append({"name": m.name, "similarity": m.similarity, "gender": m.gender})
        for alt in resolved.alternatives:
            if alt.name in seen:
                continue
            seen.add(alt.name)
            alts.append(
                {
                    "name": alt.name,
                    "similarity": alt.similarity,
                    "gender": gender_of(alt.name),
                }
            )

        source = "hybrid" if ai_pick else "lexicon"
        confidence = 0.95 if known else max(0.7, sim / 100.0)
        return ValidatedName(
            raw=cleaned,
            final_name=final,
            gender=gender,
            is_valid_iranian=known or sim >= 90.0,
            confidence=confidence,
            similarity=float(sim),
            alternatives=alts[:6],
            source=source,
        )

    def enrich_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Rewrite death-record name fields with AI-validated Iranian names."""
        enriched: List[Dict[str, Any]] = []
        for item in records:
            row = dict(item)
            for key, role in (
                ("deceased_name", "deceased"),
                ("father_name", "father"),
                ("physician_name", "physician"),
            ):
                field = row.get(key)
                raw = ""
                prior_alts: List[str] = []
                if isinstance(field, dict):
                    raw = str(field.get("final_name") or field.get("name") or "")
                    for alt in field.get("alternatives") or []:
                        if isinstance(alt, dict):
                            prior_alts.append(str(alt.get("name") or ""))
                        else:
                            prior_alts.append(str(alt))
                else:
                    raw = str(field or "")

                validated = self.validate_name(raw, role=role)
                # Fold prior OCR alternatives into comparison list.
                extra = []
                for name in prior_alts:
                    cleaned = hazm_normalize(normalize_persian(name))
                    if cleaned and cleaned != validated.final_name:
                        extra.append(
                            {
                                "name": cleaned,
                                "similarity": similarity_percent(validated.final_name, cleaned),
                                "gender": gender_of(cleaned),
                            }
                        )
                alts = validated.alternatives + extra
                # Dedupe by name.
                seen = set()
                uniq = []
                for alt in sorted(alts, key=lambda a: float(a.get("similarity") or 0), reverse=True):
                    name = str(alt.get("name") or "")
                    if not name or name in seen or name == validated.final_name:
                        continue
                    seen.add(name)
                    uniq.append(alt)

                row[key] = {
                    "final_name": validated.final_name,
                    "confidence": validated.confidence,
                    "alternatives": uniq[:8],
                    "gender": validated.gender,
                    "is_valid_iranian": validated.is_valid_iranian,
                    "similarity": validated.similarity,
                    "raw": validated.raw,
                    "source": validated.source,
                }
            enriched.append(row)
        return enriched

    def analyze_names(self, names: Sequence[str]) -> NameAgentResult:
        validated = [self.validate_name(n) for n in names if str(n or "").strip()]
        finals = [n.final_name for n in validated if n.final_name]
        comparisons: List[Dict[str, Any]] = []
        for i, left in enumerate(finals):
            for right in finals[i + 1 :]:
                if left == right:
                    continue
                sim = similarity_percent(left, right)
                comparisons.append(
                    {
                        "left": left,
                        "right": right,
                        "similarity": sim,
                        "left_gender": gender_of(left),
                        "right_gender": gender_of(right),
                    }
                )
        comparisons.sort(key=lambda item: float(item["similarity"]), reverse=True)

        lexicon_rows = compare_to_lexicon(finals, threshold=65.0)
        valid_words = [
            str(row["valid_name"] or row["raw"])
            for row in lexicon_rows
            if row.get("is_valid") or float(row.get("similarity") or 0) >= 85.0
        ]
        # Unique preserve order.
        seen = set()
        unique_words = []
        for word in valid_words:
            if word not in seen:
                seen.add(word)
                unique_words.append(word)

        return NameAgentResult(
            names=validated,
            comparisons=comparisons,
            valid_words=unique_words,
            details={
                "agent_model": self._active_model or self.model,
                "lexicon_rows": lexicon_rows,
                "ai_available": self.available(),
            },
        )

    def _ai_correct(self, raw: str, *, role: str, hints: Sequence[str]) -> Optional[str]:
        model = self._active_model or self.model
        hint_text = "، ".join(hints) if hints else "—"
        prompt = f"""You are an Iranian Persian name expert for Nasta'liq OCR cleanup.
Role: {role}
OCR raw name: {raw}
Likely lexicon hints: {hint_text}

Return ONLY JSON:
{{"valid_name":"correct Persian given name","gender":"male|female|unknown","confidence":0.0}}

Rules:
- Output a real Iranian given name in Persian script when possible.
- Fix OCR / Nasta'liq letter mistakes; do not invent Latin or Chinese.
- If unreadable, return the closest Persian name from hints.
- confidence 0..1.
"""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.0, "num_predict": 120},
                    },
                )
                response.raise_for_status()
                body = response.json()
            text = (body.get("response") or "").strip()
            data = _parse_json(text)
            name = hazm_normalize(normalize_persian(str(data.get("valid_name") or "")))
            if name and re.search(r"[\u0600-\u06FF]{2,}", name):
                return name
        except Exception as exc:
            logger.debug("AI name correct failed: %s", exc)
        return None


def _parse_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                data = json.loads(match.group(0))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


_agent: Optional[IranianNameAgent] = None


def get_name_agent() -> IranianNameAgent:
    global _agent
    if _agent is None:
        _agent = IranianNameAgent()
    return _agent
