"""Assemble 01_ORIGINAL, 02_PROCESSED and 04_RECONSTRUCTION_FRAMES of NASAX_DEEP_TIME_EVIDENCE.

    backend/.venv/Scripts/python -X utf8 scripts/build_deeptime_evidence.py

Originals are copied byte for byte (never converted). Processed products are derived from them and the built frames:
GeoJSON (all frames), GeoPackage (one per frame), Shapefile (evidence frames), GPML (Indian Plate static polygons),
GeoTIFF (every PALEOMAP map used), Cloud-Optimised GeoTIFF (evidence frames) and NetCDF (seafloor age, Indian Ocean subset).
Not every dataset is converted to every format: each format is made only where it is meaningful.
"""
from __future__ import annotations

import json
import os
import shutil
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pygplates
import rasterio
import rasterio.shutil
import xarray as xr
from PIL import Image
from rasterio.transform import from_bounds

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "deep_time"
EVID = Path(os.environ.get("DEEPTIME_EVIDENCE", "F:/NASAX_DEEP_TIME_EVIDENCE"))
ORIG = Path(os.environ.get("DEEPTIME_ROOT", "F:/NASAX_DEEPTIME")) / "originals"
PROC = EVID / "02_PROCESSED_GEOLOGICAL_DATA"
EVIDENCE_AGES = [250, 200, 150, 120, 100, 75, 66, 55, 40, 20, 0]
LAYERS = ["plates", "continents", "coastlines", "cao_landmass", "cao_shallow_marine", "cao_mountains", "cao_ice_sheet", "india_outline_earthbyte", "india_outline_paleomap"]
log: dict[str, list[str]] = {}


def note(kind: str, path: Path) -> None:
    log.setdefault(kind, []).append(str(path.relative_to(EVID)).replace("\\", "/"))


def cp(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


# ------------------------------------------------------------------------------------------- 01 originals
def originals() -> None:
    base = EVID / "01_ORIGINAL_SCIENTIFIC_DATA"
    for folder in ("EARTHBYTE", "GPLATES", "MACROSTRAT", "PALEOBIOLOGY_DATABASE", "GEOLOGICAL_TIME_SCALE"):
        for f in (ORIG / folder).iterdir():
            if f.is_file():
                cp(f, base / folder / f.name)
                note("original", base / folder / f.name)
    # The unpacked members that the processing used, kept next to the zips so a reviewer can open them without unzipping.
    ex = ORIG / "EARTHBYTE" / "extracted"
    for f in ex.rglob("*"):
        if f.is_file() and f.suffix.lower() in {".rot", ".gpml", ".txt", ".pdf"}:
            cp(f, base / "EARTHBYTE" / "unpacked_members" / f.name)
            note("original", base / "EARTHBYTE" / "unpacked_members" / f.name)
    gx = ORIG / "GPLATES" / "extracted" / "GeoData"
    for pat in ("Rotations/*.rot", "StaticPolygons/README.txt", "StaticPolygons/Shapefile/*"):
        for f in (gx / "FeatureCollections").glob(pat):
            if f.is_file():
                cp(f, base / "GPLATES" / "unpacked_members" / f.name)
                note("original", base / "GPLATES" / "unpacked_members" / f.name)


# ------------------------------------------------------------------------------------------- 02 processed
def geojson_frames() -> None:
    src = DATA / "frames"
    n = 0
    for k in sorted(p.name for p in src.iterdir() if p.is_dir()):
        for f in (src / k).glob("*.geojson"):
            cp(f, PROC / "GEOJSON" / "frames" / k / f.name)
            n += 1
        cp(src / k / "frame.json", PROC / "GEOJSON" / "frames" / k / "frame.json")
    for name in ("fossils.json", "formations.json"):
        cp(DATA / name, PROC / "GEOJSON" / name)
    note("geojson", PROC / "GEOJSON" / "frames")


def read_layer(path: Path) -> gpd.GeoDataFrame | None:
    fc = json.loads(path.read_text(encoding="utf-8"))
    if not fc.get("features"):
        return None
    g = gpd.GeoDataFrame.from_features(fc["features"], crs="EPSG:4326")
    for c in g.columns:
        if c != "geometry" and g[c].map(lambda v: isinstance(v, (list, dict))).any():
            g[c] = g[c].map(lambda v: json.dumps(v) if isinstance(v, (list, dict)) else v)
    return g


def geopackages() -> None:
    out = PROC / "GEOPACKAGE"
    out.mkdir(parents=True, exist_ok=True)
    for kdir in sorted((DATA / "frames").iterdir()):
        gp = out / f"deeptime_frame_{kdir.name}.gpkg"
        if gp.exists():
            gp.unlink()
        for name in LAYERS:
            p = kdir / f"{name}.geojson"
            if p.exists():
                g = read_layer(p)
                if g is not None:
                    g.to_file(gp, layer=name, driver="GPKG")
        note("geopackage", gp)


def shapefiles() -> None:
    out = PROC / "SHAPEFILE"
    for a in EVIDENCE_AGES:
        k = f"{a:g}".replace(".", "p")
        for name in ("plates", "cao_landmass", "cao_shallow_marine", "cao_mountains", "india_outline_earthbyte"):
            p = DATA / "frames" / k / f"{name}.geojson"
            if p.exists():
                g = read_layer(p)
                if g is not None:
                    d = out / f"{k}_Ma"
                    d.mkdir(parents=True, exist_ok=True)
                    f = d / f"{name}.shp"
                    g.to_file(f, driver="ESRI Shapefile", encoding="utf-8")
                    note("shapefile", f)


def gpml() -> None:
    out = PROC / "GPML"
    out.mkdir(parents=True, exist_ok=True)
    srcs = {
        "earthbyte_static_polygons": ORIG / "GPLATES/extracted/GeoData/FeatureCollections/StaticPolygons/Global_EarthByte_GPlates_PresentDay_StaticPlatePolygons.gpmlz",
        "paleomap_plate_polygons": ORIG / "EARTHBYTE/extracted/Scotese PaleoAtlas_v3/PALEOMAP Global Plate Model/PALEOMAP_PlatePolygons.gpml",
    }
    for name, src in srcs.items():
        fc = pygplates.FeatureCollection(str(src))
        keep = [f for f in fc if f.get_reconstruction_plate_id() == 501]
        if not keep:
            continue
        dst = out / f"india_plate_501_{name}.gpml"
        pygplates.FeatureCollection(keep).write(str(dst))
        note("gpml", dst)


def geotiffs() -> None:
    man = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    used = sorted({fm["models"]["paleomap"]["map_file"] for fm in man["frames"] if fm["models"]["paleomap"].get("map_file")})
    for rel in used:
        n = int(Path(rel).stem)
        arr = np.asarray(Image.open(DATA / rel).convert("RGB"))
        h, w, _ = arr.shape
        dst = PROC / "GEOTIFF" / f"paleomap_{n:03d}.tif"
        dst.parent.mkdir(parents=True, exist_ok=True)
        prof = dict(driver="GTiff", height=h, width=w, count=3, dtype="uint8", crs="EPSG:4326", transform=from_bounds(-180, -90, 180, 90, w, h), compress="deflate", photometric="RGB")
        with rasterio.open(dst, "w", **prof) as d:
            d.write(arr.transpose(2, 0, 1))
            d.update_tags(DESCRIPTION=f"PALEOMAP PaleoAtlas map at {n} Ma (Scotese 2016), global equirectangular. Coordinates are those of its own time (paleo-coordinates), not present-day coordinates.", SOURCE="Scotese PaleoAtlas v3, EarthByte", NOT_A_SATELLITE_OBSERVATION="true")
        note("geotiff", dst)
        if n in EVIDENCE_AGES:
            cog = PROC / "COG" / f"paleomap_{n:03d}_cog.tif"
            cog.parent.mkdir(parents=True, exist_ok=True)
            rasterio.shutil.copy(dst, cog, driver="COG", compress="DEFLATE")
            note("cog", cog)


def netcdf() -> None:
    src = ORIG / "GPLATES/extracted/GeoData/Rasters/Seafloor_Age_Grid/Seton_etal_2020_PresentDay_AgeGrid.nc"
    ds = xr.open_dataset(src, engine="h5netcdf")
    sub = ds.sel(y=slice(-65, 35), x=slice(20, 120)).load()
    sub["z"].attrs.update(long_name="Present-day age of oceanic crust", units="Myr")
    sub.attrs = {
        "title": "Seafloor age, Indian Ocean subset (present day)",
        "source": "Seton et al. (2020) age grid from EarthByte / GPlates 2.5 GeoData (Zenodo 14194897)",
        "processing": "Spatial subset only (lat -65..35, lon 20..120); values unchanged",
        "note": "Observation-derived model product (magnetic isochrons and plate model); not a satellite observation of the past",
        "Conventions": "CF-1.7",
    }
    dst = PROC / "NETCDF" / "seton2020_present_day_seafloor_age_indian_ocean_subset.nc"
    dst.parent.mkdir(parents=True, exist_ok=True)
    sub.to_netcdf(dst, engine="h5netcdf")
    note("netcdf", dst)


# ------------------------------------------------------------------------------------------- 04 frames
def frames_folder() -> None:
    base = EVID / "04_RECONSTRUCTION_FRAMES"
    for a in EVIDENCE_AGES:
        k = f"{a:g}".replace(".", "p")
        dest = base / ("PRESENT" if a == 0 else f"{a}_Ma")
        for f in (DATA / "frames" / k).glob("*"):
            cp(f, dest / f.name)
        for suf in ("eb", "pm"):
            p = EVID / "05_VISUAL_PROOF" / "GLOBAL_RECONSTRUCTIONS" / f"recon_{k}_{suf}.png"
            if p.exists():
                cp(p, dest / p.name)
        pmf = DATA / "paleomap" / f"{int(a):03d}.jpg"
        if pmf.exists():
            cp(pmf, dest / f"paleomap_{int(a):03d}.jpg")
        note("frame_folder", dest)


def main() -> None:
    steps = [originals, geojson_frames, geopackages, shapefiles, gpml, geotiffs, netcdf, frames_folder]
    for s in steps:
        print(s.__name__, flush=True)
        s()
    (EVID / "07_VALIDATION").mkdir(parents=True, exist_ok=True)
    (EVID / "07_VALIDATION" / "_produced_files.json").write_text(json.dumps({k: len(v) for k, v in log.items()}, indent=2), encoding="utf-8")
    print({k: len(v) for k, v in log.items()})


if __name__ == "__main__":
    main()
