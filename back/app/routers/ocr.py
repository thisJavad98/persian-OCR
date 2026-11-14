from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import OcrJob
from app.schemas import OcrJobOut, OcrLine, OcrWord
from app.services.excel_export import build_excel
from app.services.ocr_engine import get_ocr_service
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


def _meta_from_job(job: OcrJob) -> dict[str, Any]:
    if not job.records_json:
        return {}
    try:
        data = json.loads(job.records_json)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _serialize_job(job: OcrJob) -> OcrJobOut:
    lines: list[OcrLine] = []
    if job.lines_json:
        try:
            raw = json.loads(job.lines_json)
            lines = [OcrLine.model_validate(item) for item in raw]
        except (json.JSONDecodeError, ValueError):
            lines = []

    meta = _meta_from_job(job)
    words: list[OcrWord] = []
    for item in meta.get("words") or []:
        try:
            words.append(OcrWord.model_validate(item))
        except (ValueError, TypeError):
            continue

    sentences = [str(s) for s in (meta.get("sentences") or []) if str(s).strip()]
    warning = meta.get("warning") or ((meta.get("details") or {}).get("warning"))

    return OcrJobOut(
        id=job.id,
        filename=job.filename,
        mime_type=job.mime_type,
        status=job.status,
        extracted_text=job.extracted_text,
        lines=lines,
        words=words,
        sentences=sentences,
        table=None,
        death_records=None,
        engine=job.engine,
        confidence=job.confidence,
        error_message=job.error_message,
        warning=str(warning) if warning else None,
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
            # Light resize only — AI vision models handle document detail well.
            rgb = image.convert("RGB")
            max_side = max(960, int(settings.ocr_max_image_side or 1600))
            w, h = rgb.size
            scale = min(1.0, max_side / float(max(w, h)))
            if scale < 1.0:
                rgb = rgb.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    Image.Resampling.LANCZOS,
                )

            preview_name = f"{Path(stored_name).stem}_preview.jpg"
            preview_path = settings.upload_path / preview_name
            rgb.save(preview_path, format="JPEG", quality=90, optimize=True)

            result = get_ocr_service().extract(rgb)

        details = dict(result.details or {})
        meta = {
            "preview_image": preview_name,
            "mode": "ai-only",
            "sentences": list(result.sentences or []),
            "words": [word.as_dict() for word in (result.words or [])],
            "details": details,
            "warning": details.get("warning"),
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
        job.table_json = None
        job.records_json = json.dumps(meta, ensure_ascii=False)
        job.error_message = None
    except UnidentifiedImageError:
        job.status = "failed"
        job.error_message = "Uploaded file is not a readable image."
    except Exception as exc:  # pragma: no cover
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

    stem = Path(job.stored_name).stem
    for candidate in (
        settings.upload_path / f"{stem}_preview.jpg",
        settings.upload_path / f"{stem}_enhanced.jpg",
        settings.upload_path / f"{stem}_enhanced.png",
        settings.upload_path / job.stored_name,
    ):
        if candidate.exists():
            suffix = candidate.suffix.lower()
            media = (
                "image/png"
                if suffix == ".png"
                else "image/jpeg"
                if suffix in {".jpg", ".jpeg"}
                else job.mime_type
            )
            return FileResponse(candidate, media_type=media, filename=candidate.name)

    raise HTTPException(status_code=404, detail="Image file missing.")


@router.get("/{job_id}/excel")
def download_excel(job_id: int, db: Session = Depends(get_db)) -> Response:
    job = db.get(OcrJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="OCR is not completed yet.")

    meta = _meta_from_job(job)
    lines = []
    if job.lines_json:
        try:
            lines = json.loads(job.lines_json)
        except (json.JSONDecodeError, TypeError, ValueError):
            lines = []

    payload = build_excel(
        filename=job.filename,
        full_text=job.extracted_text or "",
        lines=lines,
        words=meta.get("words") or [],
        sentences=meta.get("sentences") or [],
        confidence=job.confidence,
        engine=job.engine,
    )
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="ocr-{job.id}.xlsx"'},
    )


@router.get("/{job_id}/word")
def download_word(job_id: int, db: Session = Depends(get_db)) -> Response:
    job = db.get(OcrJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="OCR is not completed yet.")

    meta = _meta_from_job(job)
    line_texts: list[str] = []
    if job.lines_json:
        try:
            for item in json.loads(job.lines_json):
                if isinstance(item, dict) and item.get("text"):
                    line_texts.append(str(item["text"]))
        except (json.JSONDecodeError, TypeError, ValueError):
            line_texts = []
    payload = build_word(
        filename=job.filename,
        full_text=job.extracted_text or "",
        lines=line_texts,
        words=[str(w.get("text")) for w in (meta.get("words") or []) if w.get("text")],
        sentences=meta.get("sentences") or [],
        engine=job.engine,
        confidence=job.confidence,
    )
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="ocr-{job.id}.docx"'},
    )
