"""Rebuild a visual table grid from OCR bounding boxes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from app.services.ocr_engine import LineResult


@dataclass
class TableCell:
    text: str
    confidence: float
    row: int
    col: int


@dataclass
class TableGrid:
    rows: List[List[str]]
    cells: List[TableCell]
    row_count: int
    col_count: int

    def as_dict(self) -> dict:
        return {
            "rows": self.rows,
            "row_count": self.row_count,
            "col_count": self.col_count,
            "cells": [
                {
                    "text": cell.text,
                    "confidence": cell.confidence,
                    "row": cell.row,
                    "col": cell.col,
                }
                for cell in self.cells
            ],
        }


def _box_center(box: Sequence[Sequence[float]]) -> Tuple[float, float, float, float]:
    xs = [float(point[0]) for point in box]
    ys = [float(point[1]) for point in box]
    return (
        sum(xs) / len(xs),
        sum(ys) / len(ys),
        max(xs) - min(xs) or 1.0,
        max(ys) - min(ys) or 1.0,
    )


def _cluster_1d(values: List[Tuple[float, float, int]], gap_ratio: float) -> List[List[int]]:
    """Cluster items by center with adaptive gap from median size."""
    if not values:
        return []
    ordered = sorted(values, key=lambda item: item[0])
    sizes = sorted(size for _, size, _ in ordered)
    median_size = sizes[len(sizes) // 2] if sizes else 1.0
    threshold = max(median_size * gap_ratio, 8.0)

    clusters: List[List[Tuple[float, float, int]]] = [[ordered[0]]]
    for item in ordered[1:]:
        current = clusters[-1]
        mean_center = sum(part[0] for part in current) / len(current)
        mean_size = sum(part[1] for part in current) / len(current)
        if abs(item[0] - mean_center) <= max(threshold, 0.55 * max(item[1], mean_size)):
            current.append(item)
        else:
            clusters.append([item])
    return [[index for _, _, index in cluster] for cluster in clusters]


def build_table(lines: List[LineResult]) -> TableGrid:
    """Map OCR fragments into a row/column grid that mirrors the image table."""
    usable: List[Tuple[LineResult, float, float, float, float]] = []
    for line in lines:
        if not line.text.strip():
            continue
        if line.box and len(line.box) >= 2:
            x, y, w, h = _box_center(line.box)
        else:
            # Fallback: stack as a single column.
            x, y, w, h = 0.0, float(len(usable)), 1.0, 1.0
        usable.append((line, x, y, w, h))

    if not usable:
        return TableGrid(rows=[], cells=[], row_count=0, col_count=0)

    row_input = [(y, h, index) for index, (_, _, y, _, h) in enumerate(usable)]
    row_clusters = _cluster_1d(row_input, gap_ratio=0.7)

    # Estimate columns from all cells, then refine with RTL order (right = col 0).
    col_input = [(x, w, index) for index, (_, x, _, w, _) in enumerate(usable)]
    raw_col_clusters = _cluster_1d(col_input, gap_ratio=0.55)
    # Sort column clusters by descending X so the right-most image column is first.
    col_clusters = sorted(
        raw_col_clusters,
        key=lambda cluster: sum(usable[i][1] for i in cluster) / len(cluster),
        reverse=True,
    )

    index_to_row = {}
    for row_idx, cluster in enumerate(row_clusters):
        for item_index in cluster:
            index_to_row[item_index] = row_idx

    index_to_col = {}
    for col_idx, cluster in enumerate(col_clusters):
        for item_index in cluster:
            index_to_col[item_index] = col_idx

    row_count = len(row_clusters)
    col_count = max(len(col_clusters), 1)
    grid: List[List[List[Tuple[float, str, float]]]] = [
        [[] for _ in range(col_count)] for _ in range(row_count)
    ]

    cells: List[TableCell] = []
    for index, (line, x, _, _, _) in enumerate(usable):
        row = index_to_row.get(index, 0)
        col = index_to_col.get(index, 0)
        grid[row][col].append((x, line.text.strip(), line.confidence))
        cells.append(
            TableCell(text=line.text.strip(), confidence=line.confidence, row=row, col=col)
        )

    rows: List[List[str]] = []
    for row in grid:
        rendered: List[str] = []
        for cell_parts in row:
            if not cell_parts:
                rendered.append("")
                continue
            # Inside a cell, keep right-to-left visual order.
            cell_parts.sort(key=lambda item: item[0], reverse=True)
            rendered.append(" ".join(part[1] for part in cell_parts).strip())
        rows.append(rendered)

    # Collapse obvious single-column docs that were over-split into many empty cols.
    if col_count > 1:
        nonempty_cols = [
            col
            for col in range(col_count)
            if any(rows[row][col].strip() for row in range(row_count))
        ]
        if len(nonempty_cols) == 1:
            only = nonempty_cols[0]
            rows = [[rows[row][only]] for row in range(row_count)]
            col_count = 1
            cells = [
                TableCell(text=cell.text, confidence=cell.confidence, row=cell.row, col=0)
                for cell in cells
            ]

    return TableGrid(rows=rows, cells=cells, row_count=row_count, col_count=col_count)


def table_from_payload(payload: Optional[dict]) -> Optional[TableGrid]:
    if not payload:
        return None
    rows = payload.get("rows") or []
    cells_raw = payload.get("cells") or []
    cells = [
        TableCell(
            text=str(item.get("text", "")),
            confidence=float(item.get("confidence", 0)),
            row=int(item.get("row", 0)),
            col=int(item.get("col", 0)),
        )
        for item in cells_raw
    ]
    return TableGrid(
        rows=rows,
        cells=cells,
        row_count=int(payload.get("row_count", len(rows))),
        col_count=int(payload.get("col_count", len(rows[0]) if rows else 0)),
    )
