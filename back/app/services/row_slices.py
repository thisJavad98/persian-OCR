"""Slice an enhanced page image into per-row bands for export."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image


def _ink_row_bands(gray: np.ndarray, count: int) -> List[Tuple[int, int]]:
    """Find horizontal bands using ink density; fall back to equal slices."""
    height, width = gray.shape[:2]
    if count <= 0:
        return [(0, height)]
    if count == 1:
        return [(0, height)]

    # Dark ink on light paper → invert so ink is high.
    norm = gray.astype(np.float32)
    ink = 255.0 - norm
    # Soft threshold against paper.
    ink = np.clip(ink - np.percentile(ink, 40), 0, None)
    projection = ink.mean(axis=1)
    if float(projection.max()) < 1e-3:
        return _equal_bands(height, count)

    # Smooth projection.
    kernel = max(3, height // (count * 8) | 1)
    projection = cv2.GaussianBlur(projection.reshape(-1, 1), (1, kernel), 0).ravel()
    threshold = max(float(np.mean(projection)) * 0.55, float(np.percentile(projection, 55)) * 0.35)

    active = projection >= threshold
    # Ensure edges don't eat content.
    segments: List[Tuple[int, int]] = []
    start = None
    for idx, flag in enumerate(active):
        if flag and start is None:
            start = idx
        elif not flag and start is not None:
            if idx - start >= max(8, height // (count * 12)):
                segments.append((start, idx))
            start = None
    if start is not None and height - start >= max(8, height // (count * 12)):
        segments.append((start, height))

    if len(segments) < max(1, count // 2):
        return _equal_bands(height, count)

    # Merge / split toward requested count.
    bands = list(segments)
    while len(bands) > count:
        # Merge the two closest/smallest adjacent gaps.
        merge_at = min(
            range(len(bands) - 1),
            key=lambda i: (bands[i + 1][0] - bands[i][1]) + (bands[i][1] - bands[i][0]) * 0.01,
        )
        left = bands[merge_at]
        right = bands[merge_at + 1]
        bands[merge_at] = (left[0], right[1])
        del bands[merge_at + 1]

    while len(bands) < count:
        # Split tallest band.
        tallest = max(range(len(bands)), key=lambda i: bands[i][1] - bands[i][0])
        top, bottom = bands[tallest]
        mid = (top + bottom) // 2
        bands[tallest : tallest + 1] = [(top, mid), (mid, bottom)]

    # Add small vertical padding / overlap so strokes are not clipped.
    pad = max(4, height // (count * 20))
    padded: List[Tuple[int, int]] = []
    for top, bottom in bands:
        padded.append((max(0, top - pad), min(height, bottom + pad)))
    return padded[:count]


def _equal_bands(height: int, count: int) -> List[Tuple[int, int]]:
    bands: List[Tuple[int, int]] = []
    overlap = max(4, height // (count * 18)) if count else 0
    for index in range(count):
        top = int(round(index * height / count))
        bottom = int(round((index + 1) * height / count))
        top = max(0, top - (overlap if index else 0))
        bottom = min(height, bottom + (overlap if index < count - 1 else 0))
        if bottom <= top:
            bottom = min(height, top + max(1, height // count))
        bands.append((top, bottom))
    return bands


def build_row_slices(
    image: Image.Image,
    row_count: int,
    output_dir: Path,
    *,
    labels: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    """
    Save one horizontal slice PNG per exported row.
    Returns metadata including absolute path and relative filename.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    rgb = image.convert("RGB")
    array = np.array(rgb)
    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape[:2]
    count = max(1, int(row_count or 1))
    bands = _ink_row_bands(gray, count)

    slices: List[Dict[str, Any]] = []
    for index, (top, bottom) in enumerate(bands, start=1):
        crop = rgb.crop((0, top, width, bottom))
        filename = f"row-{index:03d}.png"
        path = output_dir / filename
        crop.save(path, format="PNG", optimize=True)
        label = labels[index - 1] if index - 1 < len(labels) else ""
        slices.append(
            {
                "row_index": index,
                "filename": filename,
                "path": str(path),
                "top": top,
                "bottom": bottom,
                "label": label,
                "width": width,
                "height": bottom - top,
            }
        )
    return slices
