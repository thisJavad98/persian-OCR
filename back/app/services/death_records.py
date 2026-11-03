"""Domain model for deceased-list extraction (IDs, fathers, causes, physicians)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from app.services.name_similarity import (
    find_similar_pairs,
    resolve_name,
    row_similarity_matrix,
    similarity_percent,
)
from app.services.persian_text import hazm_normalize, is_meaningful_persian, normalize_persian


def apply_name_agent(result: "DeathExtractResult") -> "DeathExtractResult":
    """Run Iranian name AI agent over extracted person fields."""
    try:
        from app.services.name_agent import get_name_agent
    except Exception:
        return result

    agent = get_name_agent()
    payload = result.as_dict()
    enriched_rows = agent.enrich_records(payload.get("records") or [])

    # Rebuild NameField objects from enriched dicts.
    rebuilt: List[DeathRecord] = []
    collected_names: List[str] = []
    for item in enriched_rows:
        deceased = item.get("deceased_name") or {}
        father = item.get("father_name") or {}
        physician = item.get("physician_name") or {}
        for blob in (deceased, father, physician):
            name = str(blob.get("final_name") or "")
            if name:
                collected_names.append(name)
        def _field(blob: Dict[str, Any]) -> NameField:
            return NameField(
                final_name=str(blob.get("final_name") or ""),
                confidence=float(blob.get("confidence") or 0),
                alternatives=list(blob.get("alternatives") or []),
                gender=str(blob.get("gender") or "unknown"),
                is_valid_iranian=bool(blob.get("is_valid_iranian")),
                similarity=float(blob.get("similarity") or 0),
                source=str(blob.get("source") or ""),
                raw=str(blob.get("raw") or ""),
            )

        rebuilt.append(
            DeathRecord(
                row_index=int(item.get("row_index") or len(rebuilt) + 1),
                deceased_name=_field(deceased),
                national_id=str(item.get("national_id") or ""),
                father_name=_field(father),
                cause_of_death=str(item.get("cause_of_death") or ""),
                physician_name=_field(physician),
                confidence=float(item.get("confidence") or 0),
                raw_line=str(item.get("raw_line") or ""),
                name_similarities=list(item.get("name_similarities") or []),
            )
        )

    analysis = agent.analyze_names(collected_names)

    # Recompute ALL row↔row similarity rates after AI name correction.
    _attach_all_row_similarities(rebuilt)
    all_names = [
        name
        for rec in rebuilt
        for name in (
            rec.deceased_name.final_name,
            rec.father_name.final_name,
            rec.physician_name.final_name,
        )
        if name
    ]
    result.similar_name_pairs = find_similar_pairs(all_names, threshold=0.0)
    # Keep AI comparison extras that might use alternate spellings.
    pair_keys = {
        tuple(sorted((str(p.get("left")), str(p.get("right")))))
        for p in result.similar_name_pairs
    }
    for pair in analysis.comparisons:
        key = tuple(sorted((str(pair.get("left")), str(pair.get("right")))))
        if key not in pair_keys:
            result.similar_name_pairs.append(pair)
            pair_keys.add(key)
    result.similar_name_pairs.sort(
        key=lambda item: float(item.get("similarity") or 0), reverse=True
    )

    result.records = rebuilt
    result.details["ai_names"] = analysis.as_dict()
    result.details["name_agent"] = {
        "model": analysis.details.get("agent_model"),
        "ai_available": analysis.details.get("ai_available"),
        "valid_word_count": len(analysis.valid_words),
    }
    result.details["row_similarity_matrix"] = row_similarity_matrix(
        [(rec.row_index, rec.deceased_name.final_name) for rec in rebuilt]
    )

    # Refresh summary with validated names.
    summary_lines = []
    for rec in rebuilt:
        summary_lines.append(
            " | ".join(
                part
                for part in [
                    rec.deceased_name.final_name and f"متوفی: {rec.deceased_name.final_name}",
                    rec.national_id and f"کد ملی: {rec.national_id}",
                    rec.father_name.final_name and f"پدر: {rec.father_name.final_name}",
                    rec.cause_of_death and f"علت: {rec.cause_of_death}",
                    rec.physician_name.final_name and f"پزشک: {rec.physician_name.final_name}",
                ]
                if part
            )
        )
    result.summary_text = "\n".join(summary_lines)
    if rebuilt:
        result.confidence = float(sum(rec.confidence for rec in rebuilt) / len(rebuilt))
    return result


def _attach_all_row_similarities(records: List["DeathRecord"]) -> None:
    """Fill every row with similarity % against every other deceased name."""
    for rec in records:
        if not rec.deceased_name.final_name:
            rec.name_similarities = []
            continue
        row_sims: List[Dict[str, Any]] = []
        for other in records:
            if other.row_index == rec.row_index or not other.deceased_name.final_name:
                continue
            sim = similarity_percent(
                rec.deceased_name.final_name, other.deceased_name.final_name
            )
            row_sims.append(
                {
                    "row_index": other.row_index,
                    "name": other.deceased_name.final_name,
                    "similarity": sim,
                }
            )
        row_sims.sort(key=lambda item: float(item["similarity"]), reverse=True)
        rec.name_similarities = row_sims
        seen = {str(a.get("name")) for a in rec.deceased_name.alternatives}
        for item in row_sims:
            if item["name"] not in seen:
                rec.deceased_name.alternatives.append(
                    {"name": item["name"], "similarity": item["similarity"]}
                )
                seen.add(item["name"])
        rec.deceased_name.alternatives.sort(
            key=lambda item: float(item.get("similarity") or 0), reverse=True
        )

_ID_RE = re.compile(r"(?<!\d)(\d{8,12})(?!\d)")
_FA_ID_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


@dataclass
class NameField:
    final_name: str
    confidence: float = 0.0
    alternatives: List[Dict[str, Any]] = field(default_factory=list)
    gender: str = "unknown"
    is_valid_iranian: bool = False
    similarity: float = 0.0
    source: str = ""
    raw: str = ""


@dataclass
class DeathRecord:
    row_index: int
    deceased_name: NameField
    national_id: str = ""
    father_name: NameField = field(default_factory=lambda: NameField(final_name=""))
    cause_of_death: str = ""
    physician_name: NameField = field(default_factory=lambda: NameField(final_name=""))
    confidence: float = 0.0
    raw_line: str = ""
    # Similarity of this deceased name vs every other row (all rates).
    name_similarities: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class DeathExtractResult:
    records: List[DeathRecord]
    similar_name_pairs: List[Dict[str, Any]]
    summary_text: str
    confidence: float
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        ai_names = self.details.get("ai_names") or {}
        return {
            "records": [
                {
                    "row_index": rec.row_index,
                    "deceased_name": asdict(rec.deceased_name),
                    "national_id": rec.national_id,
                    "father_name": asdict(rec.father_name),
                    "cause_of_death": rec.cause_of_death,
                    "physician_name": asdict(rec.physician_name),
                    "confidence": rec.confidence,
                    "raw_line": rec.raw_line,
                    "name_similarities": rec.name_similarities,
                }
                for rec in self.records
            ],
            "similar_name_pairs": self.similar_name_pairs,
            "summary_text": self.summary_text,
            "confidence": self.confidence,
            "details": self.details,
            "ai_names": ai_names,
        }


def _to_name_field(value: Any, alternatives: Optional[List[Any]] = None) -> NameField:
    primary = ""
    alt_names: List[str] = []
    if isinstance(value, dict):
        primary = str(value.get("final_name") or value.get("name") or value.get("text") or "")
        for item in value.get("alternatives") or []:
            if isinstance(item, dict):
                alt_names.append(str(item.get("name") or item.get("text") or ""))
            else:
                alt_names.append(str(item))
    else:
        primary = str(value or "")

    for item in alternatives or []:
        if isinstance(item, dict):
            alt_names.append(str(item.get("name") or item.get("text") or ""))
        else:
            alt_names.append(str(item))

    resolved = resolve_name(primary, alt_names)
    return NameField(
        final_name=resolved.final_name,
        confidence=resolved.confidence,
        alternatives=[
            {"name": alt.name, "similarity": alt.similarity} for alt in resolved.alternatives
        ],
    )


def _normalize_id(value: Any) -> str:
    text = normalize_persian(str(value or "")).translate(_FA_ID_DIGITS)
    text = re.sub(r"[^\d]", "", text)
    match = _ID_RE.search(text)
    if match:
        return match.group(1)
    return text if 8 <= len(text) <= 12 else text


def _clean_cause(value: Any) -> str:
    text = hazm_normalize(normalize_persian(str(value or "")))
    return text if is_meaningful_persian(text, min_letters=2) or bool(re.search(r"\d", text)) else text


def _supplement_records_from_lines(
    records: List[DeathRecord],
    lines: Any,
    *,
    text: str,
    overall_confidence: float,
) -> List[DeathRecord]:
    """Turn leftover OCR lines into person rows so all visible items appear."""
    existing_raw = {
        hazm_normalize(normalize_persian(rec.raw_line))
        for rec in records
        if rec.raw_line
    }
    existing_names = {
        hazm_normalize(normalize_persian(rec.deceased_name.final_name))
        for rec in records
        if rec.deceased_name.final_name
    }
    line_items: List[str] = []
    if isinstance(lines, list):
        line_items = [str(item) for item in lines]
    elif isinstance(lines, str):
        line_items = lines.splitlines()
    if text:
        line_items.extend(str(text).splitlines())

    next_index = (max((rec.row_index for rec in records), default=0) + 1)
    for raw in line_items:
        cleaned = hazm_normalize(normalize_persian(raw))
        if not cleaned or len(cleaned) < 2:
            continue
        if cleaned in existing_raw:
            continue
        # Skip lines that are already covered by a known deceased name.
        if any(name and name in cleaned for name in existing_names):
            continue
        if not is_meaningful_persian(cleaned, min_letters=1) and not re.search(r"\d", cleaned):
            continue
        # Prefer first Persian token as a provisional name.
        tokens = re.findall(r"[\u0600-\u06FF]{2,}", cleaned)
        provisional = tokens[0] if tokens else ""
        if provisional and provisional in existing_names:
            continue
        id_match = _ID_RE.search(cleaned.translate(_FA_ID_DIGITS))
        records.append(
            DeathRecord(
                row_index=next_index,
                deceased_name=NameField(final_name=provisional, confidence=0.75, raw=provisional),
                national_id=id_match.group(1) if id_match else "",
                confidence=max(0.75, overall_confidence * 0.9),
                raw_line=cleaned,
            )
        )
        existing_raw.add(cleaned)
        if provisional:
            existing_names.add(provisional)
        next_index += 1
    return records


def build_death_extract(parsed: Dict[str, Any], *, overall_confidence: float) -> DeathExtractResult:
    raw_records = parsed.get("records") or parsed.get("deceased") or []
    records: List[DeathRecord] = []

    if isinstance(raw_records, list):
        for index, item in enumerate(raw_records, start=1):
            if not isinstance(item, dict):
                continue
            deceased = _to_name_field(
                item.get("deceased_name") or item.get("name") or item.get("full_name"),
                item.get("deceased_name_alternatives") or item.get("name_alternatives"),
            )
            father = _to_name_field(
                item.get("father_name") or item.get("father"),
                item.get("father_name_alternatives"),
            )
            physician = _to_name_field(
                item.get("physician_name")
                or item.get("doctor_name")
                or item.get("physician")
                or item.get("doctor"),
                item.get("physician_name_alternatives") or item.get("doctor_alternatives"),
            )
            national_id = _normalize_id(
                item.get("national_id") or item.get("id") or item.get("nationalId")
            )
            cause = _clean_cause(
                item.get("cause_of_death") or item.get("cause") or item.get("death_cause")
            )
            conf = float(item.get("confidence") or overall_confidence or 0.85)
            conf = max(0.0, min(conf, 1.0))
            raw_line = hazm_normalize(
                normalize_persian(str(item.get("raw_line") or ""))
            )
            # Keep every visible row — including partial / raw-only items.
            if not any(
                [
                    deceased.final_name,
                    national_id,
                    father.final_name,
                    cause,
                    physician.final_name,
                    raw_line,
                ]
            ):
                continue
            records.append(
                DeathRecord(
                    row_index=int(item.get("row_index") or index),
                    deceased_name=deceased,
                    national_id=national_id,
                    father_name=father,
                    cause_of_death=cause,
                    physician_name=physician,
                    confidence=max(conf, deceased.confidence),
                    raw_line=raw_line,
                )
            )

    # Promote leftover OCR lines into rows so nothing visible is omitted.
    records = _supplement_records_from_lines(
        records,
        parsed.get("lines") or [],
        text=str(parsed.get("text") or ""),
        overall_confidence=overall_confidence,
    )

    # All pairwise name similarities (every rate, every distinct name).
    all_names: List[str] = []
    for rec in records:
        for field_name in (rec.deceased_name, rec.father_name, rec.physician_name):
            if field_name.final_name:
                all_names.append(field_name.final_name)
            for alt in field_name.alternatives:
                name = str(alt.get("name") or "")
                if name:
                    all_names.append(name)

    similar_pairs = find_similar_pairs(all_names, threshold=0.0)
    matrix = row_similarity_matrix(
        [(rec.row_index, rec.deceased_name.final_name) for rec in records]
    )

    _attach_all_row_similarities(records)

    summary_lines = []
    for rec in records:
        summary_lines.append(
            " | ".join(
                part
                for part in [
                    rec.deceased_name.final_name and f"متوفی: {rec.deceased_name.final_name}",
                    rec.national_id and f"کد ملی: {rec.national_id}",
                    rec.father_name.final_name and f"پدر: {rec.father_name.final_name}",
                    rec.cause_of_death and f"علت: {rec.cause_of_death}",
                    rec.physician_name.final_name and f"پزشک: {rec.physician_name.final_name}",
                ]
                if part
            )
        )

    confidence = (
        float(sum(rec.confidence for rec in records) / len(records)) if records else overall_confidence
    )
    result = DeathExtractResult(
        records=records,
        similar_name_pairs=similar_pairs,
        summary_text="\n".join(summary_lines),
        confidence=confidence,
        details={
            "record_count": len(records),
            "row_similarity_matrix": matrix,
        },
    )
    return apply_name_agent(result)


def _record_key(rec: DeathRecord) -> str:
    if rec.national_id:
        return f"id:{rec.national_id}"
    name = rec.deceased_name.final_name.strip()
    father = rec.father_name.final_name.strip()
    return f"name:{name}|father:{father}"


def _merge_name_field(primary: NameField, secondary: NameField) -> NameField:
    if not primary.final_name and secondary.final_name:
        return secondary
    if primary.final_name and secondary.final_name and primary.final_name != secondary.final_name:
        resolved = resolve_name(
            primary.final_name,
            [secondary.final_name]
            + [str(a.get("name") or "") for a in primary.alternatives]
            + [str(a.get("name") or "") for a in secondary.alternatives],
        )
        return NameField(
            final_name=resolved.final_name,
            confidence=max(primary.confidence, secondary.confidence, resolved.confidence),
            alternatives=[
                {"name": alt.name, "similarity": alt.similarity} for alt in resolved.alternatives
            ],
        )
    alts = list(primary.alternatives)
    seen = {str(a.get("name")) for a in alts}
    for alt in secondary.alternatives:
        name = str(alt.get("name") or "")
        if name and name not in seen and name != primary.final_name:
            alts.append(alt)
            seen.add(name)
    return NameField(
        final_name=primary.final_name or secondary.final_name,
        confidence=max(primary.confidence, secondary.confidence),
        alternatives=alts,
    )


def merge_death_extracts(parts: List[DeathExtractResult]) -> DeathExtractResult:
    """Merge multi-pass/tile extractions so every person on the page is kept."""
    if not parts:
        return DeathExtractResult(
            records=[],
            similar_name_pairs=[],
            summary_text="",
            confidence=0.0,
        )
    if len(parts) == 1:
        return parts[0]

    merged_map: Dict[str, DeathRecord] = {}
    order: List[str] = []
    for part in parts:
        for rec in part.records:
            key = _record_key(rec)
            # Fuzzy attach when IDs missing but names are very similar.
            matched_key = None
            if key.startswith("name:") and rec.deceased_name.final_name:
                for existing_key in order:
                    existing = merged_map[existing_key]
                    if existing.national_id and rec.national_id:
                        continue
                    sim = similarity_percent(
                        existing.deceased_name.final_name, rec.deceased_name.final_name
                    )
                    if sim >= 90.0:
                        matched_key = existing_key
                        break
            use_key = matched_key or key
            if use_key not in merged_map:
                merged_map[use_key] = rec
                order.append(use_key)
                continue
            current = merged_map[use_key]
            merged_map[use_key] = DeathRecord(
                row_index=min(current.row_index, rec.row_index),
                deceased_name=_merge_name_field(current.deceased_name, rec.deceased_name),
                national_id=current.national_id or rec.national_id,
                father_name=_merge_name_field(current.father_name, rec.father_name),
                cause_of_death=current.cause_of_death or rec.cause_of_death,
                physician_name=_merge_name_field(current.physician_name, rec.physician_name),
                confidence=max(current.confidence, rec.confidence),
                raw_line=current.raw_line or rec.raw_line,
            )

    records = list(merged_map.values())
    records.sort(key=lambda item: item.row_index)
    for index, rec in enumerate(records, start=1):
        rec.row_index = index

    payload = {
        "records": [
            {
                "row_index": rec.row_index,
                "deceased_name": {
                    "final_name": rec.deceased_name.final_name,
                    "confidence": rec.deceased_name.confidence,
                    "alternatives": rec.deceased_name.alternatives,
                },
                "national_id": rec.national_id,
                "father_name": {
                    "final_name": rec.father_name.final_name,
                    "confidence": rec.father_name.confidence,
                    "alternatives": rec.father_name.alternatives,
                },
                "cause_of_death": rec.cause_of_death,
                "physician_name": {
                    "final_name": rec.physician_name.final_name,
                    "confidence": rec.physician_name.confidence,
                    "alternatives": rec.physician_name.alternatives,
                },
                "confidence": rec.confidence,
                "raw_line": rec.raw_line,
            }
            for rec in records
        ]
    }
    overall = (
        float(sum(part.confidence for part in parts) / len(parts)) if parts else 0.0
    )
    merged = build_death_extract(payload, overall_confidence=overall)
    merged.details["merged_passes"] = len(parts)
    return merged
