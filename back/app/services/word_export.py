"""Word (.docx) export for AI-validated Persian / Nasta'liq names — i2OCR-style deliverable."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


def _set_run_rtl(run) -> None:
    rpr = run._element.get_or_add_rPr()
    rtl = rpr.find(qn("w:rtl"))
    if rtl is None:
        from docx.oxml import OxmlElement

        rtl = OxmlElement("w:rtl")
        rpr.append(rtl)


def _add_rtl_paragraph(doc: Document, text: str, *, bold: bool = False, size: int = 12):
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
    _set_run_rtl(run)
    return paragraph


def build_word(
    *,
    filename: str,
    full_text: str,
    death_records: Optional[Dict[str, Any]] = None,
    engine: Optional[str] = None,
    confidence: Optional[float] = None,
    row_slices: Optional[List[Dict[str, Any]]] = None,
) -> bytes:
    doc = Document()
    section = doc.sections[0]
    section.page_width = section.page_width  # keep default A4-ish

    _add_rtl_paragraph(doc, "خط‌خوان — خروجی نام‌های معتبر نستعلیق", bold=True, size=16)
    _add_rtl_paragraph(doc, f"فایل منبع: {filename}")
    if engine:
        _add_rtl_paragraph(doc, f"موتور: {engine}")
    if confidence is not None:
        _add_rtl_paragraph(doc, f"اطمینان: {round(float(confidence) * 100)}٪")

    records = (death_records or {}).get("records") or []
    ai_names = (death_records or {}).get("ai_names") or {}
    valid_words: List[str] = list(ai_names.get("valid_words") or [])

    if records:
        _add_rtl_paragraph(doc, "فهرست متوفیان (نام‌های اعتبارسنجی‌شده با عامل هوش مصنوعی)", bold=True, size=13)
        for item in records:
            deceased = item.get("deceased_name") or {}
            father = item.get("father_name") or {}
            physician = item.get("physician_name") or {}
            gender = deceased.get("gender") or "unknown"
            gender_fa = {"male": "مرد", "female": "زن"}.get(gender, "نامشخص")
            valid = "✓ معتبر" if deceased.get("is_valid_iranian") else "نیاز به بازبینی"
            line = (
                f"ردیف {item.get('row_index')}: "
                f"متوفی {deceased.get('final_name') or '—'} ({gender_fa}، {valid})؛ "
                f"کد ملی {item.get('national_id') or '—'}؛ "
                f"پدر {father.get('final_name') or '—'}؛ "
                f"علت {item.get('cause_of_death') or '—'}؛ "
                f"پزشک {physician.get('final_name') or '—'}."
            )
            _add_rtl_paragraph(doc, line)

            row_sims = item.get("name_similarities") or deceased.get("alternatives") or []
            if row_sims:
                alt_text = "؛ ".join(
                    (
                        f"ردیف {a.get('row_index')}: {a.get('name')} ({a.get('similarity')}٪)"
                        if a.get("row_index")
                        else f"{a.get('name')} ({a.get('similarity')}٪)"
                    )
                    for a in row_sims
                )
                _add_rtl_paragraph(doc, f"شباهت با همه ردیف‌ها: {alt_text}", size=10)

    if valid_words:
        _add_rtl_paragraph(doc, "واژه‌ها و نام‌های معتبر ایرانی", bold=True, size=13)
        _add_rtl_paragraph(doc, "، ".join(valid_words))

    comparisons = (death_records or {}).get("similar_name_pairs") or ai_names.get("comparisons") or []
    if comparisons:
        _add_rtl_paragraph(doc, "مقایسه نام‌های مشابه", bold=True, size=13)
        for pair in comparisons[:40]:
            _add_rtl_paragraph(
                doc,
                f"{pair.get('left')} ≈ {pair.get('right')} — {pair.get('similarity')}٪",
                size=11,
            )

    summary = (death_records or {}).get("summary_text") or full_text
    if summary:
        _add_rtl_paragraph(doc, "متن استخراج‌شده", bold=True, size=13)
        for block in str(summary).splitlines():
            if block.strip():
                _add_rtl_paragraph(doc, block.strip())

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

    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = note.add_run(
        "خروجی مشابه ابزارهای OCR فارسی آنلاین (متن قابل کپی / Word) — "
        "ابتدا کیفیت تصویر ارتقا یافته، سپس واژه‌ها استخراج و برش هر ردیف در پایین خروجی آمده است."
    )
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x5D, 0x5F, 0x60)
    _set_run_rtl(run)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
