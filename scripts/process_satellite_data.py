"""Process the downloaded OFFICIAL files into NASAX datasets (app format) with a full audit trail.

Pipeline per product (each step is recorded in pipeline.json next to the dataset):
    1 inspect     open the original, record CRS / resolution / bounds / dtype / nodata
    2 clip        read only the analysis window (the original is never modified)
    3 crs         all products are already EPSG:4326; this step records that no reprojection was needed
    4 align       the window is written on the product's own pixel grid (no resampling) unless noted (WorldCover is aggregated 3x with the mode)
    5 classify    documented reclassification into app classes (thresholds listed in the dataset metadata)
    6 write       Cloud Optimized GeoTIFF observations + dataset.json with per-observation provenance

Outputs: datasets/india_historical_atlas/processed/official/<region>/<dataset id>/
Run:  python scripts/process_satellite_data.py
"""

from __future__ import annotations

import json
import math
import sys
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.windows import Window, from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from atlas_common import ATLAS, DOC, now_iso, read_json, sha256, write_json  # noqa: E402
from app.explorer.atlas import CLASS_NAMES  # noqa: E402
from app.explorer.geoutil import area_ha, pixel_area_m2_per_row  # noqa: E402

OFF = ATLAS / "official"
PROC = ATLAS / "processed" / "official"
UNC = 255


def registry() -> dict[str, dict]:
    return {e["id"]: e for e in read_json(DOC / "source_registry.json", {"entries": []})["entries"]}


def write_cog(path: Path, arr: np.ndarray, transform, tags: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prof = dict(driver="COG", height=arr.shape[0], width=arr.shape[1], count=1, dtype=str(arr.dtype), crs="EPSG:4326", transform=transform, nodata=UNC if arr.dtype == np.uint8 else None, compress="DEFLATE", blocksize=256)
    try:
        with rasterio.open(path, "w", **prof) as dst:
            dst.write(arr, 1)
            dst.update_tags(**tags)
    except Exception:
        prof.update(driver="GTiff", tiled=True, blockxsize=256, blockysize=256)
        prof.pop("blocksize", None)
        with rasterio.open(path, "w", **prof) as dst:
            dst.write(arr, 1)
            dst.update_tags(**tags)


def clip(src_path: str, bbox: tuple[float, float, float, float], resampling: Resampling | None = None, factor: int = 1):
    """Read ``bbox`` from a EPSG:4326 raster; returns (array, transform, original window, source resolution)."""
    with rasterio.open(src_path) as s:
        win = from_bounds(*bbox, transform=s.transform).round_offsets().round_lengths()
        win = Window(win.col_off, win.row_off, (win.width // factor) * factor, (win.height // factor) * factor)
        tr = s.window_transform(win)
        if factor > 1:
            out_shape = (int(win.height // factor), int(win.width // factor))
            arr = s.read(1, window=win, out_shape=out_shape, resampling=resampling or Resampling.mode)
            tr = tr * tr.scale(factor, factor)
        else:
            arr = s.read(1, window=win)
        return arr, tr, win, (s.res[0], s.res[1])


def zip_tif(zpath: Path) -> str:
    with zipfile.ZipFile(zpath) as z:
        inner = next(n for n in z.namelist() if n.lower().endswith(".tif"))
    return f"zip://{zpath.as_posix()}!/{inner}"


def finish(root: Path, meta: dict, steps: list[dict]) -> None:
    (root / "dataset.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    (root / "pipeline.json").write_text(json.dumps({"dataset": meta["id"], "generated_at": now_iso(), "steps": steps}, indent=1), encoding="utf-8")


def base_meta(ds_id: str, name: str, region_hint: str, bbox, res_deg: float, lat0: float, product: str, desc: str, aliases: list[str], loc: tuple[float, float], classes: dict, variables: list[dict], provider: str, license_: str) -> dict:
    return {
        "schema_version": 2, "id": ds_id, "name": name, "description": desc, "kind": "raster_classification", "is_synthetic": False, "designation": "official_derived",
        "public_label": "Satellite Observations", "simulated_label": None, "source": provider, "product": product, "format": "Cloud Optimized GeoTIFF (derived from the original official file)",
        "crs": "EPSG:4326", "resolution_deg": res_deg, "resolution_m": round(res_deg * 111_320 * math.cos(math.radians(lat0)), 1), "bbox": [round(v, 6) for v in bbox],
        "location": {"name": name.split(",")[0], "aliases": aliases, "lat": loc[0], "lon": loc[1], "hint": region_hint}, "classes": classes, "uncertain_value": UNC,
        "variables": variables, "license": license_,
        # Classification products on a fixed grid have no shoreline positional noise to filter; Landsat water does.
        "min_feature_px": 1 if any(k in provider for k in ("Settlement", "WorldCover")) else 3,
    }


def build_ghsl(region: str, ds_id: str, name: str, hint: str, bbox, aliases: list[str], loc: tuple[float, float], reg: dict) -> None:
    root = PROC / region / ds_id
    root.mkdir(parents=True, exist_ok=True)
    steps: list[dict] = []
    obs, dates = [], []
    THRESH = 0.15
    classes = {"1": "Not built-up (below 15% of the cell)", "4": "Built-up (at least 15% of the cell)", "255": "No data"}
    transform0 = None
    for epoch in (2000, 2010, 2020):
        rid = f"ghsl_built_s_{epoch}_R8_C26"
        e = reg[rid]
        orig = ATLAS.parent.parent / e["local_path"]
        path = zip_tif(orig)
        arr, tr, win, res = clip(path, bbox)
        transform0 = transform0 or tr
        h, w = arr.shape
        crs_ok = rasterio.open(path).crs.to_string()
        row_area = pixel_area_m2_per_row(tr, h, rasterio.crs.CRS.from_epsg(4326))
        nodata = arr == 65535
        frac = arr.astype(np.float64) / row_area[:, None]
        built = (frac >= THRESH) & ~nodata
        cls = np.full(arr.shape, 1, dtype=np.uint8)
        cls[built] = 4
        cls[nodata] = UNC
        tags = {"DATA_DESIGNATION": "official_derived", "SOURCE_ID": rid, "SOURCE_SHA256": e["sha256"], "EPOCH": str(epoch), "THRESHOLD": f"built surface >= {THRESH:.0%} of cell area"}
        write_cog(root / "intermediate" / f"built_surface_m2_{epoch}.tif", arr, tr, {**tags, "KIND": "clipped original values (m2 of built-up surface per cell)", "NODATA": "65535"})
        iso = date(epoch, 1, 1).isoformat()
        write_cog(root / "observations" / f"{epoch}.tif", cls, tr, {**tags, "DATE": iso, "KIND": "classified"})
        valid = ~nodata
        obs.append({
            "date": iso, "file": f"observations/{epoch}.tif", "valid_fraction": round(float(valid.mean()), 4), "quality": "good" if valid.mean() >= 0.9 else "fair", "sensor": "Landsat / Sentinel-2 derived (GHSL model)",
            "class_area_ha": {"Built-up (at least 15% of the cell)": round(area_ha(built, row_area), 2), "Not built-up (below 15% of the cell)": round(area_ha(~built & valid, row_area), 2)},
            "provenance": {
                "designation": "official_derived", "source_id": rid, "provider": e["providing_organization"], "dataset_identifier": e["dataset_identifier"], "official_url": e["official_dataset_url"], "download_url": e["download_url"],
                "original_file": e["original_file_name"], "original_local_path": e["local_path"], "sha256": e["sha256"], "license": e["license_or_terms"], "temporal_coverage": e["acquisition_or_temporal_coverage"],
                "date_semantics": "epoch year of a modelled product, not a single acquisition date", "original_crs": crs_ok, "original_resolution_deg": res[0], "window_pixels": [int(win.width), int(win.height)],
                "processing_operations": ["clip to analysis window", "built-up fraction = built surface m2 / geodesic cell area", f"classify built-up where fraction >= {THRESH}", "write COG"], "nodata_value": 65535,
                "nodata_fraction": round(float(nodata.mean()), 5), "processed_at": now_iso(),
            },
        })
        steps.append({"epoch": epoch, "inspect": {"crs": crs_ok, "res_deg": res[0], "dtype": str(arr.dtype)}, "clip": {"window": [int(win.col_off), int(win.row_off), int(win.width), int(win.height)]}, "crs": "no reprojection needed (EPSG:4326)",
                      "align": "native 3 arc-second grid kept", "classify": f"built-up if m2 / cell area >= {THRESH}", "output": f"observations/{epoch}.tif", "built_up_ha": obs[-1]["class_area_ha"]["Built-up (at least 15% of the cell)"]})
    meta = base_meta(ds_id, name, hint, bbox, res[0], (bbox[1] + bbox[3]) / 2, "GHS-BUILT-S R2023A built-up surface (reclassified)", "Built-up surface from the Global Human Settlement Layer at epochs 2000, 2010 and 2020, reclassified to built-up / not built-up.",
                     aliases, loc, classes, [{"key": "built_up", "label": "built-up area", "class": 4, "primary": True}], "European Commission JRC, Global Human Settlement Layer (GHS-BUILT-S R2023A)", "CC BY 4.0")
    meta.update(temporal_resolution="irregular", coverage={"start": obs[0]["date"], "end": obs[-1]["date"]}, observations=obs, water_class=4, real_dataset_targets=[])
    meta["provenance"] = {"designation": "official_derived", "note": "GHSL is a modelled product built from Landsat and Sentinel-2 imagery. Epoch years are not acquisition dates.", "pipeline": "pipeline.json"}
    finish(root, meta, steps)
    print("wrote", root)


def build_jrc_transitions(region: str, ds_id: str, name: str, hint: str, bbox, aliases: list[str], loc: tuple[float, float], reg: dict) -> None:
    rid = "jrc_gsw_transitions_70E_20N"
    e = reg[rid]
    orig = ATLAS.parent.parent / e["local_path"]
    root = PROC / region / ds_id
    arr, tr, win, res = clip(str(orig), bbox)
    # JRC transition legend: 0 not water, 1 permanent, 2 new permanent, 3 lost permanent, 4 seasonal, 5 new seasonal, 6 lost seasonal, 7 seasonal to permanent, 8 permanent to seasonal, 9 ephemeral permanent, 10 ephemeral seasonal
    water_first = np.isin(arr, [1, 3, 4, 6, 7, 8])
    water_last = np.isin(arr, [1, 2, 4, 5, 7, 8])
    h = arr.shape[0]
    row_area = pixel_area_m2_per_row(tr, h, rasterio.crs.CRS.from_epsg(4326))
    tags = {"DATA_DESIGNATION": "official_derived", "SOURCE_ID": rid, "SOURCE_SHA256": e["sha256"]}
    write_cog(root / "intermediate" / "transitions_clip.tif", arr, tr, {**tags, "KIND": "clipped original transition classes 0-10"})
    obs = []
    for label, wmask, iso in (("first year of the JRC record (1984)", water_first, "1984-01-01"), ("last year of the JRC record (2021)", water_last, "2021-01-01")):
        cls = np.where(wmask, 2, 1).astype(np.uint8)
        fn = f"observations/{iso[:4]}.tif"
        write_cog(root / fn, cls, tr, {**tags, "DATE": iso, "KIND": f"water state, {label}"})
        obs.append({
            "date": iso, "file": fn, "valid_fraction": 1.0, "quality": "fair", "sensor": "Landsat-derived (JRC Global Surface Water)", "class_area_ha": {"Water": round(area_ha(wmask, row_area), 2)},
            "provenance": {
                "designation": "official_derived", "source_id": rid, "provider": e["providing_organization"], "dataset_identifier": e["dataset_identifier"], "official_url": e["official_dataset_url"], "download_url": e["download_url"],
                "original_file": e["original_file_name"], "original_local_path": e["local_path"], "sha256": e["sha256"], "license": e["license_or_terms"], "temporal_coverage": e["acquisition_or_temporal_coverage"],
                "date_semantics": f"{label}, taken from the product's transition layer; not a single acquisition date", "original_crs": "EPSG:4326", "original_resolution_deg": res[0], "window_pixels": [int(win.width), int(win.height)],
                "processing_operations": ["clip to analysis window", "water state at each end derived from the 11 transition classes", "write COG"], "nodata_fraction": 0.0, "processed_at": now_iso(),
                "limitation": "Early Landsat coverage over India is sparse, so the 1984 state is less certain than the 2021 state. Floating vegetation and froth can hide water from this method.",
            },
        })
    meta = base_meta(ds_id, name, hint, bbox, res[0], (bbox[1] + bbox[3]) / 2, "JRC Global Surface Water transitions (v1.4, 2021 release)", "Water state at the first and last year of the JRC record, derived from the transition layer.", aliases, loc,
                     {"1": "Not water", "2": "Water (permanent or seasonal)", "255": "No data"}, [{"key": "water", "label": "water", "class": 2, "primary": True}], "European Commission JRC, Global Surface Water Explorer", "Free and open; cite Pekel et al. (2016)")
    meta.update(temporal_resolution="irregular", coverage={"start": obs[0]["date"], "end": obs[-1]["date"]}, observations=obs, water_class=2, real_dataset_targets=[],
                provenance={"designation": "official_derived", "note": "Two-date comparison taken from JRC's own transition layer.", "pipeline": "pipeline.json"})
    steps = [{"inspect": {"crs": "EPSG:4326", "res_deg": res[0], "dtype": str(arr.dtype)}, "clip": {"window": [int(win.col_off), int(win.row_off), int(win.width), int(win.height)]}, "crs": "no reprojection needed (EPSG:4326)",
              "align": "native 1 arc-second grid kept", "classify": "water first = classes 1,3,4,6,7,8; water last = classes 1,2,4,5,7,8", "water_ha_first": obs[0]["class_area_ha"]["Water"], "water_ha_last": obs[1]["class_area_ha"]["Water"], "classes_present": {int(k): int(v) for k, v in zip(*np.unique(arr, return_counts=True))}}]
    finish(root, meta, steps)
    print("wrote", root)


def build_worldcover(region: str, ds_id: str, name: str, hint: str, bbox, aliases: list[str], loc: tuple[float, float], reg: dict) -> None:
    rid = "esa_worldcover_2021_N21E087"
    e = reg[rid]
    orig = ATLAS.parent.parent / e["local_path"]
    root = PROC / region / ds_id
    arr, tr, win, res = clip(str(orig), bbox, Resampling.mode, factor=3)
    lut = np.full(256, 1, dtype=np.uint8)
    for src, dst in ((10, 3), (20, 3), (30, 3), (90, 3), (40, 9), (50, 4), (60, 1), (70, 1), (80, 2), (95, 8), (100, 3)):
        lut[src] = dst
    cls = lut[arr]
    cls[arr == 0] = UNC
    h = cls.shape[0]
    row_area = pixel_area_m2_per_row(tr, h, rasterio.crs.CRS.from_epsg(4326))
    tags = {"DATA_DESIGNATION": "official_derived", "SOURCE_ID": rid, "SOURCE_SHA256": e["sha256"], "DATE": "2021-01-01"}
    write_cog(root / "intermediate" / "worldcover_window_mode3x.tif", arr, tr, {**tags, "KIND": "original class codes aggregated 3x (mode) from 10 m to 30 m"})
    write_cog(root / "observations" / "2021.tif", cls, tr, {**tags, "KIND": "reclassified"})
    cnt = {CLASS_NAMES[str(k)]: round(area_ha(cls == k, row_area), 2) for k in np.unique(cls) if k != UNC}
    obs = [{
        "date": "2021-01-01", "file": "observations/2021.tif", "valid_fraction": round(float((cls != UNC).mean()), 4), "quality": "good", "sensor": "Sentinel-1 / Sentinel-2 derived (ESA WorldCover)", "class_area_ha": cnt,
        "provenance": {
            "designation": "official_derived", "source_id": rid, "provider": e["providing_organization"], "dataset_identifier": e["dataset_identifier"], "official_url": e["official_dataset_url"], "download_url": e["download_url"],
            "original_file": e["original_file_name"], "original_local_path": e["local_path"], "sha256": e["sha256"], "license": e["license_or_terms"], "temporal_coverage": e["acquisition_or_temporal_coverage"],
            "date_semantics": "map year 2021, not a single acquisition date", "original_crs": "EPSG:4326", "original_resolution_deg": res[0], "window_pixels": [int(win.width), int(win.height)],
            "processing_operations": ["clip to analysis window", "aggregate 3x3 with the mode", "reclassify: 95 mangroves to 8; 80 water to 2; 40 cropland to 9; 50 built-up to 4; 10/20/30/90/100 to 3; others to 1", "write COG"], "nodata_fraction": round(float((cls == UNC).mean()), 5), "processed_at": now_iso(),
        },
    }]
    classes = {k: v for k, v in CLASS_NAMES.items() if k in {"1", "2", "3", "4", "8", "9", "255"}}
    meta = base_meta(ds_id, name, hint, bbox, tr.a, (bbox[1] + bbox[3]) / 2, "ESA WorldCover 10 m 2021 v200 (reclassified, aggregated to 30 m)", "A single 2021 land-cover map with mangrove. One date only, so no change can be measured from it.", aliases, loc, classes,
                     [{"key": "mangrove", "label": "mangrove", "class": 8, "primary": True}, {"key": "water", "label": "water", "class": 2}], "European Space Agency, ESA WorldCover", "CC BY 4.0")
    meta.update(temporal_resolution="irregular", coverage={"start": "2021-01-01", "end": "2021-01-01"}, observations=obs, water_class=2, real_dataset_targets=[],
                provenance={"designation": "official_derived", "note": "Single-date product.", "pipeline": "pipeline.json"})
    steps = [{"inspect": {"crs": "EPSG:4326", "res_deg": res[0], "dtype": str(arr.dtype)}, "clip": {"window": [int(win.col_off), int(win.row_off), int(win.width), int(win.height)]}, "crs": "no reprojection needed (EPSG:4326)",
              "align": "3x3 mode aggregation to 0.00025 degrees", "classify": "see processing_operations", "class_area_ha": cnt}]
    finish(root, meta, steps)
    print("wrote", root)


def build_occurrence(region: str, tile_id: str, bbox, name: str) -> None:
    """Context layer: the long-term water occurrence clipped to the region (not a dated observation)."""
    reg = registry()
    e = reg[tile_id]
    orig = ATLAS.parent.parent / e["local_path"]
    arr, tr, win, res = clip(str(orig), bbox)
    out = PROC / region / "context" / f"jrc_water_occurrence_{region}.tif"
    write_cog(out, arr, tr, {"DATA_DESIGNATION": "official_derived", "SOURCE_ID": tile_id, "SOURCE_SHA256": e["sha256"], "KIND": "water occurrence percent 1984-2021, clipped; 255 = no data", "NAME": name})
    print("wrote", out)


def main() -> None:
    reg = registry()
    missing = [k for k in ("ghsl_built_s_2000_R8_C26", "jrc_gsw_transitions_70E_20N", "esa_worldcover_2021_N21E087") if reg.get(k, {}).get("verification_status") != "VERIFIED_DOWNLOADED"]
    if missing:
        sys.exit(f"Run scripts/download_official_data.py first; not downloaded: {missing}")
    hyd = (78.25, 17.25, 78.65, 17.60)
    blr_wide = (77.55, 12.85, 77.80, 13.05)
    bell = (77.62, 12.90, 77.72, 12.99)
    sun = (88.60, 21.55, 89.10, 22.05)
    build_ghsl("hyderabad", "ghsl-built-up-hyderabad", "Hyderabad metropolitan area (GHSL built-up)", "Telangana, India", hyd, ["hyderabad", "hyderabad metro", "hyderabad metropolitan area", "greater hyderabad"], (17.42, 78.45), reg)
    build_ghsl("bengaluru", "ghsl-built-up-bengaluru", "Bellandur and east Bengaluru (GHSL built-up)", "Bengaluru, Karnataka, India", blr_wide, ["bellandur", "bellandur lake", "east bengaluru"], (12.9352, 77.6720), reg)
    build_jrc_transitions("bengaluru", "jrc-water-bellandur", "Bellandur Lake (JRC surface water)", "Bengaluru, Karnataka, India", bell, ["bellandur lake", "bellandur"], (12.9352, 77.6720), reg)
    build_jrc_transitions("hyderabad", "jrc-water-hyderabad", "Hyderabad lakes (JRC surface water)", "Telangana, India", hyd, ["hyderabad", "hussain sagar", "hussain sagar lake"], (17.4239, 78.4738), reg)
    build_worldcover("sundarbans", "worldcover-sundarbans-2021", "Sundarbans (ESA WorldCover 2021)", "West Bengal, India", sun, ["sundarbans", "the sundarbans", "sunderbans"], (21.80, 88.85), reg)
    build_occurrence("bengaluru", "jrc_gsw_occurrence_70E_20N", bell, "Bellandur Lake")
    build_occurrence("hyderabad", "jrc_gsw_occurrence_70E_20N", hyd, "Hyderabad")
    build_occurrence("sundarbans", "jrc_gsw_occurrence_80E_30N", sun, "Sundarbans")


if __name__ == "__main__":
    main()
