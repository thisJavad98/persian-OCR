"""Nasta'liq-aware image enhancement for Persian handwriting OCR."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass
class PreprocessResult:
    color_bgr: np.ndarray
    enhanced_bgr: np.ndarray
    binary_bgr: np.ndarray
    variants: list[tuple[str, np.ndarray]]


def _pil_to_bgr(image: Image.Image) -> np.ndarray:
    rgb = np.array(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _limit_side(image: np.ndarray, max_side: int) -> np.ndarray:
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return image
    scale = max_side / float(longest)
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return cv2.resize(image, new_size, interpolation=cv2.INTER_CUBIC)


def _deskew_mild(gray: np.ndarray) -> np.ndarray:
    """Only tiny deskew — Nasta'liq has intentional slant; do not flatten it."""
    binary = cv2.bitwise_not(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
    coords = np.column_stack(np.where(binary > 0))
    if coords.size == 0:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    # Keep calligraphy slant; only fix accidental camera tilt.
    if abs(angle) < 1.0 or abs(angle) > 8:
        return gray
    height, width = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(
        gray,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _enhance_nastaliq(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Preserve connected Nasta'liq strokes; avoid aggressive open/erode."""
    # Mild denoise — strong denoise destroys fine nuqta (dots).
    denoised = cv2.fastNlMeansDenoising(gray, None, h=7, templateWindowSize=7, searchWindowSize=21)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrast = clahe.apply(denoised)
    # Soft unsharp; keep continuous ink ribbons.
    blurred = cv2.GaussianBlur(contrast, (0, 0), 1.0)
    enhanced = cv2.addWeighted(contrast, 1.2, blurred, -0.2, 0)

    # Soft adaptive threshold as optional variant (not primary for Nastaliq).
    adaptive = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        35,
        15,
    )
    if np.mean(adaptive) < 127:
        adaptive = cv2.bitwise_not(adaptive)
    return enhanced, adaptive


def enhance_for_ocr(
    image: Image.Image,
    *,
    min_side: int = 1800,
    max_side: int = 3600,
) -> Image.Image:
    """Upscale + sharpen + contrast BEFORE OCR / word export."""
    color = _pil_to_bgr(image)
    height, width = color.shape[:2]
    longest = max(height, width)
    shortest = min(height, width)

    # Upscale small/medium scans first so Nasta'liq strokes are clearer.
    if shortest < min_side:
        scale = min_side / float(shortest)
        # Cap so huge pages stay manageable.
        if longest * scale > max_side:
            scale = max_side / float(longest)
        if scale > 1.01:
            color = cv2.resize(
                color,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_CUBIC,
            )
    elif longest > max_side:
        color = _limit_side(color, max_side)

    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    gray = _deskew_mild(gray)
    enhanced_gray, _binary = _enhance_nastaliq(gray)

    # Extra edge clarity for thin Nasta'liq ribbons.
    blur = cv2.GaussianBlur(enhanced_gray, (0, 0), 1.2)
    sharp = cv2.addWeighted(enhanced_gray, 1.35, blur, -0.35, 0)
    # Mild colorize back so vision models keep ink/paper cues.
    enhanced_bgr = cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR)
    # Blend a touch of original color luminance for natural look.
    color_resized = color
    if color_resized.shape[:2] != enhanced_bgr.shape[:2]:
        color_resized = cv2.resize(
            color,
            (enhanced_bgr.shape[1], enhanced_bgr.shape[0]),
            interpolation=cv2.INTER_CUBIC,
        )
    blended = cv2.addWeighted(enhanced_bgr, 0.72, color_resized, 0.28, 0)
    rgb = cv2.cvtColor(blended, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def prepare_image(image: Image.Image, max_side: int = 3200) -> PreprocessResult:
    color = _limit_side(_pil_to_bgr(image), max_side)
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    gray = _deskew_mild(gray)
    enhanced_gray, binary = _enhance_nastaliq(gray)

    enhanced_bgr = cv2.cvtColor(enhanced_gray, cv2.COLOR_GRAY2BGR)
    binary_bgr = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

    height, width = enhanced_bgr.shape[:2]
    if max(height, width) < 1400:
        scale = 1400 / float(max(height, width))
        size = (max(1, int(width * scale)), max(1, int(height * scale)))
        enhanced_bgr = cv2.resize(enhanced_bgr, size, interpolation=cv2.INTER_CUBIC)
        binary_bgr = cv2.resize(binary_bgr, size, interpolation=cv2.INTER_NEAREST)
        color = cv2.resize(color, size, interpolation=cv2.INTER_CUBIC)

    # Color / enhanced first — best for Nasta'liq connected letters.
    variants = [
        ("color", color),
        ("enhanced", enhanced_bgr),
        ("binary", binary_bgr),
    ]
    return PreprocessResult(
        color_bgr=color,
        enhanced_bgr=enhanced_bgr,
        binary_bgr=binary_bgr,
        variants=variants,
    )
