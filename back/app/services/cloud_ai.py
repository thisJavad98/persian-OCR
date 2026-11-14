"""High-accuracy cloud LLM client for Persian OCR (vision + text).

Prefers strong document models over local tiny Ollama weights:
  OpenAI GPT-4o → Anthropic Claude → Google Gemini → (caller falls back to Ollama)

Cursor SDK is intentionally not used here — it is a coding agent, not a
document / vision OCR model.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence

import httpx
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CloudAiConfig:
    provider: str  # openai | anthropic | gemini
    model: str
    api_key: str


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def resolve_cloud_config() -> Optional[CloudAiConfig]:
    """Pick the best available cloud provider from env."""
    forced = _env("AI_PROVIDER", "auto").lower()
    if forced in {"0", "off", "none", "ollama"}:
        return None

    candidates: List[CloudAiConfig] = []

    openai_key = _env("OPENAI_API_KEY")
    if openai_key:
        candidates.append(
            CloudAiConfig(
                provider="openai",
                model=_env("OPENAI_MODEL", "gpt-4o"),
                api_key=openai_key,
            )
        )

    anthropic_key = _env("ANTHROPIC_API_KEY")
    if anthropic_key:
        candidates.append(
            CloudAiConfig(
                provider="anthropic",
                model=_env("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                api_key=anthropic_key,
            )
        )

    gemini_key = _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")
    if gemini_key:
        candidates.append(
            CloudAiConfig(
                provider="gemini",
                model=_env("GEMINI_MODEL", "gemini-2.0-flash"),
                api_key=gemini_key,
            )
        )

    if not candidates:
        return None

    if forced in {"openai", "anthropic", "gemini"}:
        for item in candidates:
            if item.provider == forced:
                return item
        logger.warning("AI_PROVIDER=%s set but no matching API key", forced)
        return None

    # auto: OpenAI first (strongest structured OCR JSON), then Claude, then Gemini.
    return candidates[0]


class CloudAiClient:
    """Thin multi-provider chat / vision client returning text (often JSON)."""

    def __init__(self, config: Optional[CloudAiConfig] = None) -> None:
        self.config = config if config is not None else resolve_cloud_config()

    @property
    def available(self) -> bool:
        return self.config is not None

    @property
    def label(self) -> str:
        if not self.config:
            return ""
        return f"{self.config.provider}:{self.config.model}"

    def complete_text(
        self,
        prompt: str,
        *,
        system: str = "",
        json_mode: bool = True,
        timeout: float = 60.0,
        max_tokens: int = 2048,
    ) -> str:
        if not self.config:
            raise RuntimeError("Cloud AI is not configured")
        provider = self.config.provider
        if provider == "openai":
            return self._openai_chat(
                prompt,
                system=system,
                images=None,
                json_mode=json_mode,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        if provider == "anthropic":
            return self._anthropic_chat(
                prompt,
                system=system,
                images=None,
                json_mode=json_mode,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        if provider == "gemini":
            return self._gemini_chat(
                prompt,
                system=system,
                images=None,
                json_mode=json_mode,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        raise RuntimeError(f"Unknown cloud provider: {provider}")

    def complete_vision(
        self,
        prompt: str,
        image: Image.Image,
        *,
        system: str = "",
        json_mode: bool = True,
        timeout: float = 180.0,
        max_tokens: int = 8192,
    ) -> str:
        if not self.config:
            raise RuntimeError("Cloud AI is not configured")
        images = [_image_payload(image)]
        provider = self.config.provider
        if provider == "openai":
            return self._openai_chat(
                prompt,
                system=system,
                images=images,
                json_mode=json_mode,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        if provider == "anthropic":
            return self._anthropic_chat(
                prompt,
                system=system,
                images=images,
                json_mode=json_mode,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        if provider == "gemini":
            return self._gemini_chat(
                prompt,
                system=system,
                images=images,
                json_mode=json_mode,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        raise RuntimeError(f"Unknown cloud provider: {provider}")

    def complete_json(
        self,
        prompt: str,
        *,
        system: str = "",
        image: Optional[Image.Image] = None,
        timeout: float = 120.0,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        if image is not None:
            raw = self.complete_vision(
                prompt,
                image,
                system=system,
                json_mode=True,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        else:
            raw = self.complete_text(
                prompt,
                system=system,
                json_mode=True,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        return parse_json_object(raw)

    def _openai_chat(
        self,
        prompt: str,
        *,
        system: str,
        images: Optional[Sequence[Dict[str, str]]],
        json_mode: bool,
        timeout: float,
        max_tokens: int,
    ) -> str:
        assert self.config is not None
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for item in images or []:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{item['mime']};base64,{item['b64']}",
                        "detail": "high",
                    },
                }
            )
        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        body: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                _env("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            data = response.json()
        return str((((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "").strip()

    def _anthropic_chat(
        self,
        prompt: str,
        *,
        system: str,
        images: Optional[Sequence[Dict[str, str]]],
        json_mode: bool,
        timeout: float,
        max_tokens: int,
    ) -> str:
        assert self.config is not None
        content: List[Dict[str, Any]] = []
        for item in images or []:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": item["mime"],
                        "data": item["b64"],
                    },
                }
            )
        text = prompt
        if json_mode:
            text += "\n\nReturn ONLY a valid JSON object. No markdown."
        content.append({"type": "text", "text": text})
        body: Dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": content}],
        }
        if system:
            body["system"] = system
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.config.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            data = response.json()
        parts = []
        for block in data.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(parts).strip()

    def _gemini_chat(
        self,
        prompt: str,
        *,
        system: str,
        images: Optional[Sequence[Dict[str, str]]],
        json_mode: bool,
        timeout: float,
        max_tokens: int,
    ) -> str:
        assert self.config is not None
        parts: List[Dict[str, Any]] = []
        text = prompt
        if system:
            text = f"{system}\n\n{text}"
        if json_mode:
            text += "\n\nReturn ONLY a valid JSON object. No markdown."
        parts.append({"text": text})
        for item in images or []:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": item["mime"],
                        "data": item["b64"],
                    }
                }
            )
        body: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": max_tokens,
            },
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.config.model}:generateContent"
        )
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                url,
                params={"key": self.config.api_key},
                headers={"Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
            data = response.json()
        out_parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
        texts = [str(p.get("text") or "") for p in out_parts if isinstance(p, dict)]
        return "\n".join(texts).strip()


def _image_payload(image: Image.Image, *, max_side: int = 1600) -> Dict[str, str]:
    # 1600px side keeps document detail while cutting upload/vision latency hard.
    max_side = int(os.getenv("OCR_VISION_MAX_SIDE", str(max_side)) or max_side)
    rgb = image.convert("RGB")
    w, h = rgb.size
    scale = min(1.0, max_side / float(max(w, h)))
    if scale < 1.0:
        rgb = rgb.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.LANCZOS,
        )
    buf = BytesIO()
    rgb.save(buf, format="JPEG", quality=88)
    return {
        "mime": "image/jpeg",
        "b64": base64.b64encode(buf.getvalue()).decode("ascii"),
    }


def parse_json_object(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


_client: Optional[CloudAiClient] = None


def get_cloud_ai() -> CloudAiClient:
    global _client
    if _client is None:
        _client = CloudAiClient()
    return _client


def reset_cloud_ai() -> None:
    global _client
    _client = None
