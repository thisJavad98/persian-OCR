from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, engine
from app.routers import ocr
from app.schemas import HealthOut
from app.services.ocr_engine import get_ocr_service


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    threading.Thread(target=get_ocr_service().warmup, daemon=True, name="ocr-warmup").start()
    yield


settings = get_settings()

app = FastAPI(
    title="Persian OCR API",
    description="High-precision Persian handwriting and printed-text extraction",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ocr.router)


@app.get("/api/health", response_model=HealthOut)
def health() -> HealthOut:
    service = get_ocr_service()
    db_ok = "ok"
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception as exc:  # pragma: no cover
        db_ok = f"error: {exc}"

    return HealthOut(
        status="ok" if db_ok == "ok" else "degraded",
        database=db_ok,
        ocr_ready=service.ready,
        engines=service.engines,
        details={"init_error": service.init_error},
    )
