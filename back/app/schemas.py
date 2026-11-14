from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class OcrLine(BaseModel):
    text: str
    confidence: float
    box: Optional[List[List[float]]] = None
    row: Optional[int] = None


class OcrWord(BaseModel):
    text: str
    confidence: float
    box: Optional[List[List[float]]] = None
    row: int = 0
    line_index: int = 0


class OcrJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    mime_type: str
    status: str
    extracted_text: Optional[str] = None
    lines: List[OcrLine] = Field(default_factory=list)
    words: List[OcrWord] = Field(default_factory=list)
    sentences: List[str] = Field(default_factory=list)
    table: Optional[Any] = None
    death_records: Optional[Any] = None
    engine: Optional[str] = None
    confidence: Optional[float] = None
    error_message: Optional[str] = None
    warning: Optional[str] = None
    image_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class HealthOut(BaseModel):
    status: str
    database: str
    ocr_ready: bool
    engines: List[str]
    details: Dict[str, Any] = Field(default_factory=dict)
