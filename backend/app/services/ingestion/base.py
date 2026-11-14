"""Adapter interface for dataset formats.

An adapter turns one *source format* into the canonical long-format table
(``date, region, variable, value, unit, data_source, is_synthetic`` + optional
metadata). Only a CSV adapter exists today. NetCDF / HDF / GeoTIFF adapters will
be written after the real dataset has been inspected - see
``docs/NASA_DATA_INTEGRATION.md``.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import PurePath

import pandas as pd

from app.schemas import ColumnMapping, QualityReport, SourceInspection, SourceProfile


@dataclass(frozen=True)
class DataSource:
    """An in-memory source file. ``filename`` is metadata only - it is never used as a path."""

    filename: str
    content: bytes


@dataclass
class LoadResult:
    """Result of mapping a source to the canonical schema.

    ``data`` is ``None`` when blocking problems prevent building a table; the
    ``report`` then explains why.
    """

    data: pd.DataFrame | None
    report: QualityReport
    notes: list[str]


_SAFE = re.compile(r"[^A-Za-z0-9._()\- ]+")


def safe_filename(name: str | None, default: str = "upload.csv") -> str:
    """Return a display-safe file name (no directories, no control characters)."""
    base = PurePath((name or "").replace("\\", "/")).name
    base = _SAFE.sub("_", base).strip(" .")
    return (base[:120] or default)


class DatasetAdapter(ABC):
    """Contract every format adapter implements."""

    format_name: str = "unknown"

    @abstractmethod
    def inspect(self, source: DataSource) -> SourceInspection:
        """Cheap structural look: columns, row count, encoding, preview rows."""

    @abstractmethod
    def profile(self, source: DataSource) -> SourceProfile:
        """Inspection plus per-column profiling and a *proposed* (unconfirmed) mapping."""

    @abstractmethod
    def load(self, source: DataSource, mapping: ColumnMapping) -> LoadResult:
        """Apply a user-confirmed mapping and return canonical data plus a quality report."""

    @abstractmethod
    def validate(self, data: pd.DataFrame) -> list:
        """Dataset-level checks on canonical data; returns a list of ``QualityIssue``."""
