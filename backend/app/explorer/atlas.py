"""Generator for the four-region ILLUSTRATIVE historical layers of the India Historical Atlas.

Everything written here is generated, not observed. Each dataset.json carries ``is_synthetic: true``, ``designation:
"illustrative"`` and the public label "Illustrative Dataset"; the real origin stays in the metadata, never in a satellite
label. The regions are:

    himalayas   Dhauliganga catchment (Uttarakhand): glacier, snow, glacial lake, exposed terrain. A FIXED elevation model is
                used for every year, because no elevation time series supports a change in terrain.
    sundarbans  Indian Sundarbans (West Bengal): mangrove, water, mudflat, other land; spatially varying erosion and accretion.
    hyderabad   Hyderabad metropolitan area: built-up, vegetation, agriculture, water; growth around settlements and corridors.
    bengaluru   Bellandur Lake and surroundings: open water, aquatic vegetation, wetland fringe, built-up, vegetation.

Per region the generator writes (``out`` = datasets/india_historical_atlas):

    synthetic/<region>/clean_truth/<year>.tif   the noise-free class rasters (the generator's own truth)
    synthetic/<region>/generator_config.json    seeds, parameters, the rules that produce the changes
    processed/synthetic/<region>/dataset.json   metadata for the app (class legend, variables, observation index, provenance)
    processed/synthetic/<region>/observations/  the degraded rasters the app reads (COG, EPSG:4326, uint8, nodata 255)
    processed/synthetic/<region>/ground_truth.json   true first-to-last-year areas per variable, from the clean rasters

Class codes: 1 other land / exposed terrain, 2 water, 3 vegetation, 4 built-up, 5 snow, 6 glacier ice, 7 mudflat, 8 mangrove,
9 agriculture, 10 aquatic vegetation, 11 wetland fringe, 255 uncertain / no data.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.transform import from_origin
from scipy import ndimage as ndi
from shapely.geometry import mapping, shape

from app.explorer.geoutil import area_ha, pixel_area_m2_per_row

UNC = 255
CLASS_NAMES = {
    "1": "Other land / exposed terrain", "2": "Water", "3": "Vegetation", "4": "Built-up", "5": "Snow", "6": "Glacier ice", "7": "Mudflat",
    "8": "Mangrove", "9": "Agriculture", "10": "Aquatic vegetation", "11": "Wetland fringe", "255": "Uncertain or no data",
}
PUBLIC_LABEL = "Illustrative Dataset"
PUBLIC_NOTE = "Illustrative Dataset: a generated demonstration layer, not satellite imagery."
SCHEMA_VERSION = 2


# ----------------------------------------------------------------------------------------------- spec
@dataclass
class Variable:
    key: str
    label: str
    cls: int | list[int]
    primary: bool = False


@dataclass
class Region:
    id: str
    folder: str
    name: str
    aliases: list[str]
    bbox: tuple[float, float, float, float]  # west, south, east, north
    res_deg: float
    years: list[int]
    month: int
    variables: list[Variable]
    seed: int
    place_hint: str
    description: str
    centre: tuple[float, float]  # lat, lon
    sensor_note: str
    cloud: dict[int, float] = field(default_factory=dict)  # year -> cloud fraction (an explicit, documented choice)
    rules: list[str] = field(default_factory=list)


def smooth(shape_: tuple[int, int], sigma: float, rng: np.random.Generator) -> np.ndarray:
    f = ndi.gaussian_filter(rng.standard_normal(shape_), sigma, mode="reflect")
    return (f - f.mean()) / (f.std() + 1e-12)


class Grid:
    def __init__(self, bbox: tuple[float, float, float, float], res: float):
        self.west, self.south, self.east, self.north = bbox
        self.res = res
        self.w = int(round((self.east - self.west) / res))
        self.h = int(round((self.north - self.south) / res))
        self.transform = from_origin(self.west, self.north, res, res)
        lat0 = (self.south + self.north) / 2
        self.mx = 111_320.0 * math.cos(math.radians(lat0))
        self.my = 110_574.0
        cols, rows = np.arange(self.w) + 0.5, np.arange(self.h) + 0.5
        self.lon = self.west + cols * res
        self.lat = self.north - rows * res
        self.x = np.tile(((self.lon - self.west) * self.mx)[None, :], (self.h, 1))  # metres east of the west edge
        self.y = np.tile(((self.lat - self.south) * self.my)[:, None], (1, self.w))  # metres north of the south edge
        self.shape = (self.h, self.w)

    def xy_of(self, lon: float, lat: float) -> tuple[float, float]:
        return (lon - self.west) * self.mx, (lat - self.south) * self.my


# ------------------------------------------------------------------------------------- scene builders
# Each scene object exposes classify(year) -> clean uint8 raster, and optional extras (terrain, zones).
class HimalayaScene:
    TERMINUS_M = [4650.0, 4900.0, 4550.0, 5000.0]   # elevation of the ice tongue end in 2001, per glacier basin
    RETREAT_M_PER_YR = [9.0, 4.5, 13.0, 2.0]          # upward shift of that end per year (spatially varying on purpose)
    FIRST = 2001

    def __init__(self, reg: Region):
        g = self.g = Grid(reg.bbox, reg.res_deg)
        rng = np.random.default_rng(reg.seed)
        t = g.y / g.y.max()
        n1, n2, n3 = smooth(g.shape, 30, rng), smooth(g.shape, 9, rng), smooth(g.shape, 3, rng)
        ridged = 1.0 - np.abs(n1)
        z = 2300.0 + 3300.0 * t**1.1 + 700.0 * ridged + 90.0 * n2
        axes = [(0.22, 0.10), (0.42, -0.05), (0.62, 0.06), (0.82, -0.08)]  # (x fraction at mid-height, lean)
        W = g.x.max()
        self.basin = np.zeros(g.shape, dtype=np.int8)
        best = np.full(g.shape, np.inf)
        for i, (xf, lean) in enumerate(axes):
            ax = xf * W + lean * W * (t - 0.5) + 900.0 * np.sin(6.0 * t + i)
            d = np.abs(g.x - ax)
            z -= 650.0 * np.exp(-((d / 1100.0) ** 2)) * (0.35 + 0.65 * (1.0 - t))
            upd = d < best
            self.basin[upd], best[upd] = i, d[upd]
        self.z = (z + 25.0 * n3).astype(np.float32)
        self.valley = (ndi.gaussian_filter(self.z, 18) - self.z) > 18.0
        self.rng_seed = reg.seed
        self.n_edge = smooth(g.shape, 5, np.random.default_rng(reg.seed + 1))
        self.meadow = smooth(g.shape, 14, np.random.default_rng(reg.seed + 2))
        self.snow_anom = {y: float(np.random.default_rng(reg.seed * 100 + y).normal(0, 140.0)) for y in reg.years}
        self.terminus_t = None

    def _ice(self, year: int) -> np.ndarray:
        ys = year - self.FIRST
        ice = np.zeros(self.g.shape, dtype=bool)
        for b in range(4):
            tb = self.TERMINUS_M[b] + self.RETREAT_M_PER_YR[b] * ys + 55.0 * self.n_edge
            ice |= (self.basin == b) & self.valley & (self.z > tb)
        ice |= self.z > 5800.0
        return ndi.binary_opening(ice, iterations=1)

    def classify(self, year: int) -> np.ndarray:
        z = self.z
        ice = self._ice(year)
        ice0 = self._ice(self.FIRST)
        cls = np.full(self.g.shape, 1, dtype=np.uint8)
        cls[(z < 3700.0) | ((z < 4300.0) & (self.meadow > 0.3))] = 3
        snow = (z > 5150.0 + self.snow_anom.get(year, 0.0)) & ~ice
        cls[snow] = 5
        cls[ice] = 6
        ys = year - self.FIRST
        if ys >= 9:  # a proglacial lake fills the lowest part of the area vacated by glacier basin 2
            vac = (self.basin == 2) & ice0 & ~ice & self.valley
            if vac.any():
                zmin = float(z[vac].min())
                span = float(np.ptp(z[vac]))
                lake = vac & (z < zmin + span * min(0.3, 0.012 * (ys - 8)))
                cls[lake] = 2
        return cls


class SundarbansScene:
    K = 0.03  # shoreline sensitivity (field units per year at |rate| = 1)

    def __init__(self, reg: Region):
        g = self.g = Grid(reg.bbox, reg.res_deg)
        rng = np.random.default_rng(reg.seed)
        n = lambda s: smooth(g.shape, s, rng)  # noqa: E731
        h = 0.9 * n(38) + 0.45 * n(11)
        W, H = g.x.max(), g.y.max()
        for xf, amp in ((0.18, 0.0), (0.45, 1.0), (0.72, 2.0)):  # three large tidal rivers running north to south
            axis = xf * W + 2600.0 * np.sin(5.0 * g.y / H + amp * 2.1)
            h -= 3.0 * np.exp(-(((g.x - axis) / 850.0) ** 2))
        creeks = np.abs(n(7)) < 0.075
        h -= 2.2 * creeks
        south = np.clip(1.0 - g.y / H, 0, 1)
        h = h - 0.9 * south**3  # the seaward edge is lower
        self.h0 = h.astype(np.float32)
        self.rate = (0.85 * n(55) - 0.45 * south).astype(np.float32)  # erosion (<0) is more likely on the exposed south
        self.fertile = n(16)
        self.embank = n(20)

    def field(self, year: int) -> np.ndarray:
        ys = year - 2000
        w = np.exp(-((self.h0 / 0.55) ** 2))
        return self.h0 + self.K * ys * self.rate * w

    def classify(self, year: int) -> np.ndarray:
        h = self.field(year)
        land = h > 0
        cls = np.full(self.g.shape, 2, dtype=np.uint8)
        mud = (h <= 0) & (h > -0.14)
        cls[mud] = 7
        cls[land] = 1
        cls[land & (h > 0.06) & (self.fertile > -0.7) & ~(self.embank > 0.9)] = 8
        return cls


class CityScene:
    """Hyderabad: built-up grows from fixed nuclei and corridors; water bodies are nearly stable."""

    NUCLEI = [  # (lon, lat, sigma_m, weight): approximate positions of the old city and the growth centres
        (78.4747, 17.3616, 5200, 1.00), (78.4867, 17.4400, 5200, 0.9), (78.3489, 17.4401, 4200, 0.85), (78.5600, 17.4000, 4300, 0.8),
        (78.4000, 17.4900, 3900, 0.7), (78.2700, 17.5300, 3800, 0.55), (78.4300, 17.2650, 3500, 0.5), (78.5200, 17.4800, 3400, 0.55),
    ]
    CORRIDORS = [  # polylines (lon, lat): outer ring road and the radial highways, approximate
        [(78.28, 17.42), (78.30, 17.33), (78.40, 17.27), (78.52, 17.30), (78.60, 17.38), (78.60, 17.48), (78.52, 17.56), (78.38, 17.56), (78.29, 17.50), (78.28, 17.42)],
        [(78.4867, 17.4400), (78.47, 17.60)], [(78.3489, 17.4401), (78.25, 17.52)], [(78.5600, 17.4000), (78.65, 17.36)], [(78.4747, 17.3616), (78.43, 17.25)],
    ]
    WATER = [(78.4738, 17.4239, 1000, 800, 20), (78.3004, 17.3858, 2600, 1300, 30), (78.3900, 17.3200, 2700, 1100, 60), (78.3925, 17.4325, 450, 380, 0), (78.5300, 17.4600, 520, 400, 10)]

    def __init__(self, reg: Region):
        g = self.g = Grid(reg.bbox, reg.res_deg)
        rng = np.random.default_rng(reg.seed)
        pot = np.zeros(g.shape)
        for lon, lat, sg, wt in self.NUCLEI:
            x0, y0 = g.xy_of(lon, lat)
            pot = np.maximum(pot, wt * np.exp(-((g.x - x0) ** 2 + (g.y - y0) ** 2) / (2 * sg**2)))
        cor = np.full(g.shape, np.inf)
        for line in self.CORRIDORS:
            pts = [g.xy_of(*p) for p in line]
            for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
                dx, dy = xb - xa, yb - ya
                L2 = dx * dx + dy * dy
                u = np.clip(((g.x - xa) * dx + (g.y - ya) * dy) / L2, 0, 1)
                cor = np.minimum(cor, np.hypot(g.x - (xa + u * dx), g.y - (ya + u * dy)))
        self.pot = np.clip(pot + 0.38 * np.exp(-((cor / 1300.0) ** 2)) * (0.35 + 0.65 * np.clip(pot * 2.2, 0, 1)), 0, 1.2) + 0.10 * smooth(g.shape, 9, rng)
        self.veg = smooth(g.shape, 16, rng)
        self.agri = smooth(g.shape, 22, rng)
        water = np.zeros(g.shape, dtype=bool)
        wob = smooth(g.shape, 12, rng)
        for lon, lat, a, b, rot in self.WATER:
            x0, y0 = g.xy_of(lon, lat)
            r = math.radians(rot)
            xr = (g.x - x0) * math.cos(r) + (g.y - y0) * math.sin(r)
            yr = -(g.x - x0) * math.sin(r) + (g.y - y0) * math.cos(r)
            water |= np.sqrt((xr / a) ** 2 + (yr / b) ** 2) * (1 + 0.12 * wob) < 1.0
        self.water0 = water
        self.water_n = smooth(g.shape, 5, rng)
        self.anom = {y: float(np.random.default_rng(reg.seed * 77 + y).normal(0, 0.015)) for y in range(1990, 2040)}

    def threshold(self, year: int) -> float:
        return 0.553 - 0.207 * ((year - 2000) / 24.0) ** 1.15  # falls as the city grows; never rises, so built-up never shrinks

    def classify(self, year: int) -> np.ndarray:
        built = self.pot > self.threshold(year)
        water = self.water0 & ~(built & (self.pot > 0.78) & (year >= 2010))  # tanks inside the densest fabric lose their edges
        water &= ~((self.water_n > 1.1 + 0.4 * self.anom[year] * 40) & ~self.water0)
        agri = (self.pot < 0.62) & (self.agri > 0.0)
        veg = (self.veg > 0.55) | ((self.pot > 0.4) & (self.veg > 0.25) & (self.pot < 0.8))
        cls = np.full(self.g.shape, 1, dtype=np.uint8)
        cls[agri] = 9
        cls[veg & ~agri] = 3
        cls[built] = 4
        cls[water] = 2
        return cls


class LakeScene:
    """Bellandur Lake: a stable lake outline; changes inside (open water -> aquatic vegetation) are kept apart from the surroundings."""

    A_M, B_M, ROT = 1500.0, 780.0, 70.0

    def __init__(self, reg: Region):
        g = self.g = Grid(reg.bbox, reg.res_deg)
        rng = np.random.default_rng(reg.seed)
        x0, y0 = g.xy_of(reg.centre[1], reg.centre[0])
        r = math.radians(self.ROT)
        xr = (g.x - x0) * math.cos(r) + (g.y - y0) * math.sin(r)
        yr = -(g.x - x0) * math.sin(r) + (g.y - y0) * math.cos(r)
        wob = smooth(g.shape, 10, rng)
        rr = np.sqrt((xr / self.A_M) ** 2 + (yr / self.B_M) ** 2) * (1 + 0.10 * wob)
        self.depth = 1.0 - rr
        self.zone = rr < 1.18  # the lake basin at its full outline plus a thin margin
        ang = (np.degrees(np.arctan2(g.y - y0, g.x - x0)) + 360.0) % 360.0
        self.enc = (ang > 290) | (ang < 20)  # sector of the shore that is gradually built over (south-east side)
        self.sched = np.clip(0.5 * smooth(g.shape, 5, rng) * 0.4 + 0.5, 0, 1)
        self.av_noise = smooth(g.shape, 7, rng)
        self.shallow = np.clip(1.0 - np.abs(self.depth) / 0.45, 0, 1)
        self.urban = smooth(g.shape, 26, rng)
        self.veg = smooth(g.shape, 12, rng)
        # surroundings: built-up grows along an east-west corridor and around village nuclei
        cx = lambda lon: g.xy_of(lon, reg.centre[0])[0]  # noqa: E731
        _, yc = g.xy_of(reg.centre[1], reg.centre[0] + 0.012)
        corridor = np.exp(-(((g.y - yc) / 900.0) ** 2))
        nuclei = np.zeros(g.shape)
        for lon, lat, sg, wt in ((77.6770, 12.9360, 900, 0.9), (77.6940, 12.9230, 1100, 0.95), (77.6500, 12.9150, 1000, 0.8), (77.7000, 12.9560, 900, 0.8), (77.6420, 12.9520, 1100, 0.7)):
            xs, ys = g.xy_of(lon, lat)
            nuclei = np.maximum(nuclei, wt * np.exp(-((g.x - xs) ** 2 + (g.y - ys) ** 2) / (2 * sg**2)))
        self.pot = np.clip(nuclei + 0.45 * corridor + 0.12 * self.urban, 0, 1.3)
        self.anom = {y: float(np.random.default_rng(reg.seed * 31 + y).normal(0, 0.012)) for y in range(1995, 2035)}
        self._first = min(reg.years)
        self._span = max(reg.years) - min(reg.years)

    def threshold(self, year: int) -> float:
        return 0.287 - 0.183 * ((year - self._first) / max(1, self._span)) ** 1.05

    def classify(self, year: int) -> np.ndarray:
        f = (year - self._first) / max(1, self._span)
        thr = 0.015 + self.anom[year]
        water = self.depth > thr
        enc_done = self.enc & (self.depth > -0.05) & (f * 0.09 > (1.0 - self.sched) * 0.09 + 0.001) & (self.depth < 0.12)
        built = (self.pot > self.threshold(year)) & ~self.zone
        water &= ~enc_done
        av = water & (self.shallow > 0.0) & (self.av_noise * (0.6 + 0.4 * self.shallow) > 1.5 - 1.25 * f)
        fringe = ~water & (self.depth > -0.14) & (self.depth <= thr) & ~built & ~enc_done & (self.av_noise < 0.9 - 0.4 * f)
        veg = (self.veg > 0.15) & ~built
        cls = np.full(self.g.shape, 1, dtype=np.uint8)
        cls[veg] = 3
        cls[fringe] = 11
        cls[built | enc_done] = 4
        cls[water] = 2
        cls[av] = 10
        return cls

    def zone_mask(self) -> np.ndarray:
        return self.zone


# --------------------------------------------------------------------------------------------- regions
def regions() -> list[Region]:
    return [
        Region(
            "himalayas-dhauliganga", "himalayas", "Dhauliganga catchment, Uttarakhand", ["himalayas", "the himalayas", "dhauliganga", "dhauliganga catchment", "dhauliganga valley", "himalaya"],
            (79.60, 30.55, 80.05, 30.95), 0.0006, [2001, 2005, 2010, 2015, 2020], 9,
            [Variable("glacier", "glacier ice", 6, True), Variable("snow", "snow cover", 5), Variable("glacial_lake", "glacial lake", 2), Variable("exposed_terrain", "exposed terrain", 1)],
            101, "Chamoli district, Uttarakhand, India",
            "Illustrative glacier retreat, snow, glacial-lake growth and exposed terrain over a fixed, generated elevation model.",
            (30.75, 79.825), "Late-season (September) illustrative scenes", {2005: 0.07, 2015: 0.03},
            ["Glacier tongues end at elevations that rise at a different rate for each of four basins (2.0 to 13.0 m per year).", "Snow cover follows a snowline that varies randomly from year to year, with no trend.", "A proglacial lake grows in the area vacated by one glacier after 2009.", "Terrain elevation is identical in every year."],
        ),
        Region(
            "sundarbans-west-bengal", "sundarbans", "Sundarbans, West Bengal", ["sundarbans", "the sundarbans", "sunderbans", "sundarban", "indian sundarbans", "sundarbans west bengal"],
            (88.60, 21.55, 89.10, 22.05), 0.0004, [2000, 2005, 2010, 2015, 2020], 1,
            [Variable("mangrove", "mangrove", 8, True), Variable("water", "open water", 2), Variable("mudflat", "mudflat", 7), Variable("land", "land (including mangrove)", [1, 8])],
            202, "South 24 Parganas, West Bengal, India",
            "Illustrative coastal change: spatially varying erosion and accretion, mudflat belts and mangrove cover around tidal rivers and islands.",
            (21.80, 88.85), "Dry-season (January) illustrative scenes", {2010: 0.04},
            ["Shorelines move with a smooth random field: some stretches erode, others accrete, and the exposed south erodes more often.", "Mudflat is the intertidal band next to land; mangrove needs land above a minimum height, so new land becomes mangrove only after it has emerged.", "Embanked interior is non-mangrove land."],
        ),
        Region(
            "hyderabad-metro", "hyderabad", "Hyderabad metropolitan area", ["hyderabad", "hyderabad metro", "hyderabad metropolitan area", "hyderabad telangana", "greater hyderabad"],
            (78.25, 17.25, 78.65, 17.60), 0.0003, [2000, 2005, 2010, 2015, 2020, 2024], 2,
            [Variable("built_up", "built-up area", 4, True), Variable("vegetation", "vegetation", 3), Variable("agriculture", "agriculture", 9), Variable("water", "water", 2)],
            303, "Telangana, India",
            "Illustrative urban expansion around settlements and transport corridors, with land-use transitions from agriculture and vegetation.",
            (17.42, 78.45), "Dry-season (February) illustrative scenes", {2010: 0.03},
            ["Built-up grows outward from eight settlement nuclei and along an outer ring corridor and radial roads; once built it stays built.", "Agriculture and vegetation are lost where the built-up front passes.", "Water bodies are nearly stable; tanks inside the densest fabric lose their edges after 2010."],
        ),
        Region(
            "bellandur-lake", "bengaluru", "Bellandur Lake, Bengaluru", ["bellandur lake", "bellandur", "bellandur lake bengaluru", "bellandur lake bangalore", "bellandur tank"],
            (77.62, 12.90, 77.72, 12.99), 0.00015, [2002, 2005, 2010, 2015, 2019, 2022], 2,
            [Variable("water", "open water", 2, True), Variable("lake_extent", "lake extent (open water and aquatic vegetation)", [2, 10]), Variable("aquatic_vegetation", "aquatic vegetation", 10), Variable("built_up", "built-up area", 4), Variable("vegetation", "vegetation", 3), Variable("wetland", "wetland fringe", 11)],
            404, "Bengaluru, Karnataka, India",
            "Illustrative lake with a stable outline: aquatic vegetation spreads over open water while the surroundings are built over. Changes inside the lake are kept separate from the surroundings.",
            (12.9352, 77.6720), "Dry-season (February) illustrative scenes", {2015: 0.03},
            ["The lake outline is nearly constant (a small shore sector is built over, about 2 percent of the lake).", "Aquatic vegetation expands in the shallow zones, replacing open water cover while the lake extent stays nearly the same.", "Built-up area grows around village nuclei and an east-west corridor, outside the lake zone only."],
        ),
    ]


SCENES: dict[str, Callable[[Region], object]] = {"himalayas": HimalayaScene, "sundarbans": SundarbansScene, "hyderabad": CityScene, "bengaluru": LakeScene}


# --------------------------------------------------------------------------------------------- writing
def _write_cog(path: Path, arr: np.ndarray, transform, tags: dict[str, str], nodata: int | None = UNC, dtype: str = "uint8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(driver="COG", height=arr.shape[0], width=arr.shape[1], count=1, dtype=dtype, crs="EPSG:4326", transform=transform, nodata=nodata, compress="DEFLATE", blocksize=256)
    try:
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(arr, 1)
            dst.update_tags(**tags)
    except Exception:  # GDAL without the COG driver: tiled GeoTIFF
        profile.update(driver="GTiff", tiled=True, blockxsize=256, blockysize=256)
        profile.pop("blocksize", None)
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(arr, 1)
            dst.update_tags(**tags)


def _degrade(clean: np.ndarray, reg: Region, year: int, seq: int, class_edges: list[int]) -> np.ndarray:
    """Add classification speckle along class boundaries and cloud (documented per region) to a clean raster."""
    rng = np.random.default_rng(reg.seed * 7919 + seq)
    out = clean.copy()
    edge = (ndi.maximum_filter(clean, 3) != ndi.minimum_filter(clean, 3))
    flip = edge & (rng.random(out.shape) < 0.04)
    if flip.any():
        shifted = np.roll(clean, 1, axis=1)
        out[flip] = shifted[flip]
    frac = reg.cloud.get(year, 0.0)
    if frac > 0:
        f = smooth(out.shape, 22, rng)
        out[f >= np.quantile(f, 1 - frac)] = UNC
    return out


def _quality(vf: float) -> str:
    return "good" if vf >= 0.9 else "fair" if vf >= 0.6 else "poor"


def _truth(reg: Region, scene, clean: dict[int, np.ndarray], row_area: np.ndarray) -> dict:
    y0, y1 = reg.years[0], reg.years[-1]
    out: dict = {"period": {"start_year": y0, "end_year": y1}, "method": "Per-variable areas from the noise-free generator rasters of the first and last year.", "rules": reg.rules, "variables": {}}
    for v in reg.variables:
        sel = (lambda a: np.isin(a, v.cls)) if isinstance(v.cls, list) else (lambda a, c=v.cls: a == c)
        a0, a1 = sel(clean[y0]), sel(clean[y1])
        out["variables"][v.key] = {
            "label": v.label, "start_ha": round(area_ha(a0, row_area), 2), "end_ha": round(area_ha(a1, row_area), 2),
            "loss_ha": round(area_ha(a0 & ~a1, row_area), 2), "gain_ha": round(area_ha(a1 & ~a0, row_area), 2), "unchanged_ha": round(area_ha(a0 & a1, row_area), 2),
        }
    return out


def generate_region(reg: Region, out: Path) -> dict:
    scene = SCENES[reg.folder](reg)
    g: Grid = scene.g  # type: ignore[attr-defined]
    syn = out / "synthetic" / reg.folder
    proc = out / "processed" / "synthetic" / reg.folder
    for d in (syn, proc):
        if d.exists():
            shutil.rmtree(d)
    (proc / "observations").mkdir(parents=True)
    (syn / "clean_truth").mkdir(parents=True)
    row_area = pixel_area_m2_per_row(g.transform, g.h, rasterio.crs.CRS.from_epsg(4326))
    legend = ";".join(f"{k}={v}" for k, v in CLASS_NAMES.items())
    clean: dict[int, np.ndarray] = {}
    observations = []
    for seq, year in enumerate(reg.years):
        c = scene.classify(year)  # type: ignore[attr-defined]
        clean[year] = c
        tags = {"DATA_DESIGNATION": "illustrative", "REGION": reg.id, "YEAR": str(year), "CLASSES": legend, "NOTE": PUBLIC_NOTE}
        _write_cog(syn / "clean_truth" / f"{year}.tif", c, g.transform, {**tags, "KIND": "noise-free generator truth"})
        arr = _degrade(c, reg, year, seq, [])
        valid = arr != UNC
        vf = float(valid.mean())
        iso = date(year, reg.month, 1).isoformat()
        _write_cog(proc / "observations" / f"{year}.tif", arr, g.transform, {**tags, "DATE": iso, "KIND": "degraded illustrative scene"})
        counts = {CLASS_NAMES[str(k)]: round(area_ha(arr == k, row_area), 2) for k in np.unique(arr) if k != UNC}
        observations.append({"date": iso, "file": f"observations/{year}.tif", "valid_fraction": round(vf, 4), "quality": _quality(vf), "sensor": "Illustrative (generated)", "class_area_ha": counts,
                             "provenance": {"designation": "illustrative", "processing": "generated by app.explorer.atlas", "nodata_fraction": round(1 - vf, 4)}})
    extras: dict = {}
    if isinstance(scene, HimalayaScene):
        _write_cog(proc / "terrain" / "elevation.tif", scene.z, g.transform, {"DATA_DESIGNATION": "illustrative", "NOTE": "Generated elevation model, identical for every year. Not a measured DEM."}, nodata=-9999, dtype="float32")
        extras["terrain"] = {"file": "terrain/elevation.tif", "designation": "illustrative", "min_m": float(scene.z.min()), "max_m": float(scene.z.max()), "note": "Generated elevation model, constant across years; no elevation time series supports change."}
    if isinstance(scene, LakeScene):
        _write_cog(proc / "zones" / "lake_zone.tif", scene.zone_mask().astype(np.uint8), g.transform, {"DATA_DESIGNATION": "illustrative", "NOTE": "1 = inside the lake basin (full outline plus margin), 0 = surroundings"}, nodata=None)
        extras["zones"] = {"file": "zones/lake_zone.tif", "values": {"1": "inside lake basin", "0": "surroundings"}}
    west, south, east, north = reg.bbox
    meta = {
        "schema_version": SCHEMA_VERSION, "id": reg.id, "name": reg.name + " (illustrative)", "description": reg.description, "kind": "raster_classification",
        "is_synthetic": True, "designation": "illustrative", "public_label": PUBLIC_LABEL, "simulated_label": PUBLIC_NOTE,
        "source": "Generated by the reusable pipeline app.explorer.atlas; no satellite data are used for these layers.", "product": "Illustrative land-cover classification",
        "format": "Cloud Optimized GeoTIFF", "crs": "EPSG:4326", "resolution_deg": reg.res_deg, "resolution_m": round(reg.res_deg * g.mx, 1),
        "temporal_resolution": "yearly" if len(reg.years) > 1 else "irregular", "bbox": [west, south, east, north],
        "location": {"name": reg.name.split(",")[0], "aliases": reg.aliases, "lat": reg.centre[0], "lon": reg.centre[1], "hint": reg.place_hint},
        "classes": CLASS_NAMES, "uncertain_value": UNC, "water_class": 2, "min_feature_px": 1,
        "variables": [{"key": v.key, "label": v.label, "class": v.cls, "primary": v.primary} for v in reg.variables],
        "coverage": {"start": observations[0]["date"], "end": observations[-1]["date"]}, "observations": observations,
        "provenance": {"designation": "illustrative", "generator": "backend/app/explorer/atlas.py", "seed": reg.seed, "rules": reg.rules, "clean_truth": f"synthetic/{reg.folder}/clean_truth/", "sensor_note": reg.sensor_note,
                       "cloud_fraction_by_year": reg.cloud, "resolution": f"{reg.res_deg} degrees"},
        "real_dataset_targets": [
            {"name": "Landsat Collection 2 Level-2", "coverage": "1982 onward (sensor dependent)", "resolution_m": 30, "status": "ACCESS_REQUIRES_AUTHENTICATION"},
            {"name": "Sentinel-2 Harmonized Surface Reflectance", "coverage": "2017-03 onward", "resolution_m": 10, "status": "VERIFIED_METADATA_ONLY"},
        ],
        **extras,
    }
    (proc / "dataset.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    (proc / "ground_truth.json").write_text(json.dumps(_truth(reg, scene, clean, row_area), indent=1), encoding="utf-8")
    (syn / "generator_config.json").write_text(json.dumps({"region": reg.id, "seed": reg.seed, "bbox": reg.bbox, "res_deg": reg.res_deg, "years": reg.years, "month": reg.month, "rules": reg.rules, "cloud_fraction_by_year": reg.cloud, "designation": "illustrative"}, indent=1), encoding="utf-8")
    return meta


def generate_all(out: Path, only: list[str] | None = None) -> list[dict]:
    return [generate_region(r, out) for r in regions() if not only or r.folder in only or r.id in only]


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the four ILLUSTRATIVE atlas regions (never satellite data).")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[3] / "datasets" / "india_historical_atlas")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    for m in generate_all(a.out, a.only):
        print(f"{m['id']}: {len(m['observations'])} observations {m['coverage']['start']}..{m['coverage']['end']}")


if __name__ == "__main__":
    main()
