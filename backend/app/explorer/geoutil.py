"""Area and geometry helpers. Areas are never computed from raw degree sizes.

Geographic rasters get a per-row ellipsoidal pixel area (WGS84 geodesic polygon area); projected rasters use the pixel
size converted from the CRS's linear unit to metres. Polygon areas use a local UTM CRS.
"""

from __future__ import annotations

import math

import numpy as np
from pyproj import CRS, Geod
from rasterio.transform import Affine

_GEOD = Geod(ellps="WGS84")


def pixel_area_m2_per_row(transform: Affine, height: int, crs: CRS | None) -> np.ndarray:
    """Area of one pixel (square metres) for every raster row, as a float64 vector of length ``height``."""
    if crs is None:
        raise ValueError("The raster has no CRS, so areas cannot be measured.")
    crs = CRS.from_user_input(crs.to_wkt() if hasattr(crs, "to_wkt") else crs)  # accept rasterio or pyproj CRS objects
    if crs.is_geographic:
        out = np.empty(height, dtype=np.float64)
        w = abs(transform.a)
        for r in range(height):
            lat_top = transform.f + r * transform.e
            lat_bot = lat_top + transform.e
            lon0 = transform.c
            lon1 = lon0 + w
            area, _ = _GEOD.polygon_area_perimeter([lon0, lon1, lon1, lon0], [lat_top, lat_top, lat_bot, lat_bot])
            out[r] = abs(area)
        return out
    factor = crs.axis_info[0].unit_conversion_factor if crs.axis_info else 1.0
    return np.full(height, abs(transform.a * transform.e) * factor * factor, dtype=np.float64)


def area_ha(mask: np.ndarray, row_area_m2: np.ndarray) -> float:
    """Hectares covered by the True cells of ``mask`` (rows weighted by their own pixel area)."""
    return float((mask.sum(axis=1) * row_area_m2).sum() / 10_000.0)


def compass(dx: float, dy: float) -> str:
    """Compass word for a displacement (east = +dx, north = +dy)."""
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return "central"
    ang = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
    names = ["eastern", "north-eastern", "northern", "north-western", "western", "south-western", "southern", "south-eastern"]
    return names[int(((ang + 22.5) % 360) // 45)]


def bbox_of(transform: Affine, width: int, height: int) -> tuple[float, float, float, float]:
    """(west, south, east, north) of a north-up raster."""
    west, north = transform.c, transform.f
    east = west + width * transform.a
    south = north + height * transform.e
    return (min(west, east), min(south, north), max(west, east), max(south, north))
