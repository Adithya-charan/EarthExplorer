"""Elevation sampling from the same Terrarium tiles the map displays.

Terrarium tiles encode elevation in the red / green / blue channels of a 256×256 PNG:
``elevation_m = R * 256 + G + B / 256 - 32768``. The tiles are a mosaic of several source datasets
(SRTM, national DEMs, GMTED, ETOPO1 bathymetry, ...), so resolution varies by region, and a 256 px tile
sampled at one point is *not* a surveyed summit height. Responses say so.
"""

from __future__ import annotations

import io
import math
import threading
from typing import Any

import httpx
import numpy as np
from PIL import Image
from pydantic import BaseModel

from app.config import Settings
from app.geo import geometry as G
from app.geo.coords import validate_latlon
from app.geo.nominatim import TTLCache

TERRAIN_ATTRIBUTION = (
    "Terrain Tiles on AWS (Mapzen): SRTM, GMTED2010, NED, ETOPO1 and other sources — see https://registry.opendata.aws/terrain-tiles/"
)
TERRAIN_URL = "https://registry.opendata.aws/terrain-tiles/"
MAX_SAMPLE_ZOOM = 14


class ElevationResult(BaseModel):
    available: bool
    latitude: float
    longitude: float
    elevation_m: float | None = None
    zoom: int | None = None
    approx_resolution_m: float | None = None
    tile: dict[str, int] | None = None
    source: str
    attribution: str
    notes: list[str]


class TerrainService:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.url_template = settings.terrain_tile_url
        self.default_zoom = max(0, min(settings.terrain_sample_zoom, MAX_SAMPLE_ZOOM))
        self._client = httpx.Client(timeout=settings.geocoder_timeout_s, transport=transport, headers={"User-Agent": settings.geocoder_user_agent})
        self._tiles = TTLCache(2 * 3600, 64)
        self._lock = threading.Lock()

    def descriptor(self) -> dict[str, Any]:
        """How a map client can load the same elevation data."""
        return {
            "type": "raster-dem",
            "encoding": "terrarium",
            "tiles": [self.url_template],
            "tile_size": 256,
            "max_zoom": 15,
            "attribution": TERRAIN_ATTRIBUTION,
            "attribution_url": TERRAIN_URL,
            "notes": [
                "Mosaic of several elevation datasets; resolution and vertical accuracy vary by region.",
                "Values over the ocean are coarse bathymetry (negative elevations).",
            ],
        }

    def _tile(self, z: int, x: int, y: int) -> np.ndarray | None:
        key = (z, x, y)
        cached = self._tiles.get(key)
        if cached is not None:
            return cached
        url = self.url_template.format(z=z, x=x, y=y)
        try:
            r = self._client.get(url)
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        try:
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception:  # noqa: BLE001 - not an image: treat as unavailable
            return None
        arr = np.asarray(img, dtype=np.float64)
        if arr.shape[0] != 256 or arr.shape[1] != 256:
            return None
        elev = arr[:, :, 0] * 256.0 + arr[:, :, 1] + arr[:, :, 2] / 256.0 - 32768.0
        self._tiles.set(key, elev)
        return elev

    def elevation(self, lat: float, lon: float, zoom: int | None = None) -> ElevationResult:
        lat, lon = validate_latlon(lat, lon)
        z = self.default_zoom if zoom is None else max(0, min(int(zoom), MAX_SAMPLE_ZOOM))
        base_notes = [
            "Sampled from Terrarium elevation tiles with bilinear interpolation inside one tile.",
            "A sample is resolution-limited: summits and narrow valleys can be off by tens of metres or more. It is not a surveyed height.",
        ]
        if abs(lat) > G.MERCATOR_MAX_LAT:
            return ElevationResult(
                available=False,
                latitude=lat,
                longitude=lon,
                source="Terrarium tiles (Web Mercator)",
                attribution=TERRAIN_ATTRIBUTION,
                notes=[f"Terrarium tiles use Web Mercator and do not cover latitudes beyond ±{G.MERCATOR_MAX_LAT:.2f}°, so no elevation is available here."],
            )
        x, y, fx, fy = G.tile_xy(lat, lon, z)
        tile = self._tile(z, x, y)
        if tile is None:
            return ElevationResult(
                available=False,
                latitude=lat,
                longitude=lon,
                zoom=z,
                tile={"z": z, "x": x, "y": y},
                source="Terrarium tiles (Web Mercator)",
                attribution=TERRAIN_ATTRIBUTION,
                notes=["The elevation tile could not be loaded, so no value is shown."],
            )
        px, py = fx * 256.0 - 0.5, fy * 256.0 - 0.5
        x0, y0 = int(math.floor(px)), int(math.floor(py))
        wx, wy = px - x0, py - y0
        xs = [min(255, max(0, x0)), min(255, max(0, x0 + 1))]
        ys = [min(255, max(0, y0)), min(255, max(0, y0 + 1))]
        v = (
            tile[ys[0], xs[0]] * (1 - wx) * (1 - wy)
            + tile[ys[0], xs[1]] * wx * (1 - wy)
            + tile[ys[1], xs[0]] * (1 - wx) * wy
            + tile[ys[1], xs[1]] * wx * wy
        )
        notes = list(base_notes)
        if v < 0:
            notes.append("Negative values are depths below sea level (coarse bathymetry).")
        return ElevationResult(
            available=True,
            latitude=lat,
            longitude=lon,
            elevation_m=round(float(v), 1),
            zoom=z,
            approx_resolution_m=round(156543.03392 * math.cos(math.radians(lat)) / (2**z), 1),
            tile={"z": z, "x": x, "y": y},
            source="Terrarium tiles (Web Mercator)",
            attribution=TERRAIN_ATTRIBUTION,
            notes=notes,
        )

    def close(self) -> None:
        self._client.close()
