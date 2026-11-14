"""Simple Excel export for AI OCR transcript."""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font


def build_excel(
    *,
    filename: str,
    full_text: str,
    lines: Sequence[Any] = (),
    words: Sequence[Any] = (),
    sentences: Sequence[str] = (),
    confidence: Optional[float] = None,
    engine: Optional[str] = None,
    **_: Any,
) -> bytes:
    workbook = Workbook()

    text_sheet = workbook.active
    text_sheet.title = "متن"
    text_sheet.sheet_view.rightToLeft = True
    text_sheet["A1"] = "فایل"
    text_sheet["B1"] = filename
    text_sheet["A2"] = "موتور AI"
    text_sheet["B2"] = engine or ""
    text_sheet["A3"] = "اطمینان"
    text_sheet["B3"] = f"{round((confidence or 0) * 100)}%" if confidence is not None else ""
    text_sheet["A5"] = "متن کامل"
    text_sheet["A5"].font = Font(bold=True)
    text_sheet["A6"] = full_text or ""
    text_sheet["A6"].alignment = Alignment(wrap_text=True, vertical="top")
    text_sheet.column_dimensions["A"].width = 18
    text_sheet.column_dimensions["B"].width = 80
    text_sheet.row_dimensions[6].height = 220

    line_sheet = workbook.create_sheet("خطوط")
    line_sheet.sheet_view.rightToLeft = True
    line_sheet.append(["#", "خط", "اطمینان"])
    for cell in line_sheet[1]:
        cell.font = Font(bold=True)
    for index, item in enumerate(lines, start=1):
        if isinstance(item, dict):
            text = str(item.get("text") or "")
            conf = item.get("confidence")
        else:
            text = str(getattr(item, "text", item) or "")
            conf = getattr(item, "confidence", None)
        if not text.strip():
            continue
        line_sheet.append(
            [index, text, f"{round(float(conf) * 100)}%" if conf is not None else ""]
        )
    line_sheet.column_dimensions["B"].width = 80

    sent_sheet = workbook.create_sheet("جملات")
    sent_sheet.sheet_view.rightToLeft = True
    sent_sheet.append(["#", "جمله"])
    for cell in sent_sheet[1]:
        cell.font = Font(bold=True)
    for index, sentence in enumerate(sentences, start=1):
        if str(sentence).strip():
            sent_sheet.append([index, str(sentence)])
    sent_sheet.column_dimensions["B"].width = 80

    word_sheet = workbook.create_sheet("واژه‌ها")
    word_sheet.sheet_view.rightToLeft = True
    word_sheet.append(["#", "واژه", "اطمینان"])
    for cell in word_sheet[1]:
        cell.font = Font(bold=True)
    for index, item in enumerate(words, start=1):
        if isinstance(item, dict):
            text = str(item.get("text") or "")
            conf = item.get("confidence")
        else:
            text = str(item or "")
            conf = None
        if not text.strip():
            continue
        word_sheet.append(
            [index, text, f"{round(float(conf) * 100)}%" if conf is not None else ""]
        )
    word_sheet.column_dimensions["B"].width = 40

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
