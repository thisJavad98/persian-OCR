from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg2://localhost:5432/persian_ocr"
    upload_dir: str = "uploads"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    ocr_languages: str = "fa,en"
    ocr_use_gpu: bool = False
    ocr_max_image_side: int = 3200
    ocr_min_confidence: float = 0.80
    bina_model_dir: str = "models/bina-0.2"
    bina_device: str = "cpu"
    bina_score_threshold: float = 0.0
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def bina_model_path(self) -> Path:
        path = Path(self.bina_model_dir)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def language_list(self) -> list[str]:
        return [item.strip() for item in self.ocr_languages.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
