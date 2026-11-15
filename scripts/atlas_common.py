"""Shared paths and helpers for the India Historical Atlas dataset pipeline."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "datasets" / "india_historical_atlas"
BACKEND = ROOT / "backend"
REGIONS = ["himalayas", "sundarbans", "hyderabad", "bengaluru"]
DOC = ATLAS / "documentation"

# Region footprints (west, south, east, north) in EPSG:4326. These are analysis windows chosen by hand, not administrative units.
REGION_BBOX = {
    "himalayas": (79.60, 30.55, 80.05, 30.95),     # Dhauliganga catchment, Uttarakhand (upper part)
    "sundarbans": (88.60, 21.55, 89.10, 22.05),    # Indian Sundarbans, West Bengal
    "hyderabad": (78.25, 17.25, 78.65, 17.60),     # Hyderabad metropolitan core
    "bengaluru": (77.62, 12.90, 77.72, 12.99),     # Bellandur Lake and surroundings
}


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def read_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
