"""Where NASA files are stored. The root comes from ``EARTHTREND_NASA_DATA_DIR`` and must not be on the system drive."""

from __future__ import annotations

import os
from pathlib import Path

from app.errors import AppError

ENV_DATA_DIR = "EARTHTREND_NASA_DATA_DIR"
ENV_ALLOW_SYSTEM_DRIVE = "EARTHTREND_NASA_ALLOW_SYSTEM_DRIVE"


def _same_drive(a: Path, b: Path) -> bool:
    return bool(a.drive) and a.drive.lower() == b.drive.lower()


def resolve_data_dir(value: str | os.PathLike[str] | None = None) -> Path:
    """Return the NASA data root, or raise a clear error. Never falls back to a default on the system drive."""
    raw = value if value is not None else os.environ.get(ENV_DATA_DIR)
    if not raw:
        raise AppError(503, "nasa_data_dir_unset", f"Set the {ENV_DATA_DIR} environment variable to the folder for NASA files (for example D:\\nasa_data).")
    root = Path(raw).expanduser()
    system = Path(os.environ.get("SystemDrive", "C:") + "\\")
    if _same_drive(root, system) and os.environ.get(ENV_ALLOW_SYSTEM_DRIVE) != "1":
        raise AppError(
            422,
            "nasa_data_dir_on_system_drive",
            f"{root} is on the system drive ({system.drive}). Choose another drive; raw NASA archives are large.",
        )
    return root


class DataLayout:
    """On-disk layout: raw files are kept apart from everything derived from them."""

    def __init__(self, root: Path):
        self.root = root
        self.raw = root / "raw"
        self.processed = root / "processed"
        self.manifests = root / "manifests"
        self.reports = root / "reports"
        self.logs = root / "logs"

    def ensure(self) -> "DataLayout":
        for p in (self.raw, self.processed, self.manifests, self.reports, self.logs):
            p.mkdir(parents=True, exist_ok=True)
        return self

    def raw_path(self, short_name: str, version: str, year: int, filename: str) -> Path:
        return self.raw / f"{short_name}.{version}" / f"{year:04d}" / filename

    def manifest_path(self, short_name: str, version: str) -> Path:
        return self.manifests / f"{short_name}.{version}.json"
