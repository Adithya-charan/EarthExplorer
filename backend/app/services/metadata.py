"""Dataset metadata and observation access, derived only from the loaded data."""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import pandas as pd

from app.errors import unprocessable
from app.schemas import (
    MetadataResponse,
    ObservationsResponse,
    RegionSummary,
    SeriesSummary,
    SpatialInfo,
    VariableSummary,
)
from app.services.ingestion.schema import OPTIONAL_FIELDS, csv_safe
from app.services.provenance import build_provenance
from app.services.stats.sampling import detect_sampling
from app.services.store import DatasetRecord, DatasetStore

TEXT_COLUMNS = (
    "region",
    "variable",
    "unit",
    "data_source",
    "dataset_id",
    "dataset_name",
    "mission",
    "instrument",
    "product",
    "quality_flag",
    "spatial_geometry",
    "spatial_resolution",
    "temporal_resolution",
    "original_variable",
    "original_unit",
    "source_file",
    "transformation_note",
)


def _d(ts) -> Any:
    return None if pd.isna(ts) else ts.date()


def spatial_info(df: pd.DataFrame) -> SpatialInfo:
    if "latitude" in df.columns and "longitude" in df.columns:
        pts = df[["latitude", "longitude"]].dropna()
        if len(pts):
            return SpatialInfo(
                available=True,
                n_points_with_coordinates=int(len(pts)),
                latitude_range=(float(pts["latitude"].min()), float(pts["latitude"].max())),
                longitude_range=(float(pts["longitude"].min()), float(pts["longitude"].max())),
                note=(
                    "Coordinates come from the dataset's latitude/longitude columns. The app does not know whether they describe "
                    "point observations, grid-cell centres or regional centroids, and it applies no spatial aggregation."
                ),
            )
    return SpatialInfo(
        available=False,
        note=(
            "This dataset has no latitude/longitude columns, so no map can be drawn. Region names are not converted to "
            "coordinates or boundaries, and no spatial pattern is implied."
        ),
    )


def build_metadata(store: DatasetStore, record: DatasetRecord) -> MetadataResponse:
    df = record.data
    series: list[SeriesSummary] = []
    for (variable, region), g in df.groupby(["variable", "region"], sort=True):
        valid = g["value"].notna()
        series.append(
            SeriesSummary(
                variable=variable,
                region=region,
                units=sorted(g["unit"].dropna().unique().tolist()),
                n_rows=len(g),
                n_valid=int(valid.sum()),
                n_missing=int((~valid).sum()),
                start=_d(g["date"].min()),
                end=_d(g["date"].max()),
                sampling=detect_sampling(g["date"]).label,
                data_sources=sorted(g["data_source"].dropna().unique().tolist()),
                is_synthetic=bool(g["is_synthetic"].any()),
            )
        )
    variables = []
    for name, g in df.groupby("variable", sort=True):
        variables.append(
            VariableSummary(
                name=name,
                units=sorted(g["unit"].dropna().unique().tolist()),
                regions=sorted(g["region"].unique().tolist()),
                n_rows=len(g),
                n_valid=int(g["value"].notna().sum()),
                start=_d(g["date"].min()),
                end=_d(g["date"].max()),
                original_names=(
                    sorted(g["original_variable"].dropna().unique().tolist()) if "original_variable" in g.columns else []
                ),
            )
        )
    regions = [
        RegionSummary(
            name=name,
            variables=sorted(g["variable"].unique().tolist()),
            n_rows=len(g),
            start=_d(g["date"].min()),
            end=_d(g["date"].max()),
        )
        for name, g in df.groupby("region", sort=True)
    ]
    present = [c for c in OPTIONAL_FIELDS if c in df.columns]
    return MetadataResponse(
        provenance=build_provenance(record),
        dataset=store.summarize(record),
        variables=variables,
        regions=regions,
        series=series,
        optional_fields_present=present,
        spatial=spatial_info(df),
        quality=record.quality,
    )


def filter_observations(
    df: pd.DataFrame,
    variable: str | None,
    region: str | None,
    start,
    end,
    include_missing: bool,
) -> pd.DataFrame:
    if start is not None and end is not None and start > end:
        raise unprocessable("invalid_date_range", "The start date must not be after the end date.")
    mask = pd.Series(True, index=df.index)
    if variable:
        mask &= df["variable"] == variable
    if region:
        mask &= df["region"] == region
    if start is not None:
        mask &= df["date"] >= pd.Timestamp(start)
    if end is not None:
        mask &= df["date"] < pd.Timestamp(end) + pd.Timedelta(days=1)
    if not include_missing:
        mask &= df["value"].notna()
    return df[mask]


def _row_dicts(df: pd.DataFrame) -> list[dict[str, Any]]:
    out = df.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out = out.astype(object).where(pd.notna(out), None)
    rows = out.to_dict("records")
    for r in rows:
        r["is_synthetic"] = bool(r["is_synthetic"])
        for k, v in r.items():
            if isinstance(v, (np.floating, float)) and v is not None and not np.isfinite(v):
                r[k] = None
    return rows


def page_observations(
    record: DatasetRecord, df: pd.DataFrame, limit: int, offset: int
) -> ObservationsResponse:
    page = df.iloc[offset : offset + limit]
    return ObservationsResponse(
        provenance=build_provenance(record, df),
        total=len(df),
        limit=limit,
        offset=offset,
        columns=list(df.columns),
        rows=_row_dicts(page),
    )


def observations_csv(record: DatasetRecord, df: pd.DataFrame) -> str:
    """CSV export that always carries data_source and is_synthetic, with formula-injection protection."""
    out = df.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    for col in TEXT_COLUMNS:
        if col in out.columns:
            out[col] = out[col].map(csv_safe)
    buf = io.StringIO()
    prov = build_provenance(record, df)
    buf.write(f"# EarthTrend Explorer export | dataset: {csv_safe(record.name)} | status: {record.status} | is_synthetic: {str(prov.is_synthetic).lower()} | dataset_sha256: {prov.dataset_checksum} | generated_at: {prov.generated_at}\n")
    if prov.notice:
        buf.write(f"# {prov.notice}\n")
    out.to_csv(buf, index=False)
    return buf.getvalue()
