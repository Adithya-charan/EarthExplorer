"""Gridded (NetCDF) datasets: reading, regional means and per-cell frames.

Rules: nothing is interpolated or filled. Masked/fill cells stay missing (NaN). The regional series is an area-weighted
(cos latitude) mean over the valid cells only, labelled as such. Units come from the file; if the file has none the unit
is reported as unspecified rather than guessed. Grids larger than the display limit are block-averaged for the map only,
and the response says so.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.errors import unprocessable

MAX_VALUES = 50_000_000
MAX_DISPLAY_AXIS = 100
LAT_NAMES = {"lat", "latitude", "y", "nav_lat", "grid_latitude"}
LON_NAMES = {"lon", "longitude", "x", "nav_lon", "grid_longitude"}
TIME_NAMES = {"time", "date", "valid_time", "t"}


@dataclass
class GridData:
    variable: str
    unit: str | None
    long_name: str | None
    lat: np.ndarray  # ascending, degrees north
    lon: np.ndarray  # ascending, -180..180
    times: pd.DatetimeIndex
    values: np.ndarray  # (time, lat, lon) float32, NaN = missing
    source_name: str

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        dlat = float(np.median(np.diff(self.lat))) / 2 if len(self.lat) > 1 else 0.5
        dlon = float(np.median(np.diff(self.lon))) / 2 if len(self.lon) > 1 else 0.5
        return (float(self.lon[0] - dlon), float(self.lat[0] - dlat), float(self.lon[-1] + dlon), float(self.lat[-1] + dlat))


def _open(content: bytes):
    import xarray as xr

    errors = []
    for engine in ("h5netcdf", "scipy"):
        try:
            return xr.open_dataset(io.BytesIO(content), engine=engine, decode_times=True, mask_and_scale=True)
        except Exception as exc:  # noqa: BLE001 - try the next engine, then report one clear error
            errors.append(type(exc).__name__)
    raise unprocessable(
        "unreadable_grid_file",
        "The file could not be read as NetCDF (classic or NetCDF4/HDF5). GeoTIFF and other raster formats are not supported yet.",
    )


def _role(da, dim: str) -> str | None:
    n = dim.lower()
    attrs = da.coords[dim].attrs if dim in da.coords else {}
    units = str(attrs.get("units", "")).lower()
    axis = str(attrs.get("axis", "")).upper()
    if n in LAT_NAMES or units in ("degrees_north", "degree_north", "degrees_n") or axis == "Y" and n not in LON_NAMES:
        return "lat"
    if n in LON_NAMES or units in ("degrees_east", "degree_east", "degrees_e") or axis == "X":
        return "lon"
    if n in TIME_NAMES or axis == "T":
        return "time"
    return None


def read_netcdf(content: bytes, variable: str | None, source_name: str) -> GridData:
    ds = _open(content)
    try:
        candidates = []
        for name, da in ds.data_vars.items():
            roles = {_role(da, d) for d in da.dims}
            if {"lat", "lon", "time"} <= roles and da.ndim == 3:
                candidates.append(name)
        if not candidates:
            raise unprocessable(
                "no_gridded_variable",
                "No variable with time, latitude and longitude dimensions was found. Expected a 3-D variable such as precipitation(time, lat, lon).",
            )
        if variable is None:
            if len(candidates) > 1:
                raise unprocessable(
                    "ambiguous_variable",
                    "The file has several gridded variables; choose one: " + ", ".join(candidates) + ".",
                    )
            variable = candidates[0]
        elif variable not in candidates:
            raise unprocessable("variable_not_found", f"'{variable}' is not a gridded variable in this file. Choices: {', '.join(candidates)}.")
        da = ds[variable]
        roles = {_role(da, d): d for d in da.dims}
        da = da.transpose(roles["time"], roles["lat"], roles["lon"])
        lat = np.asarray(da[roles["lat"]].values, dtype=float)
        lon = np.asarray(da[roles["lon"]].values, dtype=float)
        if da.sizes[roles["time"]] < 1 or len(lat) < 1 or len(lon) < 1:
            raise unprocessable("empty_grid", "The grid has no cells or no time steps.")
        if int(np.prod(da.shape)) > MAX_VALUES:
            raise unprocessable("grid_too_large", f"The grid has {int(np.prod(da.shape)):,} values; the limit is {MAX_VALUES:,}.")
        try:
            times = pd.DatetimeIndex(pd.to_datetime(da[roles["time"]].values))
        except Exception as exc:  # noqa: BLE001
            raise unprocessable("unreadable_time", "The time coordinate could not be read as dates (use CF time units such as 'days since 2000-01-01').") from exc
        if times.isna().any():
            raise unprocessable("unreadable_time", "The time coordinate contains invalid dates.")
        if np.nanmin(lat) < -90 or np.nanmax(lat) > 90:
            raise unprocessable("invalid_latitude", "Latitude values fall outside -90..90 degrees.")
        vals = np.asarray(da.values, dtype=np.float32)
        vals[~np.isfinite(vals)] = np.nan
        if lon.max() > 180:
            lon = np.where(lon > 180, lon - 360, lon)
        li, oi, ti = np.argsort(lat), np.argsort(lon), np.argsort(times.values)
        vals = vals[ti][:, li][:, :, oi]
        unit = da.attrs.get("units")
        return GridData(
            variable=str(variable),
            unit=str(unit) if unit else None,
            long_name=str(da.attrs.get("long_name")) if da.attrs.get("long_name") else None,
            lat=lat[li],
            lon=lon[oi],
            times=times[ti],
            values=vals,
            source_name=source_name,
        )
    finally:
        ds.close()


def regional_mean_rows(g: GridData, region: str) -> pd.DataFrame:
    """Canonical long-format rows: cos-latitude weighted mean over valid cells for each time step."""
    w = np.cos(np.deg2rad(g.lat)).astype(np.float64)[None, :, None] * np.ones((1, 1, len(g.lon)))
    valid = np.isfinite(g.values)
    num = np.where(valid, g.values, 0.0) * w
    den = (valid * w).sum(axis=(1, 2))
    mean = np.where(den > 0, num.sum(axis=(1, 2)) / np.where(den > 0, den, 1), np.nan)
    unit = g.unit or "unspecified"
    note = "Area-weighted (cos latitude) mean over valid grid cells only; missing cells excluded, none filled."
    return pd.DataFrame(
        {
            "date": g.times,
            "region": region,
            "variable": g.variable,
            "value": mean,
            "unit": unit,
            "data_source": f"Uploaded NetCDF grid: {g.source_name} (declared by uploader, not verified)",
            "is_synthetic": False,
            "original_value": mean,
            "transformation_note": note,
        }
    )


def _block_mean(a: np.ndarray, fy: int, fx: int) -> np.ndarray:
    ny, nx = a.shape[0] // fy * fy, a.shape[1] // fx * fx
    b = a[:ny, :nx].reshape(ny // fy, fy, nx // fx, fx)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(b, axis=(1, 3))


def frame(g: GridData, when: pd.Timestamp) -> dict:
    """One time step as value and anomaly grids (anomaly = value minus that cell's mean for the same calendar month)."""
    idx = int(np.argmin(np.abs(g.times - when).values))
    if abs(g.times[idx] - when) > pd.Timedelta(days=16) and len(g.times) > 1:
        # Only accept the nearest step if it is the same month; otherwise the date is not in the grid.
        if (g.times[idx].year, g.times[idx].month) != (when.year, when.month):
            raise unprocessable("date_not_in_grid", f"The grid has no time step in {when:%B %Y}.")
    cur = g.values[idx]
    same = [i for i, t in enumerate(g.times) if t.month == g.times[idx].month]
    anomaly = None
    if len(same) >= 3:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            anomaly = cur - np.nanmean(g.values[same], axis=0)
    lat, lon = g.lat, g.lon
    fy, fx = -(-len(lat) // MAX_DISPLAY_AXIS), -(-len(lon) // MAX_DISPLAY_AXIS)
    note = None
    if fy > 1 or fx > 1:
        cur = _block_mean(cur, fy, fx)
        anomaly = _block_mean(anomaly, fy, fx) if anomaly is not None else None
        lat = lat[: len(lat) // fy * fy].reshape(-1, fy).mean(axis=1)
        lon = lon[: len(lon) // fx * fx].reshape(-1, fx).mean(axis=1)
        note = f"Grid block-averaged {fy}×{fx} for display only; the regional statistics use the full grid."

    def listify(a):
        return None if a is None else [[None if not np.isfinite(v) else float(v) for v in row] for row in a]

    finite = cur[np.isfinite(cur)]
    return {
        "date": g.times[idx].date(),
        "lat": [float(x) for x in lat],
        "lon": [float(x) for x in lon],
        "values": listify(cur),
        "anomaly": listify(anomaly),
        "value_min": float(finite.min()) if finite.size else None,
        "value_max": float(finite.max()) if finite.size else None,
        "anomaly_abs_max": float(np.nanmax(np.abs(anomaly))) if anomaly is not None and np.isfinite(anomaly).any() else None,
        "display_note": note,
    }
