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


class OcrTableCell(BaseModel):
    text: str
    confidence: float = 0.0
    row: int
    col: int


class OcrTable(BaseModel):
    rows: List[List[str]] = Field(default_factory=list)
    row_count: int = 0
    col_count: int = 0
    cells: List[OcrTableCell] = Field(default_factory=list)


class NameAlternative(BaseModel):
    name: str
    similarity: float


class ResolvedNameOut(BaseModel):
    final_name: str
    confidence: float = 0.0
    alternatives: List[NameAlternative] = Field(default_factory=list)
    gender: str = "unknown"
    is_valid_iranian: bool = False
    similarity: float = 0.0
    source: str = ""
    raw: str = ""


class DeathRecordOut(BaseModel):
    row_index: int
    deceased_name: ResolvedNameOut
    national_id: str = ""
    father_name: ResolvedNameOut = Field(default_factory=lambda: ResolvedNameOut(final_name=""))
    cause_of_death: str = ""
    physician_name: ResolvedNameOut = Field(
        default_factory=lambda: ResolvedNameOut(final_name="")
    )
    confidence: float = 0.0
    raw_line: str = ""
    name_similarities: List["RowNameSimilarity"] = Field(default_factory=list)


class SimilarNamePair(BaseModel):
    left: str
    right: str
    similarity: float
    left_row: Optional[int] = None
    right_row: Optional[int] = None


class RowNameSimilarity(BaseModel):
    row_index: int
    name: str
    similarity: float


class AiNameEntry(BaseModel):
    raw: str = ""
    final_name: str = ""
    gender: str = "unknown"
    is_valid_iranian: bool = False
    confidence: float = 0.0
    similarity: float = 0.0
    alternatives: List[Dict[str, Any]] = Field(default_factory=list)
    source: str = ""


class AiNamesPayload(BaseModel):
    names: List[AiNameEntry] = Field(default_factory=list)
    comparisons: List[Dict[str, Any]] = Field(default_factory=list)
    valid_words: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class DeathRecordsPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    records: List[DeathRecordOut] = Field(default_factory=list)
    similar_name_pairs: List[SimilarNamePair] = Field(default_factory=list)
    summary_text: str = ""
    confidence: float = 0.0
    details: Dict[str, Any] = Field(default_factory=dict)
    ai_names: Optional[AiNamesPayload] = None


class OcrJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    mime_type: str
    status: str
    extracted_text: Optional[str] = None
    lines: List[OcrLine] = Field(default_factory=list)
    words: List[OcrWord] = Field(default_factory=list)
    table: Optional[OcrTable] = None
    death_records: Optional[DeathRecordsPayload] = None
    engine: Optional[str] = None
    confidence: Optional[float] = None
    error_message: Optional[str] = None
    image_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class HealthOut(BaseModel):
    status: str
    database: str
    ocr_ready: bool
    engines: List[str]
    details: Dict[str, Any] = Field(default_factory=dict)
