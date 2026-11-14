"""Maps file extensions to adapters. Only CSV is implemented."""

from __future__ import annotations

from pathlib import PurePath

from app.errors import AppError

from .base import DatasetAdapter
from .csv_adapter import CSVAdapter

# NetCDF / HDF5 / GeoTIFF are deliberately NOT registered: those adapters will be
# written after the real dataset has been inspected (docs/NASA_DATA_INTEGRATION.md).
ADAPTERS: dict[str, type[DatasetAdapter]] = {".csv": CSVAdapter}

SUPPORTED_EXTENSIONS = tuple(ADAPTERS)


def adapter_for(filename: str) -> DatasetAdapter:
    ext = PurePath(filename or "").suffix.lower()
    if ext in ADAPTERS:
        return ADAPTERS[ext]()
    shown = ext or "files without an extension"
    raise AppError(
        415,
        "unsupported_format",
        f"{shown} is not supported. Currently only CSV (.csv) can be imported. "
        "NetCDF, HDF and GeoTIFF adapters are not implemented yet; they will be added after the real dataset is inspected.",
    )
