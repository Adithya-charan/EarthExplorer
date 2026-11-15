"""GeospatialRenderingService: PNG / GeoTIFF layers for the globe, cached so repeat requests are cheap."""

from __future__ import annotations

import io
import threading
from collections import OrderedDict

import numpy as np
import rasterio
from PIL import Image
from rasterio.io import MemoryFile

from app.explorer.datasets import Dataset

# difference codes (also written into the difference GeoTIFF)
D_UNCERTAIN, D_LAND, D_WATER, D_LOSS, D_GAIN = 0, 1, 2, 3, 4
DIFF_COLORS = {
    D_LAND: (122, 128, 140, 120),    # grey: unchanged land
    D_WATER: (56, 139, 253, 190),    # blue: unchanged water
    D_LOSS: (230, 57, 70, 235),      # red: water lost
    D_GAIN: (46, 204, 113, 235),     # green: water gained
}
OBS_COLORS = {
    1: (168, 150, 120, 215), 2: (50, 140, 255, 230), 3: (74, 140, 80, 215), 4: (214, 118, 80, 225), 5: (240, 246, 255, 235), 6: (150, 214, 236, 240), 7: (196, 178, 120, 225),
    8: (24, 110, 70, 230), 9: (214, 196, 96, 215), 10: (120, 200, 90, 230), 11: (96, 168, 150, 220),
}
HATCH = (205, 215, 232, 120)
UPSCALE = 2


def _hatch(shape: tuple[int, int]) -> np.ndarray:
    r, c = np.indices(shape)
    return ((r + c) % 6) < 2


def _png(rgba: np.ndarray) -> bytes:
    img = Image.fromarray(rgba, "RGBA")
    if UPSCALE > 1:
        img = img.resize((img.width * UPSCALE, img.height * UPSCALE), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False)
    return buf.getvalue()


def observation_rgba(arr: np.ndarray, uncertain: int) -> np.ndarray:
    out = np.zeros((*arr.shape, 4), dtype=np.uint8)
    for code, rgba in OBS_COLORS.items():
        out[arr == code] = rgba
    unc = arr == uncertain
    out[unc & _hatch(arr.shape)] = HATCH
    return out


def difference_rgba(diff: np.ndarray) -> np.ndarray:
    out = np.zeros((*diff.shape, 4), dtype=np.uint8)
    for code, rgba in DIFF_COLORS.items():
        out[diff == code] = rgba
    out[(diff == D_UNCERTAIN) & _hatch(diff.shape)] = HATCH
    return out


def composite_rgba(water: np.ndarray, ok: np.ndarray) -> np.ndarray:
    out = np.zeros((*water.shape, 4), dtype=np.uint8)
    out[ok & ~water] = (122, 128, 140, 110)
    out[ok & water] = DIFF_COLORS[D_WATER]
    out[~ok & _hatch(water.shape)] = HATCH
    return out


def difference_geotiff(ds: Dataset, diff: np.ndarray, tags: dict[str, str]) -> bytes:
    profile = dict(driver="GTiff", height=diff.shape[0], width=diff.shape[1], count=1, dtype="uint8", crs=ds.crs, transform=ds.transform, nodata=255, compress="DEFLATE")
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(diff.astype(np.uint8), 1)
            dst.update_tags(**tags)
        return mem.read()


class LayerCache:
    """Small thread-safe LRU of rendered bytes."""

    def __init__(self, size: int = 400):
        self._d: OrderedDict[tuple, bytes] = OrderedDict()
        self._size = size
        self._lock = threading.Lock()

    def get_or_make(self, key: tuple, make) -> bytes:
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
        data = make()
        with self._lock:
            self._d[key] = data
            while len(self._d) > self._size:
                self._d.popitem(last=False)
        return data


class RenderingService:
    def __init__(self):
        self.cache = LayerCache()

    def observation_png(self, ds: Dataset, iso: str, arr: np.ndarray) -> bytes:
        return self.cache.get_or_make(("obs", ds.id, iso), lambda: _png(observation_rgba(arr, ds.uncertain)))

    def difference_png(self, analysis_id: str, diff: np.ndarray) -> bytes:
        return self.cache.get_or_make(("diff", analysis_id), lambda: _png(difference_rgba(diff)))

    def composite_png(self, analysis_id: str, which: str, water: np.ndarray, ok: np.ndarray) -> bytes:
        return self.cache.get_or_make(("comp", analysis_id, which), lambda: _png(composite_rgba(water, ok)))
