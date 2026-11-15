"""Reusable generator for SIMULATED land-cover time series used by the Earth Time Machine demo.

Everything produced here is invented. Every dataset.json carries ``is_synthetic: true`` and a ``simulated_label`` that the
API and the UI repeat. The generator writes, per site:

    <out>/<site id>/dataset.json            metadata, class legend, observation index (date, quality, valid fraction)
    <out>/<site id>/observations/*.tif      one classified GeoTIFF per observation (EPSG:4326, uint8, nodata 255)
    <out>/<site id>/ground_truth.json       the controlled changes that were built in, and their true areas

Class codes: 1 land, 2 water, 3 vegetation, 4 built-up, 255 uncertain / no data (cloud, gap).

The lake outline, the encroachment, the drying arm and the new pond are controlled, known changes so detection can be
checked against ground truth. Seasonal fluctuation, speckle, clouds and missing months are added on purpose so the
analysis has to cope with them. Run ``python -m app.explorer.synthetic`` to (re)generate everything.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.transform import from_origin
from scipy import ndimage as ndi
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from app.explorer.geoutil import area_ha, pixel_area_m2_per_row

LAND, WATER, VEG, BUILT, UNCERTAIN = 1, 2, 3, 4, 255
CLASSES = {"1": "Land (bare / other)", "2": "Water", "3": "Vegetation", "4": "Built-up", "255": "Uncertain or no data"}
SIMULATED_LABEL = "SIMULATED DEMONSTRATION DATA — not satellite observations"
SCHEMA_VERSION = 1


@dataclass
class Event:
    kind: str  # "encroachment" (water -> built-up), "drying" (water -> land), "new_pond" (land -> water)
    start: float  # decimal year
    end: float
    angle_from: float = 0.0  # degrees counter-clockwise from east, for sector events
    angle_to: float = 0.0
    centre_m: tuple[float, float] = (0.0, 0.0)  # pond centre, metres east/north of the site centre
    radius_m: float = 0.0
    note: str = ""


@dataclass
class Site:
    id: str
    name: str
    aliases: list[str]
    lon: float
    lat: float
    half_w_deg: float
    half_h_deg: float
    lake_a_m: float
    lake_b_m: float
    lake_rot_deg: float
    temporal_resolution: str  # "monthly" | "yearly"
    first_year: int
    last_year: int
    res_deg: float = 0.0003
    yearly_month: int = 12
    events: list[Event] = field(default_factory=list)
    missing_prob: float = 0.0
    gap_months: list[tuple[int, int]] = field(default_factory=list)  # (year, month) observations that do not exist
    cloud_prob_monsoon: float = 0.0
    explicit: list[tuple[int, int, float]] | None = None  # (year, month, cloud fraction) when the dates are fixed
    seed: int = 1
    description: str = ""
    place_hint: str = ""


SITES: list[Site] = [
    Site(
        id="bellandur-synthetic",
        name="Bellandur Lake, Bengaluru (simulated)",
        aliases=["bellandur lake", "bellandur", "bellandur lake bengaluru", "bellandur lake, bengaluru, india"],
        lon=77.672, lat=12.935, half_w_deg=0.06, half_h_deg=0.05,
        lake_a_m=1900, lake_b_m=750, lake_rot_deg=62,
        temporal_resolution="monthly", first_year=2000, last_year=2025,
        events=[
            Event("encroachment", 2008.0, 2018.0, -75, -5, note="Shore lobe in the south-east is gradually built over."),
            Event("drying", 2012.0, 2022.0, 135, 185, note="Shallow arm in the north-west dries out to bare land."),
            Event("new_pond", 2016.4, 2016.4, centre_m=(1500, 850), radius_m=170, note="A small retention pond appears in the north-east."),
        ],
        missing_prob=0.06, gap_months=[(2003, m) for m in range(4, 9)], cloud_prob_monsoon=0.6, seed=11,
        description="Simulated monthly classification of a Bellandur-like lake with controlled encroachment, drying and a new pond.",
        place_hint="Bengaluru, Karnataka, India",
    ),
    Site(
        id="hussain-sagar-synthetic",
        name="Hussain Sagar, Hyderabad (simulated)",
        aliases=["hussain sagar", "hussain sagar lake", "hussain sagar hyderabad", "hussain sagar, hyderabad, india"],
        lon=78.4738, lat=17.4239, half_w_deg=0.04, half_h_deg=0.035,
        lake_a_m=1050, lake_b_m=800, lake_rot_deg=20,
        temporal_resolution="yearly", first_year=2005, last_year=2023, yearly_month=12,
        events=[], missing_prob=0.0, seed=23,
        description="Simulated yearly classification of a stable lake: only seasonal-scale noise and speckle, no built-in change.",
        place_hint="Hyderabad, Telangana, India",
    ),
    Site(
        id="chilika-synthetic",
        name="Chilika Lake patch, Odisha (simulated, sparse)",
        aliases=["chilika lake", "chilika", "chilika lake odisha", "chilika lake, odisha, india"],
        lon=85.32, lat=19.72, half_w_deg=0.07, half_h_deg=0.05, res_deg=0.0004,
        lake_a_m=4200, lake_b_m=2300, lake_rot_deg=35,
        temporal_resolution="yearly", first_year=2014, last_year=2019, yearly_month=2,
        events=[], seed=37,
        explicit=[(2014, 2, 0.62), (2016, 2, 0.0), (2019, 2, 0.05)],
        description="Simulated sparse series: three observations, the earliest mostly clouded. Exists to test insufficient-data handling.",
        place_hint="Odisha, India",
    ),
]


def _smooth(shape_: tuple[int, int], sigma: float, rng: np.random.Generator) -> np.ndarray:
    f = ndi.gaussian_filter(rng.standard_normal(shape_), sigma, mode="reflect")
    return (f - f.mean()) / (f.std() + 1e-12)


class _Scene:
    """Fixed fields for one site; ``classify`` turns a date into a clean (cloud-free) class raster."""

    def __init__(self, site: Site):
        self.site = site
        self.w = int(round(2 * site.half_w_deg / site.res_deg))
        self.h = int(round(2 * site.half_h_deg / site.res_deg))
        self.west = site.lon - site.half_w_deg
        self.north = site.lat + site.half_h_deg
        self.transform = from_origin(self.west, self.north, site.res_deg, site.res_deg)
        rng = np.random.default_rng(site.seed)
        cols = np.arange(self.w) + 0.5
        rows = np.arange(self.h) + 0.5
        lon = self.west + cols * site.res_deg
        lat = self.north - rows * site.res_deg
        mlat = 110_574.0
        mlon = 111_320.0 * math.cos(math.radians(site.lat))
        self.x = np.tile(((lon - site.lon) * mlon)[None, :], (self.h, 1))
        self.y = np.tile(((lat - site.lat) * mlat)[:, None], (1, self.w))
        rot = math.radians(site.lake_rot_deg)
        xr = self.x * math.cos(rot) + self.y * math.sin(rot)
        yr = -self.x * math.sin(rot) + self.y * math.cos(rot)
        r = np.sqrt((xr / site.lake_a_m) ** 2 + (yr / site.lake_b_m) ** 2)
        wobble = _smooth((self.h, self.w), 12, rng)
        r_eff = r * (1.0 + 0.10 * wobble)
        self.depth = 1.0 - r_eff  # > 0 inside the lake at full extent
        self.angle = (np.degrees(np.arctan2(self.y, self.x)) + 360.0) % 360.0
        self.schedule = np.clip(0.5 * (1 - np.clip(self.depth, 0, 1)) + 0.5 * (0.5 + 0.25 * _smooth((self.h, self.w), 6, rng)), 0, 1)
        self.urban = _smooth((self.h, self.w), 18, rng)
        self.veg = _smooth((self.h, self.w), 10, rng)
        self.year_anomaly = {y: float(np.random.default_rng(site.seed * 1000 + y).normal(0, 0.012)) for y in range(site.first_year - 1, site.last_year + 2)}

    def _in_sector(self, ev: Event) -> np.ndarray:
        a0, a1 = ev.angle_from % 360, ev.angle_to % 360
        return (self.angle >= a0) & (self.angle <= a1) if a0 <= a1 else (self.angle >= a0) | (self.angle <= a1)

    def classify(self, year: int, month: int) -> np.ndarray:
        s = self.site
        ty = year + (month - 0.5) / 12.0
        season = 0.10 * (1 + math.cos(2 * math.pi * (month - 9) / 12.0)) / 2.0  # lake is fullest in September
        thr = season + self.year_anomaly[year]
        water = self.depth > thr
        built_extra = np.zeros_like(water)
        for ev in s.events:
            if ev.kind in ("encroachment", "drying"):
                done = ty >= ev.start + self.schedule * (ev.end - ev.start)
                hit = self._in_sector(ev) & (self.depth > 0.0) & done
                water &= ~hit
                if ev.kind == "encroachment":
                    built_extra |= hit
            elif ev.kind == "new_pond" and ty >= ev.start:
                d = np.hypot(self.x - ev.centre_m[0], self.y - ev.centre_m[1]) / ev.radius_m
                water |= (1.0 - d) > (thr * 0.8)
        g = (ty - s.first_year) / max(1.0, s.last_year - s.first_year)  # urban growth 0..1
        built = (self.urban + 1.4 * g - 0.55) > 0.75
        veg = (self.veg > 0.1) & ~built
        cls = np.full((self.h, self.w), LAND, dtype=np.uint8)
        cls[veg] = VEG
        cls[built | built_extra] = BUILT
        cls[water] = WATER
        return cls


def _observation_dates(site: Site) -> list[tuple[int, int, float | None]]:
    """(year, month, forced cloud fraction or None) for every observation that exists."""
    if site.explicit is not None:
        return [(y, m, c) for y, m, c in site.explicit]
    rng = np.random.default_rng(site.seed + 99)
    gaps = set(site.gap_months)
    out: list[tuple[int, int, float | None]] = []
    for y in range(site.first_year, site.last_year + 1):
        months = range(1, 13) if site.temporal_resolution == "monthly" else [site.yearly_month]
        for m in months:
            if (y, m) in gaps or rng.random() < site.missing_prob:
                continue
            out.append((y, m, None))
    return out


def _decorate(cls: np.ndarray, scene: _Scene, year: int, month: int, forced_cloud: float | None, seq: int) -> np.ndarray:
    """Add speckle along the water edge and cloud/uncertain pixels to a clean raster."""
    s = scene.site
    rng = np.random.default_rng(s.seed * 7919 + seq)
    out = cls.copy()
    water = out == WATER
    edge = ndi.binary_dilation(water, iterations=1) & ~ndi.binary_erosion(water, iterations=1)
    flip = edge & (rng.random(out.shape) < 0.05)
    out[flip & water] = LAND
    out[flip & ~water] = WATER
    cloud_fraction = 0.0
    if forced_cloud is not None:
        cloud_fraction = forced_cloud
    elif 6 <= month <= 9 and rng.random() < s.cloud_prob_monsoon:
        cloud_fraction = float(rng.uniform(0.05, 0.9) ** 1.6)
    elif rng.random() < 0.05:
        cloud_fraction = float(rng.uniform(0.02, 0.15))
    if cloud_fraction > 0:
        field_ = _smooth(out.shape, 25, rng)
        cutoff = np.quantile(field_, 1 - cloud_fraction)
        out[field_ >= cutoff] = UNCERTAIN
    return out


def _write(path: Path, arr: np.ndarray, transform, tags: dict[str, str]) -> None:
    profile = dict(driver="COG", height=arr.shape[0], width=arr.shape[1], count=1, dtype="uint8", crs="EPSG:4326", transform=transform, nodata=UNCERTAIN, compress="DEFLATE", blocksize=256)
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


def _quality(valid_fraction: float) -> str:
    return "good" if valid_fraction >= 0.9 else "fair" if valid_fraction >= 0.6 else "poor"


def _truth(scene: _Scene, row_area: np.ndarray) -> dict:
    """True (cloud-free, speckle-free) change between the first and last year, from the generating model itself."""
    s = scene.site
    months = range(1, 13) if s.temporal_resolution == "monthly" else [s.yearly_month]

    def freq(year: int) -> np.ndarray:
        acc = np.zeros((scene.h, scene.w))
        for m in months:
            acc += scene.classify(year, m) == WATER
        return acc / len(list(months))

    w0, w1 = freq(s.first_year) >= 0.5, freq(s.last_year) >= 0.5
    loss, gain, stable = w0 & ~w1, w1 & ~w0, w0 & w1

    def polys(mask: np.ndarray) -> list[dict]:
        out = []
        for geom, val in shapes(mask.astype(np.uint8), mask=mask, transform=scene.transform):
            if val == 1:
                out.append(mapping(shape(geom)))
        return out

    return {
        "period": {"start_year": s.first_year, "end_year": s.last_year},
        "method": "Matched-season water frequency >= 0.5 in the first and last year of the simulation, from the noise-free generator.",
        "water_start_ha": round(area_ha(w0, row_area), 2),
        "water_end_ha": round(area_ha(w1, row_area), 2),
        "loss_ha": round(area_ha(loss, row_area), 2),
        "gain_ha": round(area_ha(gain, row_area), 2),
        "unchanged_water_ha": round(area_ha(stable, row_area), 2),
        "loss_geojson": {"type": "GeometryCollection", "geometries": polys(loss)},
        "gain_geojson": {"type": "GeometryCollection", "geometries": polys(gain)},
        "events": [
            {"kind": e.kind, "start": e.start, "end": e.end, "note": e.note,
             **({"angle_from": e.angle_from, "angle_to": e.angle_to} if e.kind != "new_pond" else {"centre_m": list(e.centre_m), "radius_m": e.radius_m})}
            for e in s.events
        ],
    }


def generate_site(site: Site, out_dir: Path) -> dict:
    scene = _Scene(site)
    root = out_dir / site.id
    obs_dir = root / "observations"
    if root.exists():
        shutil.rmtree(root)
    obs_dir.mkdir(parents=True)
    row_area = pixel_area_m2_per_row(scene.transform, scene.h, rasterio.crs.CRS.from_epsg(4326))
    observations = []
    for seq, (y, m, forced) in enumerate(_observation_dates(site)):
        clean = scene.classify(y, m)
        arr = _decorate(clean, scene, y, m, forced, seq)
        valid = arr != UNCERTAIN
        vf = float(valid.mean())
        iso = date(y, m, 1).isoformat()
        name = f"{y}-{m:02d}.tif" if site.temporal_resolution == "monthly" else f"{y}.tif"
        _write(obs_dir / name, arr, scene.transform, {"SYNTHETIC": "true", "DATE": iso, "SIMULATED": SIMULATED_LABEL})
        observations.append(
            {
                "date": iso,
                "file": f"observations/{name}",
                "valid_fraction": round(vf, 4),
                "quality": _quality(vf),
                "water_area_ha": round(area_ha((arr == WATER), row_area), 2),
                "sensor": "SIMULATED",
            }
        )
    west, south = scene.west, site.lat - site.half_h_deg
    meta = {
        "schema_version": SCHEMA_VERSION,
        "id": site.id,
        "name": site.name,
        "description": site.description,
        "kind": "raster_classification",
        "is_synthetic": True,
        "simulated_label": SIMULATED_LABEL,
        "source": "Reusable Python generator (app.explorer.synthetic). No satellite data.",
        "product": "Simulated land-cover classification",
        "format": "GeoTIFF (Cloud-Optimized when GDAL supports it)",
        "crs": "EPSG:4326",
        "resolution_deg": site.res_deg,
        "resolution_m": round(site.res_deg * 111_320 * math.cos(math.radians(site.lat)), 1),
        "temporal_resolution": site.temporal_resolution,
        "bbox": [round(west, 6), round(south, 6), round(site.lon + site.half_w_deg, 6), round(site.lat + site.half_h_deg, 6)],
        "location": {"name": site.name.split(" (")[0], "aliases": site.aliases, "lat": site.lat, "lon": site.lon, "hint": site.place_hint},
        "classes": CLASSES,
        "uncertain_value": UNCERTAIN,
        "water_class": WATER,
        "coverage": {"start": observations[0]["date"], "end": observations[-1]["date"]},
        "observations": observations,
        "real_dataset_targets": [
            {"name": "JRC Global Surface Water Monthly History", "coverage": "1984-03 to 2021-12", "resolution_m": 30},
            {"name": "Landsat Collection 2", "coverage": "1982 onward (depends on sensor and product)", "resolution_m": 30},
            {"name": "Sentinel-2 Harmonized Surface Reflectance", "coverage": "2017-03 onward", "resolution_m": 10},
        ],
    }
    (root / "dataset.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    (root / "ground_truth.json").write_text(json.dumps(_truth(scene, row_area)), encoding="utf-8")
    return meta


def generate_all(out_dir: Path, *, sites: list[Site] | None = None) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    return [generate_site(s, out_dir) for s in (sites or SITES)]


def ensure_demo_data(out_dir: Path) -> None:
    """Generate any missing demo dataset (used on first start; a no-op once the folders exist)."""
    for s in SITES:
        if not (out_dir / s.id / "dataset.json").exists():
            generate_site(s, out_dir)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate SIMULATED demo datasets for the Earth Time Machine.")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "data" / "explorer")
    args = ap.parse_args()
    for meta in generate_all(args.out):
        print(f"{meta['id']}: {len(meta['observations'])} observations, {meta['temporal_resolution']}, {meta['coverage']['start']} to {meta['coverage']['end']}")


if __name__ == "__main__":
    main()
