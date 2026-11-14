"""Small deterministic fixtures shared by the tests."""

from __future__ import annotations

import io

import numpy as np
import pandas as pd

from app.schemas import QualityReport
from app.services.store import CANONICAL_COLUMNS, DatasetRecord, DatasetStore


def monthly_dates(start_year: int = 2000, n: int = 120) -> pd.DatetimeIndex:
    return pd.date_range(f"{start_year}-01-01", periods=n, freq="MS")


def canonical_df(
    values,
    dates=None,
    *,
    region: str = "R1",
    variable: str = "V1",
    unit: str = "u",
    is_synthetic: bool = False,
    data_source: str = "test fixture",
) -> pd.DataFrame:
    values = np.asarray(values, dtype="float64")
    dates = monthly_dates(n=len(values)) if dates is None else pd.DatetimeIndex(dates)
    df = pd.DataFrame(
        {
            "date": dates,
            "region": region,
            "variable": variable,
            "value": values,
            "unit": unit,
            "data_source": data_source,
            "is_synthetic": is_synthetic,
        }
    )
    return df


def make_record(df: pd.DataFrame, *, status: str = "uploaded", name: str = "fixture") -> DatasetRecord:
    df = DatasetStore._finalize(df, "fixture-id", name)
    return DatasetRecord(
        id="fixture-id", name=name, status=status, data=df, quality=None, source_file="fixture.csv"  # type: ignore[arg-type]
    )


def csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def frame_to_csv(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


__all__ = ["canonical_df", "make_record", "monthly_dates", "csv_bytes", "frame_to_csv", "CANONICAL_COLUMNS", "QualityReport"]
