#!/usr/bin/env python3
"""Download Bina 0.2 Rizeh (or a public PP-OCRv6 bootstrap) into models/bina-0.2."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "models" / "bina-0.2"
BINA_REPO = "Reza2kn/Bina-0.2-Roryh"
DET_REPO = "PaddlePaddle/PP-OCRv6_medium_det"
REC_REPO = "PaddlePaddle/PP-OCRv6_medium_rec"


def _download(repo_id: str, local_dir: Path, *, token: str | None, allow_patterns: list[str] | None = None) -> None:
    from huggingface_hub import snapshot_download

    local_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(local_dir),
        token=token,
        allow_patterns=allow_patterns,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Bina 0.2 model files")
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_DIR,
        help="Target directory (default: back/models/bina-0.2)",
    )
    parser.add_argument(
        "--bootstrap-only",
        action="store_true",
        help="Skip gated Bina repo; install public detector + medium recognizer only",
    )
    args = parser.parse_args()
    target: Path = args.dir
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")

    print(f"Target: {target}")
    target.mkdir(parents=True, exist_ok=True)

    if not args.bootstrap_only and token:
        try:
            print(f"Downloading full Bina release from {BINA_REPO} ...")
            _download(BINA_REPO, target, token=token)
            bootstrap = target / "inference" / ".bina_bootstrap"
            if bootstrap.exists():
                bootstrap.unlink()
            print("Bina 0.2 Rizeh installed.")
            return 0
        except Exception as exc:
            print(f"Bina repo download failed ({exc}); falling back to public bootstrap.", file=sys.stderr)

    print(f"Installing public detector ({DET_REPO}) ...")
    _download(
        DET_REPO,
        target / "detector",
        token=token,
        allow_patterns=["inference.*", "*.yml", "*.json", "*.pdiparams", "*.pdmodel"],
    )
    print(f"Installing public recognizer bootstrap ({REC_REPO}) ...")
    inference = target / "inference"
    if inference.exists():
        shutil.rmtree(inference)
    _download(
        REC_REPO,
        inference,
        token=token,
        allow_patterns=["inference.*", "*.yml", "*.json", "*.pdiparams", "*.pdmodel", "*.txt"],
    )
    (inference / ".bina_bootstrap").write_text(
        f"Placeholder recognizer: {REC_REPO}\n"
        f"Set HF_TOKEN and re-run to install {BINA_REPO}.\n",
        encoding="utf-8",
    )
    (target / "README.md").write_text(
        "# Bina 0.2 model directory\n\n"
        f"Detector: `{DET_REPO}` (same family as the Bina release).\n"
        f"Recognizer: bootstrap `{REC_REPO}` until `{BINA_REPO}` is downloaded with `HF_TOKEN`.\n",
        encoding="utf-8",
    )
    print("Bootstrap install complete. Set HF_TOKEN and re-run for the real Bina fine-tune.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
