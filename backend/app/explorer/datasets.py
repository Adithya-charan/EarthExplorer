"""DatasetService: registry, metadata inspection / validation, and a unified read interface.

Every dataset is a folder with ``dataset.json`` plus dated observation files. Supported observation formats:

* GeoTIFF / Cloud-Optimized GeoTIFF (class raster, any CRS; aligned onto the dataset grid with nearest neighbour)
* GeoJSON (water polygons, rasterised onto the dataset grid; ``properties.class`` or ``water`` marks water)
* CSV with geo metadata (columns ``lon,lat`` plus ``class``; points are burned into the dataset grid)

``dataset.json`` carries the dates, so no shared dates or resolution between datasets is assumed.
"""

from __future__ import annotations

import csv
import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio import features
from rasterio.crs import CRS
from rasterio.transform import Affine, from_origin
from rasterio.warp import Resampling, reproject

from app.errors import AppError
from app.explorer.geoutil import pixel_area_m2_per_row

log = logging.getLogger("earthtrend.explorer")

REQUIRED_KEYS = ("id", "name", "temporal_resolution", "bbox", "observations", "coverage")
TEMPORAL = ("monthly", "yearly", "irregular")


@dataclass
class Obs:
    date: date
    file: str
    valid_fraction: float
    quality: str
    sensor: str | None = None
    broken: str | None = None  # reason a file could not be read, filled in lazily

    @property
    def iso(self) -> str:
        return self.date.isoformat()


@dataclass
class Dataset:
    id: str
    root: Path
    meta: dict[str, Any]
    observations: list[Obs]
    issues: list[str] = field(default_factory=list)
    transform: Affine | None = None
    width: int = 0
    height: int = 0
    crs: CRS = field(default_factory=lambda: CRS.from_epsg(4326))
    row_area_m2: np.ndarray | None = None

    @property
    def water_class(self) -> int:
        return int(self.meta.get("water_class", 2))

    @property
    def variables(self) -> list[dict[str, Any]]:
        """Trackable classes. Datasets without an explicit list track water only (the original behaviour)."""
        vs = self.meta.get("variables")
        if vs:
            return [{"key": v["key"], "label": v.get("label", v["key"]), "class": [int(c) for c in v["class"]] if isinstance(v["class"], list) else int(v["class"]), "primary": bool(v.get("primary"))} for v in vs]
        return [{"key": "water", "label": "water", "class": self.water_class, "primary": True}]

    def variable(self, key: str | None = None) -> dict[str, Any]:
        vs = self.variables
        if key is None:
            return next((v for v in vs if v["primary"]), vs[0])
        for v in vs:
            if v["key"] == key:
                return v
        raise ValueError(f"unknown variable '{key}'; available: {', '.join(v['key'] for v in vs)}")

    @property
    def uncertain(self) -> int:
        return int(self.meta.get("uncertain_value", 255))

    @property
    def is_synthetic(self) -> bool:
        return bool(self.meta.get("is_synthetic"))

    @property
    def temporal(self) -> str:
        return str(self.meta["temporal_resolution"])

    @property
    def bbox(self) -> list[float]:
        return [float(v) for v in self.meta["bbox"]]

    def covers(self, lat: float, lon: float) -> bool:
        w, s, e, n = self.bbox
        return w <= lon <= e and s <= lat <= n

    def obs_by_date(self, iso: str) -> Obs | None:
        for o in self.observations:
            if o.iso == iso:
                return o
        return None

    def usable(self, o: Obs, min_valid: float) -> bool:
        return o.broken is None and o.valid_fraction >= min_valid


def _parse_date(text: str) -> date:
    return date.fromisoformat(text[:10])


def validate_meta(meta: dict[str, Any]) -> list[str]:
    """Return a list of problems; an empty list means the metadata is usable."""
    problems: list[str] = []
    for k in REQUIRED_KEYS:
        if k not in meta:
            problems.append(f"missing required key '{k}'")
    if problems:
        return problems
    if meta["temporal_resolution"] not in TEMPORAL:
        problems.append(f"temporal_resolution must be one of {TEMPORAL}")
    bb = meta["bbox"]
    if not (isinstance(bb, list) and len(bb) == 4 and all(isinstance(v, (int, float)) for v in bb)):
        problems.append("bbox must be [west, south, east, north]")
    elif not (-180 <= bb[0] < bb[2] <= 180 and -90 <= bb[1] < bb[3] <= 90):
        problems.append("bbox is outside the valid longitude/latitude range or inverted")
    if not isinstance(meta["observations"], list) or not meta["observations"]:
        problems.append("observations must be a non-empty list")
    else:
        for i, o in enumerate(meta["observations"]):
            if not isinstance(o, dict) or "date" not in o or "file" not in o:
                problems.append(f"observations[{i}] needs 'date' and 'file'")
                break
            try:
                _parse_date(str(o["date"]))
            except ValueError:
                problems.append(f"observations[{i}].date '{o['date']}' is not an ISO date")
                break
    return problems


class DatasetService:
    def __init__(self, root: Path, cache_size: int = 160):
        self.root = Path(root)
        self._datasets: dict[str, Dataset] = {}
        self._cache: OrderedDict[tuple[str, str], np.ndarray] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.RLock()
        self.rejected: dict[str, list[str]] = {}
        self.reload()

    # --------------------------------------------------------------------------- registry
    def reload(self) -> None:
        with self._lock:
            self._datasets.clear()
            self._cache.clear()
            self.rejected.clear()
            if not self.root.exists():
                return
            for meta_path in sorted(p for p in self.root.rglob("dataset.json") if len(p.relative_to(self.root).parts) <= 4):
                try:
                    ds = self._load(meta_path)
                except Exception as exc:  # a broken dataset must not stop the others loading
                    self.rejected[meta_path.parent.name] = [f"{type(exc).__name__}: {exc}"]
                    log.warning("Dataset %s rejected: %s", meta_path.parent.name, exc)
                    continue
                self._datasets[ds.id] = ds

    def _load(self, meta_path: Path) -> Dataset:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        problems = validate_meta(meta)
        if problems:
            raise ValueError("; ".join(problems))
        root = meta_path.parent
        obs: list[Obs] = []
        issues: list[str] = []
        for o in meta["observations"]:
            f = root / str(o["file"])
            if not f.exists():
                issues.append(f"{o['date']}: file {o['file']} is missing, observation ignored")
                continue
            vf = float(o.get("valid_fraction", 1.0))
            obs.append(Obs(_parse_date(str(o["date"])), str(o["file"]), vf, str(o.get("quality") or _q(vf)), o.get("sensor")))
        obs.sort(key=lambda x: x.date)
        if not obs:
            raise ValueError("no readable observation files")
        ds = Dataset(id=str(meta["id"]), root=root, meta=meta, observations=obs, issues=issues)
        self._set_grid(ds)
        return ds

    def _set_grid(self, ds: Dataset) -> None:
        w, s, e, n = ds.bbox
        crs = CRS.from_string(str(ds.meta.get("crs", "EPSG:4326")))
        res = float(ds.meta.get("resolution_deg") or 0)
        grid_set = False
        for o in ds.observations:  # the first readable raster defines the grid; unreadable ones are flagged, not fatal
            if not o.file.lower().endswith((".tif", ".tiff")):
                continue
            try:
                with rasterio.open(ds.root / o.file) as src:
                    ds.transform, ds.width, ds.height, crs = src.transform, src.width, src.height, src.crs
                grid_set = True
                break
            except Exception as exc:
                o.broken = f"{type(exc).__name__}: {exc}"[:160]
                ds.issues.append(f"{o.iso[:7]}: raster could not be opened ({o.broken})")
        if not grid_set and any(o.file.lower().endswith((".tif", ".tiff")) for o in ds.observations):
            raise ValueError("none of the GeoTIFF observations could be opened")
        if not grid_set:
            if res <= 0:
                raise ValueError("vector / CSV datasets need resolution_deg in dataset.json")
            ds.width, ds.height = max(1, round((e - w) / res)), max(1, round((n - s) / res))
            ds.transform = from_origin(w, n, res, res)
        ds.crs = crs
        ds.row_area_m2 = pixel_area_m2_per_row(ds.transform, ds.height, crs)

    def list(self) -> list[Dataset]:
        return list(self._datasets.values())

    def get(self, dataset_id: str) -> Dataset:
        ds = self._datasets.get(dataset_id)
        if ds is None:
            raise AppError(404, "dataset_not_found", f"No explorer dataset called '{dataset_id}'.")
        return ds

    def covering(self, lat: float, lon: float) -> list[Dataset]:
        return [d for d in self._datasets.values() if d.covers(lat, lon)]

    def intersecting(self, bbox: list[float] | None) -> list[Dataset]:
        """Datasets whose footprint overlaps a place's extent (a state or district contains the data without the data covering its centre)."""
        if not bbox:
            return []
        w, s, e, n = bbox
        return [d for d in self._datasets.values() if not (d.bbox[2] < w or d.bbox[0] > e or d.bbox[3] < s or d.bbox[1] > n)]

    # ------------------------------------------------------------------------------ reads
    def read(self, ds: Dataset, o: Obs) -> np.ndarray:
        """Class raster for one observation on the dataset grid. Raises AppError(422) if the file is unusable."""
        key = (ds.id, o.iso)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        try:
            arr = self._read_uncached(ds, o)
        except AppError:
            raise
        except Exception as exc:
            o.broken = f"{type(exc).__name__}: {exc}"[:160]
            raise AppError(422, "invalid_raster", f"The observation for {o.iso} could not be read ({o.broken}).") from exc
        with self._lock:
            self._cache[key] = arr
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return arr

    def _read_uncached(self, ds: Dataset, o: Obs) -> np.ndarray:
        path = ds.root / o.file
        suffix = path.suffix.lower()
        if suffix in (".tif", ".tiff"):
            with rasterio.open(path) as src:
                if src.count < 1:
                    raise ValueError("raster has no bands")
                if src.crs is None:
                    raise ValueError("raster has no CRS")
                same = src.crs == ds.crs and (src.width, src.height) == (ds.width, ds.height) and src.transform.almost_equals(ds.transform, precision=1e-9)
                if same:
                    arr = src.read(1)
                else:
                    arr = np.full((ds.height, ds.width), ds.uncertain, dtype=np.uint8)
                    reproject(rasterio.band(src, 1), arr, dst_transform=ds.transform, dst_crs=ds.crs, resampling=Resampling.nearest, dst_nodata=ds.uncertain)
        elif suffix in (".geojson", ".json"):
            arr = self._rasterise_geojson(ds, path)
        elif suffix == ".csv":
            arr = self._rasterise_csv(ds, path)
        else:
            raise ValueError(f"unsupported observation format '{suffix}'")
        arr = np.asarray(arr)
        if arr.shape != (ds.height, ds.width):
            raise ValueError(f"unexpected shape {arr.shape}, expected {(ds.height, ds.width)}")
        out = arr.astype(np.uint8, copy=False)
        nodata = ds.meta.get("nodata_value")
        if nodata is not None:
            out = np.where(arr == nodata, ds.uncertain, out).astype(np.uint8)
        return out

    def _rasterise_geojson(self, ds: Dataset, path: Path) -> np.ndarray:
        gj = json.loads(path.read_text(encoding="utf-8"))
        feats = gj.get("features") if gj.get("type") == "FeatureCollection" else [{"type": "Feature", "geometry": gj, "properties": {}}]
        if not feats:
            raise ValueError("GeoJSON has no features")
        base = np.full((ds.height, ds.width), 1, dtype=np.uint8)
        shapes = []
        for f in feats:
            props = f.get("properties") or {}
            cls = props.get("class", props.get("water") and ds.water_class)
            if cls in (True, "water", "Water", ds.water_class) or props.get("class") is None:
                shapes.append((f["geometry"], ds.water_class))
        if shapes:
            burned = features.rasterize(shapes, out_shape=(ds.height, ds.width), transform=ds.transform, fill=0, dtype="uint8")
            base[burned == ds.water_class] = ds.water_class
        return base

    def _rasterise_csv(self, ds: Dataset, path: Path) -> np.ndarray:
        base = np.full((ds.height, ds.width), ds.uncertain, dtype=np.uint8)
        inv = ~ds.transform
        n = 0
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    lon, lat, cls = float(row["lon"]), float(row["lat"]), int(float(row["class"]))
                except (KeyError, ValueError):
                    continue
                c, r = inv * (lon, lat)
                c, r = int(c), int(r)
                if 0 <= r < ds.height and 0 <= c < ds.width:
                    base[r, c] = cls
                    n += 1
        if n == 0:
            raise ValueError("CSV has no usable lon/lat/class rows inside the dataset bbox")
        return base

    # --------------------------------------------------------------------------- summaries
    def usable(self, ds: Dataset, min_valid: float = 0.5) -> list[Obs]:
        return [o for o in ds.observations if ds.usable(o, min_valid)]

    def water_shares(self, ds: Dataset) -> dict[str, float | None]:
        """Water share of valid pixels per observation date (None when an observation cannot be read)."""
        out: dict[str, float | None] = {}
        for o in ds.observations:
            try:
                a = self.read(ds, o)
            except AppError:
                out[o.iso] = None
                continue
            valid = a != ds.uncertain
            out[o.iso] = float((np.isin(a, ds.variable()["class"]) & valid).sum() / valid.sum()) if valid.any() else None
        return out


def _q(vf: float) -> str:
    return "good" if vf >= 0.9 else "fair" if vf >= 0.6 else "poor"


# ------------------------------------------------------------------------------- inspection
def inspect_file(path: Path) -> dict[str, Any]:
    """Describe and validate one geospatial / metadata file (GeoTIFF, COG, GeoJSON, CSV with geo columns, JSON metadata)."""
    path = Path(path)
    if not path.exists():
        raise AppError(404, "file_not_found", f"{path.name} does not exist.")
    suffix = path.suffix.lower()
    info: dict[str, Any] = {"file": path.name, "format": suffix.lstrip("."), "valid": True, "problems": []}
    try:
        if suffix in (".tif", ".tiff"):
            with rasterio.open(path) as src:
                info.update(
                    format="GeoTIFF" + (" (COG layout)" if src.profile.get("tiled") else ""), kind="raster",
                    crs=src.crs.to_string() if src.crs else None, width=src.width, height=src.height, bands=src.count,
                    dtype=src.dtypes[0], nodata=src.nodata, bounds=list(src.bounds), resolution=list(src.res),
                    tags={k: v for k, v in src.tags().items() if k.isupper()},
                )
                if src.crs is None:
                    info["problems"].append("no CRS: areas cannot be measured")
                if src.count < 1:
                    info["problems"].append("no bands")
        elif suffix in (".geojson", ".json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and doc.get("type") in ("FeatureCollection", "Feature", "Polygon", "MultiPolygon", "Point"):
                n = len(doc.get("features", [])) if doc.get("type") == "FeatureCollection" else 1
                info.update(format="GeoJSON", kind="vector", features=n)
                if n == 0:
                    info["problems"].append("no features")
            else:
                probs = validate_meta(doc) if isinstance(doc, dict) else ["not a JSON object"]
                info.update(format="JSON metadata", kind="metadata", keys=sorted(doc)[:20] if isinstance(doc, dict) else [])
                info["problems"].extend(probs)
        elif suffix == ".csv":
            with path.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                cols = reader.fieldnames or []
                rows = sum(1 for _ in reader)
            info.update(format="CSV", kind="table", columns=cols, rows=rows)
            if not ({"lon", "lat"} <= set(cols) or {"longitude", "latitude"} <= set(cols)):
                info["problems"].append("no lon/lat columns: not a geospatial table")
        else:
            info["problems"].append(f"unsupported format '{suffix}'")
    except AppError:
        raise
    except Exception as exc:
        info["problems"].append(f"unreadable: {type(exc).__name__}: {exc}"[:200])
    info["valid"] = not info["problems"]
    return info
