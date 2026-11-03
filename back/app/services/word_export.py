"""Word (.docx) export — OCR AI polished Persian / Nasta'liq document."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from app.services.word_ai import polish_for_word


def _set_run_rtl(run) -> None:
    rpr = run._element.get_or_add_rPr()
    rtl = rpr.find(qn("w:rtl"))
    if rtl is None:
        from docx.oxml import OxmlElement

        rtl = OxmlElement("w:rtl")
        rpr.append(rtl)


def _add_rtl_paragraph(
    doc: Document,
    text: str,
    *,
    bold: bool = False,
    size: int = 12,
    color: Optional[RGBColor] = None,
):
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    paragraph.paragraph_format.space_after = Pt(6)
    paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    ppr = paragraph._p.get_or_add_pPr()
    from docx.oxml import OxmlElement

    bidi = OxmlElement("w:bidi")
    ppr.append(bidi)
    run = paragraph.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = "Tahoma"
    run._element.rPr.rFonts.set(qn("w:cs"), "Tahoma")
    if color is not None:
        run.font.color.rgb = color
    _set_run_rtl(run)
    return paragraph


def _add_records_table(doc: Document, records: Sequence[Dict[str, Any]]) -> None:
    if not records:
        return
    headers = ["ردیف", "نام متوفی", "کد ملی", "نام پدر", "علت فوت", "پزشک", "معتبر؟"]
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for idx, title in enumerate(headers):
        cell = table.rows[0].cells[idx]
        cell.text = title
        for paragraph in cell.paragraphs:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            for run in paragraph.runs:
                run.bold = True
                run.font.size = Pt(10)
                run.font.name = "Tahoma"
                _set_run_rtl(run)

    for item in records:
        deceased = item.get("deceased_name") or {}
        father = item.get("father_name") or {}
        physician = item.get("physician_name") or {}
        values = [
            str(item.get("row_index") or ""),
            str(deceased.get("final_name") or ""),
            str(item.get("national_id") or ""),
            str(father.get("final_name") or ""),
            str(item.get("cause_of_death") or ""),
            str(physician.get("final_name") or ""),
            "بله" if deceased.get("is_valid_iranian") else "بازبینی",
        ]
        row = table.add_row().cells
        for idx, value in enumerate(values):
            row[idx].text = value
            for paragraph in row[idx].paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                for run in paragraph.runs:
                    run.font.size = Pt(10)
                    run.font.name = "Tahoma"
                    _set_run_rtl(run)
    doc.add_paragraph()


def build_word(
    *,
    filename: str,
    full_text: str,
    death_records: Optional[Dict[str, Any]] = None,
    engine: Optional[str] = None,
    confidence: Optional[float] = None,
    row_slices: Optional[List[Dict[str, Any]]] = None,
    lines: Optional[Sequence[str]] = None,
    words: Optional[Sequence[str]] = None,
    bina_words: Optional[List[Dict[str, Any]]] = None,
    use_ai: bool = True,
) -> bytes:
    doc = Document()

    records = (death_records or {}).get("records") or []
    details = (death_records or {}).get("details") or {}
    ai_names = (death_records or {}).get("ai_names") or details.get("ai_names") or {}
    cached_polish = details.get("word_ai") or {}
    detected_words = list(bina_words or details.get("bina_words") or [])
    word_texts = [
        str(w)
        for w in (words or [item.get("text") for item in detected_words] or [])
        if str(w or "").strip()
    ]

    if use_ai and not cached_polish.get("paragraphs"):
        polish = polish_for_word(
            full_text=full_text or "",
            lines=list(lines or []),
            records=list(records),
            words=word_texts,
        )
    elif cached_polish.get("paragraphs"):
        polish = cached_polish
    else:
        polish = polish_for_word(
            full_text=full_text or "",
            lines=list(lines or []),
            records=list(records),
            words=word_texts,
        ) if use_ai else {
            "title": "خروجی OCR فارسی — خط‌خوان",
            "paragraphs": [ln for ln in str(full_text or "").splitlines() if ln.strip()],
            "structured_rows": [],
            "valid_words": list(ai_names.get("valid_words") or []),
            "ai_available": False,
            "model": "off",
            "notes": "",
        }

    title = str(polish.get("title") or "خروجی OCR فارسی — خط‌خوان")
    _add_rtl_paragraph(doc, title, bold=True, size=16)
    _add_rtl_paragraph(doc, f"فایل منبع: {filename}")
    if engine:
        _add_rtl_paragraph(doc, f"موتور OCR: {engine}", size=11)
    if confidence is not None:
        _add_rtl_paragraph(doc, f"اطمینان: {round(float(confidence) * 100)}٪", size=11)
    model = polish.get("model") or "lexicon"
    ai_flag = "فعال" if polish.get("ai_available") else "واژه‌نامه / آفلاین"
    _add_rtl_paragraph(doc, f"عامل Word AI: {model} ({ai_flag})", size=11)

    # 1) AI-cleaned body — primary Word deliverable (i2OCR-style readable text).
    paragraphs = list(polish.get("paragraphs") or [])
    if paragraphs:
        _add_rtl_paragraph(doc, "متن پاک‌سازی‌شده برای Word", bold=True, size=13)
        for block in paragraphs:
            if str(block).strip():
                _add_rtl_paragraph(doc, str(block).strip(), size=12)

    # 2) Structured deceased table.
    if records:
        _add_rtl_paragraph(
            doc,
            "جدول متوفیان (نام‌های اعتبارسنجی‌شده)",
            bold=True,
            size=13,
        )
        _add_records_table(doc, records)

        for item in records:
            deceased = item.get("deceased_name") or {}
            row_sims = item.get("name_similarities") or deceased.get("alternatives") or []
            if not row_sims:
                continue
            alt_text = "؛ ".join(
                (
                    f"ردیف {a.get('row_index')}: {a.get('name')} ({a.get('similarity')}٪)"
                    if a.get("row_index")
                    else f"{a.get('name')} ({a.get('similarity')}٪)"
                )
                for a in row_sims[:12]
            )
            _add_rtl_paragraph(
                doc,
                f"شباهت ردیف {item.get('row_index')} ({deceased.get('final_name') or '—'}): {alt_text}",
                size=9,
                color=RGBColor(0x8A, 0x8C, 0x92),
            )

    # 3) Detected Persian words (Bina + classic OCR) — skip digit-only noise.
    letter_words = [
        item
        for item in detected_words
        if re.search(r"[\u0600-\u06FF]", str(item.get("text") or ""))
    ]
    if letter_words:
        _add_rtl_paragraph(doc, "واژه‌های تشخیص‌شده (Bina / OCR)", bold=True, size=13)
        for item in letter_words[:400]:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            score = item.get("confidence")
            score_txt = f" — {round(float(score) * 100)}٪" if score is not None else ""
            row = item.get("row")
            row_txt = f" [ردیف {row}]" if row is not None else ""
            _add_rtl_paragraph(doc, f"{text}{score_txt}{row_txt}", size=11)

    # 4) Valid Iranian words/names from OCR AI.
    valid_words = list(polish.get("valid_words") or ai_names.get("valid_words") or [])
    if valid_words:
        _add_rtl_paragraph(doc, "واژه‌ها و نام‌های معتبر ایرانی", bold=True, size=13)
        _add_rtl_paragraph(doc, "، ".join(valid_words), size=12)

    comparisons = (death_records or {}).get("similar_name_pairs") or ai_names.get("comparisons") or []
    if comparisons:
        _add_rtl_paragraph(doc, "مقایسه نام‌های مشابه", bold=True, size=13)
        for pair in comparisons[:50]:
            _add_rtl_paragraph(
                doc,
                f"{pair.get('left')} ≈ {pair.get('right')} — {pair.get('similarity')}٪",
                size=11,
            )

    # 5) Raw OCR fallback appendix when AI body is short.
    summary = (death_records or {}).get("summary_text") or full_text
    if summary and len(paragraphs) < 2:
        _add_rtl_paragraph(doc, "پیوست متن خام OCR", bold=True, size=13)
        for block in str(summary).splitlines():
            if block.strip():
                _add_rtl_paragraph(doc, block.strip(), size=11)

    # 6) Row image slices at bottom.
    slices = row_slices or ((death_records or {}).get("details") or {}).get("row_slices") or []
    if slices:
        _add_rtl_paragraph(
            doc,
            "برش تصویر ردیف‌ها (پس از ارتقای کیفیت تصویر)",
            bold=True,
            size=13,
        )
        for item in slices:
            label = item.get("label") or f"ردیف {item.get('row_index')}"
            _add_rtl_paragraph(doc, f"ردیف {item.get('row_index')}: {label}", size=11)
            path = Path(str(item.get("path") or ""))
            if path.exists():
                try:
                    doc.add_picture(str(path), width=Inches(5.8))
                except Exception:
                    _add_rtl_paragraph(doc, "نتوانست برش تصویر را اضافه کند.", size=10)

    note_text = str(
        polish.get("notes")
        or "خروجی Word با عامل OCR AI پاک‌سازی شده؛ نام‌ها با فهرست ایرانی اعتبارسنجی شده‌اند."
    )
    _add_rtl_paragraph(doc, note_text, size=9, color=RGBColor(0x8A, 0x8C, 0x92))

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
