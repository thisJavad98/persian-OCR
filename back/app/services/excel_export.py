"""Export deceased-list OCR results to Excel (AI-validated Iranian names)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, Side

from app.services.ocr_engine import LineResult
from app.services.table_structure import TableGrid, build_table

_GENDER_FA = {"male": "مرد", "female": "زن", "unknown": "نامشخص"}


def build_excel(
    *,
    filename: str,
    full_text: str,
    lines: List[LineResult],
    confidence: Optional[float],
    engine: Optional[str],
    table: Optional[TableGrid] = None,
    death_records: Optional[Dict[str, Any]] = None,
    min_confidence: float = 0.80,
    row_slices: Optional[List[Dict[str, Any]]] = None,
    bina_words: Optional[List[Dict[str, Any]]] = None,
) -> bytes:
    workbook = Workbook()
    thin = Border(
        left=Side(style="thin", color="CDCED1"),
        right=Side(style="thin", color="CDCED1"),
        top=Side(style="thin", color="CDCED1"),
        bottom=Side(style="thin", color="CDCED1"),
    )

    records = (death_records or {}).get("records") or []
    ai_names = (death_records or {}).get("ai_names") or (death_records or {}).get("details", {}).get(
        "ai_names"
    ) or {}

    if records:
        sheet = workbook.active
        sheet.title = "متوفیان"
        sheet.sheet_view.rightToLeft = True
        headers = [
            "ردیف",
            "نام متوفی",
            "جنسیت",
            "نام ایرانی معتبر",
            "شباهت به فهرست",
            "شباهت با همه ردیف‌ها",
            "کد ملی",
            "نام پدر",
            "علت فوت",
            "پزشک معالج",
            "اطمینان",
            "منبع AI",
        ]
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)

        for item in records:
            deceased = item.get("deceased_name") or {}
            father = item.get("father_name") or {}
            physician = item.get("physician_name") or {}
            row_sims = item.get("name_similarities") or []
            if not row_sims:
                row_sims = [
                    {"name": a.get("name"), "similarity": a.get("similarity"), "row_index": ""}
                    for a in (deceased.get("alternatives") or [])
                ]
            sim_text = "؛ ".join(
                f"ردیف {s.get('row_index')}: {s.get('name')} ({s.get('similarity')}٪)"
                if s.get("row_index") not in ("", None)
                else f"{s.get('name')} ({s.get('similarity')}٪)"
                for s in row_sims
            )
            sheet.append(
                [
                    item.get("row_index"),
                    deceased.get("final_name") or "",
                    _GENDER_FA.get(str(deceased.get("gender") or "unknown"), "نامشخص"),
                    "بله" if deceased.get("is_valid_iranian") else "خیر",
                    deceased.get("similarity") or "",
                    sim_text,
                    item.get("national_id") or "",
                    father.get("final_name") or "",
                    item.get("cause_of_death") or "",
                    physician.get("final_name") or "",
                    round(float(item.get("confidence") or 0), 4),
                    deceased.get("source") or "",
                ]
            )

        widths = [8, 22, 10, 14, 12, 48, 16, 20, 24, 20, 10, 12]
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width
            for row in sheet.iter_rows(min_row=2, min_col=index, max_col=index):
                for cell in row:
                    cell.alignment = Alignment(wrap_text=True, readingOrder=2, vertical="center")
                    cell.border = thin

        similar = workbook.create_sheet("همه شباهت‌ها")
        similar.sheet_view.rightToLeft = True
        similar.append(["ردیف ۱", "نام ۱", "ردیف ۲", "نام ۲", "درصد شباهت"])
        for cell in similar[1]:
            cell.font = Font(bold=True)
        matrix = ((death_records or {}).get("details") or {}).get("row_similarity_matrix") or []
        if matrix:
            for pair in matrix:
                similar.append(
                    [
                        pair.get("left_row"),
                        pair.get("left"),
                        pair.get("right_row"),
                        pair.get("right"),
                        pair.get("similarity"),
                    ]
                )
        else:
            for pair in (death_records or {}).get("similar_name_pairs") or []:
                similar.append(
                    [
                        pair.get("left_row") or "",
                        pair.get("left"),
                        pair.get("right_row") or "",
                        pair.get("right"),
                        pair.get("similarity"),
                    ]
                )

        valid_sheet = workbook.create_sheet("نام‌های معتبر AI")
        valid_sheet.sheet_view.rightToLeft = True
        valid_sheet.append(["نام خام OCR", "نام معتبر", "جنسیت", "شباهت", "معتبر؟", "منبع"])
        for cell in valid_sheet[1]:
            cell.font = Font(bold=True)
        for entry in ai_names.get("names") or []:
            valid_sheet.append(
                [
                    entry.get("raw"),
                    entry.get("final_name"),
                    _GENDER_FA.get(str(entry.get("gender") or "unknown"), "نامشخص"),
                    entry.get("similarity"),
                    "بله" if entry.get("is_valid_iranian") else "خیر",
                    entry.get("source"),
                ]
            )
        for word in ai_names.get("valid_words") or []:
            # Ensure unique valid words appear even if not in names list.
            pass
        if ai_names.get("valid_words"):
            words = workbook.create_sheet("واژه‌های معتبر")
            words.sheet_view.rightToLeft = True
            words.append(["واژه / نام معتبر نستعلیق"])
            words[1][0].font = Font(bold=True)
            for word in ai_names.get("valid_words") or []:
                words.append([word])
    else:
        export_lines = [line for line in lines if line.confidence >= min_confidence] or list(lines)
        grid = table or build_table(export_lines)
        sheet = workbook.active
        sheet.title = "متن"
        sheet.sheet_view.rightToLeft = True
        if grid and grid.rows:
            for row_index, row in enumerate(grid.rows, start=1):
                for col_index, value in enumerate(row, start=1):
                    cell = sheet.cell(row=row_index, column=col_index, value=value)
                    cell.alignment = Alignment(wrap_text=True, readingOrder=2)
        else:
            sheet["A1"] = full_text or "متنی یافت نشد"

    detected = list(
        bina_words
        or ((death_records or {}).get("details") or {}).get("bina_words")
        or []
    )
    if detected:
        words_sheet = workbook.create_sheet("واژه‌های Bina")
        words_sheet.sheet_view.rightToLeft = True
        words_sheet.append(["ردیف", "واژه", "اطمینان", "اندیس خط", "جعبه"])
        for cell in words_sheet[1]:
            cell.font = Font(bold=True)
        for item in detected:
            box = item.get("box")
            box_txt = ""
            if box:
                try:
                    flat = [f"{float(p[0]):.1f},{float(p[1]):.1f}" for p in box]
                    box_txt = " | ".join(flat)
                except (TypeError, ValueError, IndexError):
                    box_txt = str(box)
            words_sheet.append(
                [
                    item.get("row"),
                    item.get("text"),
                    round(float(item.get("confidence") or 0), 4),
                    item.get("line_index"),
                    box_txt,
                ]
            )
        for index, width in enumerate([8, 28, 12, 10, 48], start=1):
            words_sheet.column_dimensions[words_sheet.cell(row=1, column=index).column_letter].width = width

    summary = workbook.create_sheet("خلاصه")
    summary["A1"] = "نام فایل"
    summary["B1"] = filename
    summary["A2"] = "موتور"
    summary["B2"] = engine or "-"
    summary["A3"] = "اطمینان"
    summary["B3"] = round(confidence or 0.0, 4)
    summary["A4"] = "تعداد متوفیان"
    summary["B4"] = len(records)
    summary["A5"] = "عامل نام AI"
    summary["B5"] = (
        ((death_records or {}).get("details") or {}).get("name_agent") or {}
    ).get("model") or "lexicon"
    summary["A6"] = "تعداد واژه‌های Bina"
    summary["B6"] = len(detected)
    summary["A7"] = "متن خلاصه"
    summary["A8"] = (death_records or {}).get("summary_text") or full_text
    summary["A8"].alignment = Alignment(wrap_text=True, readingOrder=2)
    summary.column_dimensions["A"].width = 22
    summary.column_dimensions["B"].width = 80

    # Bottom of export: per-row image slices from the enhanced page.
    slices = row_slices or ((death_records or {}).get("details") or {}).get("row_slices") or []
    if slices:
        slice_sheet = workbook.create_sheet("برش تصویر ردیف‌ها")
        slice_sheet.sheet_view.rightToLeft = True
        slice_sheet["A1"] = "برش‌های تصویر پس از ارتقای کیفیت (متناظر با ردیف‌های خروجی)"
        slice_sheet["A1"].font = Font(bold=True, size=13)
        slice_sheet.merge_cells("A1:D1")
        slice_sheet.append([])
        slice_sheet.append(["ردیف", "برچسب / متن", "مسیر", "تصویر برش"])
        for cell in slice_sheet[3]:
            cell.font = Font(bold=True)
        slice_sheet.column_dimensions["A"].width = 10
        slice_sheet.column_dimensions["B"].width = 40
        slice_sheet.column_dimensions["C"].width = 28
        slice_sheet.column_dimensions["D"].width = 48

        excel_row = 4
        for item in slices:
            path = Path(str(item.get("path") or ""))
            label = str(item.get("label") or "")
            slice_sheet.cell(row=excel_row, column=1, value=item.get("row_index"))
            slice_sheet.cell(row=excel_row, column=2, value=label)
            slice_sheet.cell(row=excel_row, column=3, value=item.get("filename") or path.name)
            if path.exists():
                try:
                    xl_img = XLImage(str(path))
                    # Keep readable strip height in the sheet.
                    max_width = 420
                    if xl_img.width and xl_img.width > max_width:
                        ratio = max_width / float(xl_img.width)
                        xl_img.width = int(xl_img.width * ratio)
                        xl_img.height = int(xl_img.height * ratio)
                    slice_sheet.row_dimensions[excel_row].height = max(
                        40, min(140, (xl_img.height or 40) * 0.75)
                    )
                    slice_sheet.add_image(xl_img, f"D{excel_row}")
                except Exception:
                    slice_sheet.cell(row=excel_row, column=4, value=" entکه در بارگذاری تصویر")
            else:
                slice_sheet.cell(row=excel_row, column=4, value="فایل برش موجود نیست")
            excel_row += 1

        # Also append a compact preview block under the main records sheet.
        if records:
            main = workbook["متوفیان"]
            anchor = len(records) + 4
            main.cell(row=anchor, column=1, value="برش تصویر ردیف‌ها (پایین خروجی)")
            main.cell(row=anchor, column=1).font = Font(bold=True)
            preview_row = anchor + 2
            for item in slices:
                path = Path(str(item.get("path") or ""))
                main.cell(row=preview_row, column=1, value=f"ردیف {item.get('row_index')}")
                main.cell(row=preview_row, column=2, value=item.get("label") or "")
                if path.exists():
                    try:
                        xl_img = XLImage(str(path))
                        max_width = 520
                        if xl_img.width and xl_img.width > max_width:
                            ratio = max_width / float(xl_img.width)
                            xl_img.width = int(xl_img.width * ratio)
                            xl_img.height = int(xl_img.height * ratio)
                        main.row_dimensions[preview_row].height = max(
                            36, min(120, (xl_img.height or 36) * 0.75)
                        )
                        main.add_image(xl_img, f"C{preview_row}")
                    except Exception:
                        pass
                preview_row += 1

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
