from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import OcrJob
from app.schemas import DeathRecordsPayload, OcrJobOut, OcrLine, OcrTable, OcrWord
from app.services.excel_export import build_excel
from app.services.ocr_engine import LineResult, get_ocr_service
from app.services.preprocess import enhance_for_ocr
from app.services.row_slices import build_row_slices
from app.services.table_structure import build_table, table_from_payload
from app.services.word_ai import polish_for_word
from app.services.word_export import build_word

router = APIRouter(prefix="/api/ocr", tags=["ocr"])

ALLOWED_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/bmp",
    "image/tiff",
}


def _lines_from_job(job: OcrJob) -> list[LineResult]:
    lines: list[LineResult] = []
    if not job.lines_json:
        return lines
    try:
        for item in json.loads(job.lines_json):
            lines.append(
                LineResult(
                    text=item.get("text", ""),
                    confidence=float(item.get("confidence", 0)),
                    box=item.get("box"),
                )
            )
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    return lines


def _table_for_job(job: OcrJob) -> OcrTable | None:
    if job.table_json:
        try:
            grid = table_from_payload(json.loads(job.table_json))
            if grid is not None:
                return OcrTable.model_validate(grid.as_dict())
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return None


def _records_for_job(job: OcrJob) -> DeathRecordsPayload | None:
    if not job.records_json:
        return None
    try:
        return DeathRecordsPayload.model_validate(json.loads(job.records_json))
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _words_from_records(job: OcrJob) -> list[OcrWord]:
    records = _job_records_dict(job) or {}
    raw_words = ((records.get("details") or {}).get("bina_words")) or []
    words: list[OcrWord] = []
    for item in raw_words:
        try:
            words.append(OcrWord.model_validate(item))
        except (ValueError, TypeError):
            continue
    return words


def _serialize_job(job: OcrJob) -> OcrJobOut:
    lines: list[OcrLine] = []
    if job.lines_json:
        try:
            raw = json.loads(job.lines_json)
            lines = [OcrLine.model_validate(item) for item in raw]
        except (json.JSONDecodeError, ValueError):
            lines = []

    return OcrJobOut(
        id=job.id,
        filename=job.filename,
        mime_type=job.mime_type,
        status=job.status,
        extracted_text=job.extracted_text,
        lines=lines,
        words=_words_from_records(job),
        table=_table_for_job(job),
        death_records=_records_for_job(job),
        engine=job.engine,
        confidence=job.confidence,
        error_message=job.error_message,
        image_url=f"/api/ocr/{job.id}/image",
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post("/upload", response_model=OcrJobOut)
async def upload_and_extract(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> OcrJobOut:
    settings = get_settings()
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Only image uploads are supported.")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")

    suffix = Path(file.filename or "upload.png").suffix.lower() or ".png"
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    target = settings.upload_path / stored_name

    async with aiofiles.open(target, "wb") as handle:
        await handle.write(raw)

    job = OcrJob(
        filename=file.filename or stored_name,
        stored_name=stored_name,
        mime_type=content_type,
        status="processing",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        with Image.open(target) as image:
            image.load()
            # 1) Upscale / enhance quality first, then extract words.
            enhanced = enhance_for_ocr(image.copy())
            enhanced_name = f"{Path(stored_name).stem}_enhanced.png"
            enhanced_path = settings.upload_path / enhanced_name
            enhanced.save(enhanced_path, format="PNG", optimize=True)

            result = get_ocr_service().extract(enhanced.copy())

            records_payload = result.death_records or {}
            record_rows = list(records_payload.get("records") or [])
            slice_count = len(record_rows) or max(len(result.lines), 1)
            labels = []
            for item in record_rows:
                deceased = (item.get("deceased_name") or {}).get("final_name") or ""
                raw = item.get("raw_line") or ""
                labels.append(deceased or raw)
            if not labels:
                labels = [line.text for line in result.lines]

            slice_dir = settings.upload_path / f"{Path(stored_name).stem}_slices"
            slices = build_row_slices(
                enhanced,
                slice_count,
                slice_dir,
                labels=labels,
            )
            # Public URLs for UI + export metadata (absolute path kept for Excel/Word embed).
            for item in slices:
                item["url"] = f"/api/ocr/{job.id}/slice/{item['filename']}"
            details = dict(records_payload.get("details") or {})
            details["enhanced_image"] = enhanced_name
            details["row_slices"] = slices
            bina_words = [word.as_dict() for word in (result.words or [])]
            details["bina_words"] = bina_words
            details["bina"] = (result.details or {}).get("bina") or {
                "word_count": len(bina_words),
                "engine": result.engine,
            }
            # OCR AI polish for better Word export (cached on the job).
            try:
                details["word_ai"] = polish_for_word(
                    full_text=result.text or "",
                    lines=[line.text for line in result.lines],
                    records=list(record_rows),
                    words=[word.text for word in (result.words or [])],
                )
            except Exception:
                details["word_ai"] = {"ai_available": False, "paragraphs": [], "valid_words": []}
            if result.death_records is not None:
                result.death_records = dict(result.death_records)
                result.death_records["details"] = details
            else:
                result.death_records = {
                    "records": [],
                    "similar_name_pairs": [],
                    "summary_text": result.text or "",
                    "confidence": result.confidence or 0.0,
                    "details": details,
                }

        job.status = "completed"
        job.extracted_text = result.text
        job.engine = result.engine
        job.confidence = result.confidence
        job.lines_json = json.dumps(
            [
                {
                    "text": line.text,
                    "confidence": line.confidence,
                    "box": line.box,
                    "row": line.row,
                }
                for line in result.lines
            ],
            ensure_ascii=False,
        )
        if result.death_records:
            job.records_json = json.dumps(result.death_records, ensure_ascii=False)
            job.table_json = None
        elif result.table_rows:
            from app.services.table_structure import TableCell, TableGrid

            rows = result.table_rows
            cells = [
                TableCell(text=cell, confidence=result.confidence, row=r, col=c)
                for r, row in enumerate(rows)
                for c, cell in enumerate(row)
                if str(cell).strip()
            ]
            table = TableGrid(
                rows=rows,
                cells=cells,
                row_count=len(rows),
                col_count=max((len(row) for row in rows), default=0),
            )
            job.table_json = json.dumps(table.as_dict(), ensure_ascii=False)
        else:
            table = build_table(result.lines)
            job.table_json = json.dumps(table.as_dict(), ensure_ascii=False) if table.rows else None
        job.error_message = None
    except UnidentifiedImageError:
        job.status = "failed"
        job.error_message = "Uploaded file is not a readable image."
    except Exception as exc:  # pragma: no cover - runtime OCR failures
        job.status = "failed"
        job.error_message = str(exc)

    db.commit()
    db.refresh(job)
    return _serialize_job(job)


@router.get("/{job_id}", response_model=OcrJobOut)
def get_job(job_id: int, db: Session = Depends(get_db)) -> OcrJobOut:
    job = db.get(OcrJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _serialize_job(job)


@router.get("/{job_id}/image")
def get_job_image(job_id: int, db: Session = Depends(get_db)) -> FileResponse:
    settings = get_settings()
    job = db.get(OcrJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    # Prefer enhanced image when available.
    enhanced = settings.upload_path / f"{Path(job.stored_name).stem}_enhanced.png"
    path = enhanced if enhanced.exists() else settings.upload_path / job.stored_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file missing.")
    media = "image/png" if path.suffix.lower() == ".png" else job.mime_type
    return FileResponse(path, media_type=media, filename=path.name)


@router.get("/{job_id}/slice/{slice_name}")
def get_job_slice(job_id: int, slice_name: str, db: Session = Depends(get_db)) -> FileResponse:
    settings = get_settings()
    job = db.get(OcrJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    safe_name = Path(slice_name).name
    if not safe_name.startswith("row-") or not safe_name.endswith(".png"):
        raise HTTPException(status_code=400, detail="Invalid slice name.")
    path = settings.upload_path / f"{Path(job.stored_name).stem}_slices" / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Slice not found.")
    return FileResponse(path, media_type="image/png", filename=safe_name)


def _job_records_dict(job: OcrJob) -> Optional[dict[str, Any]]:
    if not job.records_json:
        return None
    try:
        return json.loads(job.records_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _bina_words_from_job(job: OcrJob) -> list[dict[str, Any]]:
    records = _job_records_dict(job) or {}
    return list(((records.get("details") or {}).get("bina_words")) or [])


@router.get("/{job_id}/excel")
def download_excel(job_id: int, db: Session = Depends(get_db)) -> Response:
    job = db.get(OcrJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="OCR is not completed yet.")

    lines = _lines_from_job(job)
    table = None
    if job.table_json:
        try:
            table = table_from_payload(json.loads(job.table_json))
        except (json.JSONDecodeError, TypeError, ValueError):
            table = None

    records = _job_records_dict(job)
    slices = ((records or {}).get("details") or {}).get("row_slices") or []
    payload = build_excel(
        filename=job.filename,
        full_text=job.extracted_text or "",
        lines=lines,
        confidence=job.confidence,
        engine=job.engine,
        table=table,
        death_records=records,
        min_confidence=get_settings().ocr_min_confidence,
        row_slices=slices,
        bina_words=_bina_words_from_job(job),
    )
    download_name = f"deceased-list-{job.id}.xlsx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


@router.get("/{job_id}/word")
def download_word(job_id: int, db: Session = Depends(get_db)) -> Response:
    """Word export of AI-validated Persian / Nasta'liq names (i2OCR-style deliverable)."""
    job = db.get(OcrJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="OCR is not completed yet.")

    records = _job_records_dict(job)
    slices = ((records or {}).get("details") or {}).get("row_slices") or []
    line_texts = [line.text for line in _lines_from_job(job)]
    bina_words = _bina_words_from_job(job)
    word_texts = [str(item.get("text") or "") for item in bina_words if item.get("text")]
    # Refresh Word AI polish on download when cache is empty.
    if records is not None:
        details = dict(records.get("details") or {})
        if not (details.get("word_ai") or {}).get("paragraphs"):
            try:
                details["word_ai"] = polish_for_word(
                    full_text=job.extracted_text or "",
                    lines=line_texts,
                    records=list(records.get("records") or []),
                    words=word_texts,
                )
                records["details"] = details
                job.records_json = json.dumps(records, ensure_ascii=False)
                db.commit()
            except Exception:
                pass
    payload = build_word(
        filename=job.filename,
        full_text=job.extracted_text or "",
        death_records=records,
        engine=job.engine,
        confidence=job.confidence,
        row_slices=slices,
        lines=line_texts,
        words=word_texts,
        bina_words=bina_words,
        use_ai=True,
    )
    download_name = f"nastaliq-names-{job.id}.docx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )
