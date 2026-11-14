"""Simple Word export for AI OCR transcript."""

from __future__ import annotations

from io import BytesIO
from typing import Any, Optional, Sequence

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Pt


def _set_run_rtl(run) -> None:
    rpr = run._element.get_or_add_rPr()
    rtl = rpr.find(qn("w:rtl"))
    if rtl is None:
        from docx.oxml import OxmlElement

        rtl = OxmlElement("w:rtl")
        rpr.append(rtl)


def _add_rtl(doc: Document, text: str, *, bold: bool = False, size: int = 12):
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
    lines: Sequence[str] = (),
    words: Sequence[str] = (),
    sentences: Sequence[str] = (),
    engine: Optional[str] = None,
    confidence: Optional[float] = None,
    **_: Any,
) -> bytes:
    doc = Document()
    _add_rtl(doc, "خروجی OCR — خط‌خوان", bold=True, size=16)
    _add_rtl(doc, f"فایل: {filename}", size=10)
    if engine:
        _add_rtl(doc, f"موتور AI: {engine}", size=10)
    if confidence is not None:
        _add_rtl(doc, f"اطمینان: {round(confidence * 100)}٪", size=10)

    _add_rtl(doc, "متن کامل", bold=True, size=13)
    body = full_text.strip() or "\n".join(str(x) for x in lines if str(x).strip())
    for block in (body or "متنی یافت نشد").splitlines() or ["متنی یافت نشد"]:
        _add_rtl(doc, block, size=12)

    if sentences:
        _add_rtl(doc, "جملات", bold=True, size=13)
        for sentence in sentences:
            if str(sentence).strip():
                _add_rtl(doc, str(sentence), size=12)

    if words:
        _add_rtl(doc, "واژه‌ها", bold=True, size=13)
        _add_rtl(doc, "، ".join(str(w) for w in words if str(w).strip()), size=11)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
