"""Area weighting for regular latitude/longitude grids.

On a regular lat/lon grid, cell area shrinks toward the poles. For a cell bounded by latitudes phi1 < phi2 and a
fixed longitude width dlam, the exact spherical area is ``R^2 * dlam * (sin(phi2) - sin(phi1))``. Because dlam is the
same for every cell on a regular grid, the *relative* weight of a cell is ``sin(phi2) - sin(phi1)``. Using
``cos(phi_centre)`` is the common approximation; it differs by about ``(dphi^2)/24`` relative, which is far below
1e-4 for a 0.1 degree grid, but both are provided so the difference can be reported instead of assumed.

Missing cells are removed *and the weights renormalised over the valid cells*. That is a documented choice: the
result is the mean over the area that has data, and ``valid_area_fraction`` says how much of the area that was. It
is not a global mean when coverage is partial.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EARTH_RADIUS_KM = 6371.0088  # IUGG mean radius; only used to turn weights into km^2


def cos_lat_weights(lat: np.ndarray) -> np.ndarray:
    lat = np.asarray(lat, dtype="float64")
    if np.any(np.abs(lat) > 90):
        raise ValueError("latitude outside [-90, 90]")
    return np.cos(np.deg2rad(lat))


def exact_band_weights(lat_south: np.ndarray, lat_north: np.ndarray) -> np.ndarray:
    s = np.asarray(lat_south, dtype="float64")
    n = np.asarray(lat_north, dtype="float64")
    if np.any(np.abs(s) > 90) or np.any(np.abs(n) > 90) or np.any(n < s):
        raise ValueError("invalid latitude bounds")
    return np.sin(np.deg2rad(n)) - np.sin(np.deg2rad(s))


def centres_to_bounds(lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bounds of a regular, monotonic latitude axis, clipped to the poles (used only when bounds are not given)."""
    lat = np.asarray(lat, dtype="float64")
    if lat.size < 2:
        raise ValueError("need at least two latitudes")
    step = np.diff(lat)
    if not (np.allclose(step, step[0], rtol=0, atol=1e-6) and step[0] != 0):
        raise ValueError("latitude axis is not regular")
    half = abs(step[0]) / 2
    lo, hi = lat - half, lat + half
    lo, hi = np.minimum(lo, hi), np.maximum(lo, hi)
    return np.clip(lo, -90, 90), np.clip(hi, -90, 90)


def sphere_area_km2() -> float:
    return 4 * np.pi * EARTH_RADIUS_KM**2


@dataclass(frozen=True)
class WeightedMean:
    mean: float | None
    valid_area_fraction: float
    n_valid: int
    n_total: int
    scheme: str


def weighted_mean(values: np.ndarray, lat_weights: np.ndarray, scheme: str, lat_mask: np.ndarray | None = None) -> WeightedMean:
    """Area-weighted mean of a 2-D (lat, lon) field. NaN means "no data".

    ``lat_weights`` has one weight per latitude row. ``lat_mask`` (bool per row) restricts the average to a latitude
    range; ``valid_area_fraction`` is then relative to that range.
    """
    v = np.asarray(values, dtype="float64")
    if v.ndim != 2 or v.shape[0] != len(lat_weights):
        raise ValueError("values must be 2-D with one row per latitude weight")
    w_rows = np.asarray(lat_weights, dtype="float64")
    keep = np.ones(v.shape[0], dtype=bool) if lat_mask is None else np.asarray(lat_mask, dtype=bool)
    if not keep.any():
        raise ValueError("latitude mask selects no rows")
    sub = v[keep]
    w = np.broadcast_to(w_rows[keep][:, None], sub.shape)
    ok = np.isfinite(sub)
    total_w = float(w.sum())
    valid_w = float(w[ok].sum())
    if valid_w == 0:
        return WeightedMean(None, 0.0, 0, int(sub.size), scheme)
    return WeightedMean(float((sub[ok] * w[ok]).sum() / valid_w), valid_w / total_w, int(ok.sum()), int(sub.size), scheme)


def hours_in_month(year: int, month: int) -> int:
    import calendar

    return calendar.monthrange(year, month)[1] * 24
