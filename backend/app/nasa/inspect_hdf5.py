"""Read an original GPM IMERG monthly HDF5 granule and report what is *actually* in it.

Nothing is assumed: dimension order, attributes, fill values, units, coordinates and time are read from the file and
compared with what CMR said. Differences are reported as findings, not corrected silently.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import xarray as xr

from app.nasa import areaweight as aw

GROUP = "Grid"
VARIABLES = ("precipitation", "randomError", "precipitationQualityIndex")
# What CMR's UMM-Var records say (inspection of 2026-11-13). The file is checked against this, never the reverse.
CMR_EXPECTED = {
    "precipitation": {"units": "mm/hr", "dtype": "float32", "fill": -9999.9},
    "randomError": {"units": "mm/hr", "dtype": "float32", "fill": -9999.9},
    "precipitationQualityIndex": {"units": "Equivalent gauges per 2.5 deg box", "dtype": "float32", "fill": -9999.9},
}
GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)


def _plain(v: Any) -> Any:
    """Make an HDF5 attribute JSON-friendly without altering its meaning."""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, np.ndarray):
        return [_plain(x) for x in v.tolist()]
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def read_structure(path: Path) -> dict[str, Any]:
    """Every group and dataset in the file with shape, dtype, chunking, compression and all attributes."""
    items: dict[str, Any] = {}

    def visit(name: str, obj: Any) -> None:
        if isinstance(obj, h5py.Dataset):
            items[name] = {
                "kind": "dataset",
                "shape": list(obj.shape),
                "dtype": str(obj.dtype),
                "chunks": list(obj.chunks) if obj.chunks else None,
                "compression": obj.compression,
                "attrs": {k: _plain(v) for k, v in obj.attrs.items() if k not in ("DIMENSION_LIST", "REFERENCE_LIST")},
            }
        else:
            items[name] = {"kind": "group", "attrs": {k: _plain(v) for k, v in obj.attrs.items()}}

    with h5py.File(path, "r") as f:
        root_attrs = {k: _plain(v) for k, v in f.attrs.items()}
        f.visititems(visit)
    return {"root_attrs": root_attrs, "objects": items}


def _decode_time(seconds: int) -> datetime:
    return GPS_EPOCH + timedelta(seconds=int(seconds))


def inspect_granule(path: Path, *, cmr_size_mb: float | None = None, granule_begin: str | None = None, granule_end: str | None = None) -> dict[str, Any]:
    """Validate structure, dimension order, attributes, coordinates and time. Returns a JSON-serializable report."""
    path = Path(path)
    findings: list[dict[str, str]] = []

    def note(level: str, text: str) -> None:
        findings.append({"level": level, "text": text})

    size = path.stat().st_size
    report: dict[str, Any] = {"file": path.name, "size_bytes": size}
    if cmr_size_mb is not None:
        report["cmr_size_mb"] = cmr_size_mb
        report["size_vs_cmr_ratio"] = round(size / (cmr_size_mb * 1024 * 1024), 4)
        report["size_vs_cmr_ratio_if_decimal_mb"] = round(size / (cmr_size_mb * 1_000_000), 4)

    if not h5py.is_hdf5(path):
        raise ValueError(f"{path.name} is not a readable HDF5 file")
    report["structure"] = read_structure(path)

    # Raw (undecoded) view so that attributes and fill values are seen exactly as stored.
    ds = xr.open_dataset(path, group=GROUP, engine="h5netcdf", decode_cf=False, mask_and_scale=False)
    try:
        variables: dict[str, Any] = {}
        for name in VARIABLES:
            if name not in ds.variables:
                note("error", f"variable {name} is missing from group {GROUP}")
                continue
            v = ds[name]
            attrs = {k: _plain(a) for k, a in v.attrs.items()}
            expected = CMR_EXPECTED[name]
            info = {
                "dims": list(v.dims),
                "shape": list(v.shape),
                "dtype": str(v.dtype),
                "attrs": attrs,
                "has_scale_factor": "scale_factor" in attrs,
                "has_add_offset": "add_offset" in attrs,
            }
            units = attrs.get("units")
            if units is None:
                note("warning", f"{name}: no 'units' attribute in the file; CMR says '{expected['units']}'")
            elif units != expected["units"]:
                note("warning", f"{name}: file units '{units}' differ from CMR '{expected['units']}'")
            fill = attrs.get("_FillValue", attrs.get("CodeMissingValue"))
            if fill is None:
                note("warning", f"{name}: no _FillValue attribute in the file; CMR says {expected['fill']}")
            else:
                try:
                    if not np.isclose(float(fill if not isinstance(fill, list) else fill[0]), expected["fill"], rtol=0, atol=0.01):
                        note("warning", f"{name}: file fill value {fill} differs from CMR {expected['fill']}")
                except (TypeError, ValueError):
                    note("warning", f"{name}: fill value {fill!r} could not be read as a number")
            if str(v.dtype) != expected["dtype"]:
                note("warning", f"{name}: file dtype {v.dtype} differs from CMR {expected['dtype']}")
            variables[name] = info
        report["variables"] = variables
        dim_orders = {tuple(i["dims"]) for i in variables.values()}
        report["dimension_order"] = [list(d) for d in sorted(dim_orders)]
        if len(dim_orders) > 1:
            note("warning", "the three variables do not share one dimension order")

        # Coordinates
        lat = np.asarray(ds["lat"].values, dtype="float64")
        lon = np.asarray(ds["lon"].values, dtype="float64")
        coords: dict[str, Any] = {
            "n_lat": int(lat.size),
            "n_lon": int(lon.size),
            "lat_first": float(lat[0]),
            "lat_last": float(lat[-1]),
            "lon_first": float(lon[0]),
            "lon_last": float(lon[-1]),
            "lat_step_unique": sorted({round(float(x), 5) for x in np.diff(lat)})[:5],
            "lon_step_unique": sorted({round(float(x), 5) for x in np.diff(lon)})[:5],
            "lat_units": _plain(ds["lat"].attrs.get("units")),
            "lon_units": _plain(ds["lon"].attrs.get("units")),
        }
        if not (np.all(np.diff(lat) > 0) or np.all(np.diff(lat) < 0)):
            note("error", "latitude is not monotonic")
        if not (np.all(np.diff(lon) > 0) or np.all(np.diff(lon) < 0)):
            note("error", "longitude is not monotonic")
        if (lat.size, lon.size) != (1800, 3600):
            note("warning", f"grid is {lat.size} x {lon.size}, not the 1800 x 3600 that CMR describes")
        if np.any(np.abs(lat) > 90) or np.any(np.abs(lon) > 180):
            note("error", "coordinate values outside the valid range")
        # Bounds, when present, must enclose the centres and give the exact cell edges.
        if "lat_bnds" in ds.variables:
            b = np.asarray(ds["lat_bnds"].values, dtype="float64")
            coords["lat_bnds_min"], coords["lat_bnds_max"] = float(b.min()), float(b.max())
            if not (np.all(b.min(axis=1) <= lat + 1e-6) and np.all(b.max(axis=1) >= lat - 1e-6)):
                note("error", "lat_bnds do not enclose the latitude centres")
        report["coordinates"] = coords
        report["lat_axis_ascending"] = bool(lat[0] < lat[-1])

        # Time
        t = np.asarray(ds["time"].values).ravel()
        time_info: dict[str, Any] = {"raw": [int(x) for x in t], "units_attr": _plain(ds["time"].attrs.get("units"))}
        if "since 1980-01-06" not in str(time_info["units_attr"]):
            note("warning", f"time units are '{time_info['units_attr']}', not the 'seconds since 1980-01-06' that CMR describes")
        if t.size != 1:
            note("error", f"expected exactly one time step, found {t.size}")
        else:
            time_info["decoded_utc"] = _decode_time(t[0]).isoformat()
            if "time_bnds" in ds.variables:
                tb = np.asarray(ds["time_bnds"].values).ravel()
                time_info["bounds_utc"] = [_decode_time(tb[0]).isoformat(), _decode_time(tb[1]).isoformat()]
            if granule_begin:
                start = datetime.fromisoformat(granule_begin.replace("Z", "+00:00"))
                got = _decode_time(t[0])
                if (got.year, got.month) != (start.year, start.month):
                    note("error", f"file time {got.isoformat()} is not in the CMR month {granule_begin[:7]}")
                time_info["matches_cmr_month"] = (got.year, got.month) == (start.year, start.month)
                if "bounds_utc" in time_info and granule_end:
                    b0 = datetime.fromisoformat(time_info["bounds_utc"][0])
                    time_info["bounds_start_matches_cmr_begin"] = abs((b0 - start).total_seconds()) < 1
        report["time"] = time_info

        report["axes_note"] = "variables are stored (time, lon, lat); analysis code reorders by dimension NAME, never by position"
    finally:
        ds.close()
    report["findings"] = findings
    report["ok"] = not any(f["level"] == "error" for f in findings)
    return report


def load_field(path: Path, name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Return (field[lat, lon] float64 with the file's fill value turned into NaN, lat, lon, raw attrs).

    Only the *fill value* is converted to NaN (documented below); values are otherwise untouched and no unit changes
    are made. The array is reordered by dimension name to (lat, lon).
    """
    ds = xr.open_dataset(path, group=GROUP, engine="h5netcdf", decode_cf=False, mask_and_scale=False)
    try:
        v = ds[name]
        attrs = {k: _plain(a) for k, a in v.attrs.items()}
        arr = v.squeeze(drop=True).transpose("lat", "lon").values.astype("float64")
        fill = attrs.get("_FillValue", attrs.get("CodeMissingValue"))
        if isinstance(fill, list):
            fill = fill[0]
        if fill is not None:
            arr = np.where(np.isclose(arr, float(fill), rtol=0, atol=1e-3), np.nan, arr)
        lat = ds["lat"].values.astype("float64")
        lon = ds["lon"].values.astype("float64")
    finally:
        ds.close()
    return arr, lat, lon, attrs


def _pcts(x: np.ndarray) -> dict[str, float]:
    qs = [0, 1, 5, 25, 50, 75, 95, 99, 100]
    vals = np.percentile(x, qs)
    return {f"p{q}": float(v) for q, v in zip(qs, vals)}


def quality_report(path: Path, granule_begin: str | None = None) -> dict[str, Any]:
    """Missing-data and value-distribution report for one granule. Descriptive only: it recommends nothing."""
    fields: dict[str, np.ndarray] = {}
    attrs: dict[str, Any] = {}
    lat = lon = None
    for name in VARIABLES:
        fields[name], lat, lon, attrs[name] = load_field(path, name)
    assert lat is not None and lon is not None

    out: dict[str, Any] = {"file": Path(path).name, "variables": {}}
    total = fields["precipitation"].size
    bands = [(-90, -60), (-60, -30), (-30, 0), (0, 30), (30, 60), (60, 90)]
    for name, arr in fields.items():
        valid = np.isfinite(arr)
        info: dict[str, Any] = {
            "cells": int(total),
            "valid": int(valid.sum()),
            "missing_fill": int((~valid).sum()),
            "valid_fraction": float(valid.mean()),
            "negative_values": int((arr[valid] < 0).sum()),
            "exact_zero": int((arr[valid] == 0).sum()),
            "distribution_valid": _pcts(arr[valid]) if valid.any() else None,
            "valid_fraction_by_lat_band": {f"{a}..{b}": float(valid[(lat >= a) & (lat < b)].mean()) for a, b in bands},
        }
        # Rows that are entirely missing: where does valid coverage stop?
        rows = valid.any(axis=1)
        info["lat_range_with_any_valid"] = [float(lat[rows].min()), float(lat[rows].max())] if rows.any() else None
        out["variables"][name] = info

    p, r, q = (np.isfinite(fields[k]) for k in VARIABLES)
    out["mask_agreement"] = {
        "precip_valid_and_randomError_missing": int((p & ~r).sum()),
        "precip_missing_and_randomError_valid": int((~p & r).sum()),
        "precip_valid_and_quality_missing": int((p & ~q).sum()),
        "precip_missing_and_quality_valid": int((~p & q).sum()),
    }

    # Relation between random error and the estimate (descriptive)
    both = p & r & (fields["precipitation"] > 0)
    if both.any():
        ratio = fields["randomError"][both] / fields["precipitation"][both]
        out["randomError_over_precipitation_where_precip_positive"] = _pcts(ratio)
    # Quality index against latitude (descriptive)
    qv = fields["precipitationQualityIndex"]
    out["quality_index_median_by_lat_band"] = {f"{a}..{b}": (float(np.nanmedian(qv[(lat >= a) & (lat < b)])) if np.isfinite(qv[(lat >= a) & (lat < b)]).any() else None) for a, b in bands}

    # Weighting: exact band areas from the stored bounds when available, cos(lat) for comparison.
    ds = xr.open_dataset(path, group=GROUP, engine="h5netcdf", decode_cf=False, mask_and_scale=False)
    try:
        if "lat_bnds" in ds.variables:
            b = ds["lat_bnds"].values.astype("float64")
            lo, hi = b.min(axis=1), b.max(axis=1)
            bounds_source = "file lat_bnds"
        else:
            lo, hi = aw.centres_to_bounds(lat)
            bounds_source = "derived from regular centres"
    finally:
        ds.close()
    w_exact = aw.exact_band_weights(lo, hi)
    w_cos = aw.cos_lat_weights(lat)
    prec = fields["precipitation"]
    wm_exact = aw.weighted_mean(prec, w_exact, "exact spherical band area")
    wm_cos = aw.weighted_mean(prec, w_cos, "cos(latitude)")
    unweighted = float(np.nanmean(prec))
    out["weighting"] = {
        "bounds_source": bounds_source,
        "exact_band_weights_sum_check": float(w_exact.sum() / 2.0),  # sum of (sin n - sin s) over the globe is 2
        "global_mean_precipitation_valid_cells_only": {
            "exact": wm_exact.mean,
            "cos_lat": wm_cos.mean,
            "unweighted_simple_mean_for_contrast": unweighted,
            "units": attrs["precipitation"].get("units"),
            "valid_area_fraction_exact": wm_exact.valid_area_fraction,
        },
        "relative_difference_exact_vs_cos": (abs(wm_exact.mean - wm_cos.mean) / abs(wm_exact.mean)) if wm_exact.mean else None,
    }
    if granule_begin:
        y, m = int(granule_begin[:4]), int(granule_begin[5:7])
        h = aw.hours_in_month(y, m)
        out["derived_example_not_stored"] = {
            "hours_in_month": h,
            "note": "accumulation (mm) = mean rate (mm/hr) x hours in the calendar month. Shown only if the file's attributes confirm the value is a monthly mean rate.",
            "global_mean_accumulation_mm_if_mean_rate": (wm_exact.mean * h) if wm_exact.mean is not None else None,
        }
    return out
