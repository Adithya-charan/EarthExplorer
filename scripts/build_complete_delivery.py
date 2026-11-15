"""Export every dataset used by NASAX into NASAX_COMPLETE_DATASET_DELIVERY/ (step 1 of 2; step 2 is finalize_delivery.py).

Sources are the real files in datasets/india_historical_atlas/. Originals are copied byte-for-byte and checked against the
SHA-256 in documentation/source_registry.json. Change-detection exports are produced by running the application's own
ChangeDetectionService, so gain/loss/unchanged/filtered masks are the exact arrays behind the numbers shown in the app.

    python scripts/build_complete_delivery.py            # output: $NASAX_DELIVERY_OUT (default F:/NASAX_DELIVERY_OUTPUT)
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image, ImageDraw
from pyproj import Geod
from rasterio.enums import Resampling
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from delivery_common import (ATLAS, BG, DIFF_COLORS, DOC, FONT, HATCH, OBS_COLORS, PKG, REGION_BBOX, REGION_DIR, REGION_NAME, ROOT, SMALL, class_legend, colorize_classes,  # noqa: E402
                             cp, fit, framed, jdump, line_chart, now_iso, raster_info, read_json, rel, sha256, write_cog, write_csv, write_geotiff_plain, datasets)

INDEX: dict[str, dict] = {}   # package-relative path -> facts about how/why the file exists
GEOD = Geod(ellps="WGS84")
ORIG_DIR = {"ghsl": "GHSL", "jrc": "JRC_GLOBAL_SURFACE_WATER", "esa": "ESA_WORLDCOVER", "geoboundaries": "GEOBOUNDARIES"}


def note(path: Path, **kw) -> None:
    INDEX[rel(path)] = kw


# ------------------------------------------------------------------------------------ originals
WORLDCOVER = {10: ((0, 100, 0), "Tree cover"), 20: ((255, 187, 34), "Shrubland"), 30: ((255, 255, 76), "Grassland"), 40: ((240, 150, 255), "Cropland"), 50: ((250, 0, 0), "Built-up"), 60: ((180, 180, 180), "Bare / sparse"),
              70: ((240, 240, 240), "Snow and ice"), 80: ((0, 100, 200), "Permanent water"), 90: ((0, 150, 160), "Herbaceous wetland"), 95: ((0, 207, 117), "Mangroves"), 100: ((250, 230, 160), "Moss and lichen")}
JRC_TRANS = {1: ((0, 0, 255), "Permanent"), 2: ((0, 200, 0), "New permanent"), 3: ((200, 0, 0), "Lost permanent"), 4: ((120, 120, 255), "Seasonal"), 5: ((120, 220, 120), "New seasonal"),
             6: ((230, 120, 120), "Lost seasonal"), 7: ((200, 200, 0), "Seasonal to permanent"), 8: ((200, 160, 0), "Permanent to seasonal"), 9: ((120, 80, 160), "Ephemeral permanent"), 10: ((160, 120, 200), "Ephemeral seasonal")}


def preview_original(path: Path, entry: dict, out: Path) -> None:
    region = (entry.get("used_by_regions") or [""])[0]
    title = f"ORIGINAL official file: {path.name}"
    sub = f"{entry['providing_organization']} · {entry['dataset_identifier']} · window of the file over {REGION_NAME.get(region, region)} (original is not modified)"
    if path.suffix == ".geojson":
        gdf = gpd.read_file(path)
        W, H = 760, 820
        west, south, east, north = 67.5, 6.0, 98.5, 37.5
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        for g in gdf.geometry:
            polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
            for p in polys:
                d.polygon([((x - west) / (east - west) * W, (north - y) / (north - south) * H) for x, y in p.exterior.coords], fill=(22, 40, 70), outline=(90, 130, 190))
        framed(im, title, sub, [((90, 130, 190), f"{len(gdf)} features, attributes: {', '.join(list(gdf.columns)[:5])}")]).save(out, optimize=True)
        return
    src = f"zip://{path}!/{[n for n in zipfile.ZipFile(path).namelist() if n.lower().endswith('.tif')][0]}" if path.suffix == ".zip" else str(path)
    with rasterio.open(src) as s:
        w, so, e, n = REGION_BBOX.get(region, tuple(s.bounds))
        win = rasterio.windows.from_bounds(w, so, e, n, s.transform).round_offsets().round_lengths()
        scale = min(1.0, 700 / max(win.width, win.height))
        a = s.read(1, window=win, out_shape=(max(1, int(win.height * scale)), max(1, int(win.width * scale))), resampling=Resampling.nearest)
        nd = s.nodata
        name = path.name.lower()
    rgb = np.zeros((*a.shape, 3), np.uint8)
    rgb[:] = BG
    legend: list = []
    if "ghs_built" in name:
        v = np.where(a == 65535, 0, a).astype(float)
        t = np.clip(v / max(1.0, np.percentile(v[v > 0], 98) if (v > 0).any() else 1), 0, 1)
        rgb[..., 0] = (30 + 225 * t).astype(np.uint8)
        rgb[..., 1] = (40 + 110 * t).astype(np.uint8)
        rgb[..., 2] = (60 - 40 * t).astype(np.uint8)
        legend = [((255, 150, 20), "built-up surface per cell (m2), brighter = more"), (BG, "no built-up / nodata 65535")]
    elif "occurrence" in name:
        t = np.clip(a.astype(float) / 100, 0, 1)
        rgb[..., 0] = (20 + 20 * (1 - t)).astype(np.uint8)
        rgb[..., 1] = (30 + 110 * t).astype(np.uint8)
        rgb[..., 2] = (50 + 205 * t).astype(np.uint8)
        legend = [((40, 140, 255), "water occurrence 1984-2021 (% of valid observations), brighter = more often water"), (BG, "never water / nodata")]
    elif "transitions" in name:
        for k, (c, _n) in JRC_TRANS.items():
            rgb[a == k] = c
        legend = [(c, nm) for c, nm in JRC_TRANS.values()]
    else:
        for k, (c, _n) in WORLDCOVER.items():
            rgb[a == k] = c
        present = set(np.unique(a).tolist())
        legend = [(c, f"{k} {nm}") for k, (c, nm) in WORLDCOVER.items() if k in present]
    framed(Image.fromarray(rgb), title, sub, legend, footer=f"{raster_info(src)['dimensions']} pixels in full file · CRS {raster_info(src)['crs']} · nodata {nd}").save(out, optimize=True)


def copy_originals() -> dict[str, dict]:
    reg = read_json(DOC / "source_registry.json")
    found = {}
    for e in reg["entries"]:
        if e["verification_status"] != "VERIFIED_DOWNLOADED":
            continue
        src = ROOT / e["local_path"]
        if not src.exists():
            found[e["id"]] = {"entry": e, "status": "MISSING", "path": None}
            continue
        sub = ORIG_DIR[next(k for k in ORIG_DIR if e["id"].startswith(k))]
        dst = cp(src, PKG / "01_ORIGINAL_OFFICIAL_DATA" / sub / src.name)
        ok = sha256(dst) == e["sha256"]
        found[e["id"]] = {"entry": e, "status": "RECOVERED" if ok else "CHECKSUM_MISMATCH", "path": dst}
        note(dst, kind="original", source_id=e["id"], dataset_id=e["id"], original_file=src.name, sha_matches_registry=ok, region=",".join(e.get("used_by_regions") or []))
        pv = PKG / "08_VISUAL_DATASETS/ORIGINAL_PREVIEWS" / f"{src.stem}.png"
        pv.parent.mkdir(parents=True, exist_ok=True)
        preview_original(src, e, pv)
        note(pv, kind="preview_original", source_id=e["id"])
        print(f"original {src.name}: {found[e['id']]['status']}")
    other = [{"id": e["id"], "provider": e.get("providing_organization"), "status": e["verification_status"], "official_url": e.get("official_dataset_url"), "note": e.get("verification_note"), "files_in_this_delivery": "none (no file was downloaded)"} for e in reg["entries"] if e["verification_status"] != "VERIFIED_DOWNLOADED"]
    jdump(PKG / "01_ORIGINAL_OFFICIAL_DATA/OTHER_VERIFIED_SOURCES/SOURCES_NOT_DOWNLOADED.json", {"note": "These sources are recorded but NO file was obtained. They are not part of any dataset used by the application.", "sources": other})
    return found


# --------------------------------------------------------------------------------------- rasters
def export_dataset_rasters(ds: dict) -> None:
    root: Path = ds["_dir"]
    reg = REGION_DIR[ds["_region"]]
    base = PKG / "02_PROCESSED_OFFICIAL_DATA" if ds["_official"] else PKG / "03_ILLUSTRATIVE_DEMONSTRATION_DATA" / reg
    for o in ds["observations"]:
        src = root / o["file"]
        tag = {"DATASET_ID": ds["id"], "DATA_LABEL": ds["public_label"], "SOURCE_ID": (o.get("provenance") or {}).get("source_id", "generated"), "OBSERVATION_DATE": o["date"]}
        stem = f"{ds['id']}__{o['date']}.tif"
        g = base / "GEOTIFF" / stem
        write_geotiff_plain(src, g, tag)
        c = base / "COG" / stem
        write_cog(g, c)
        common = dict(dataset_id=ds["id"], region=ds["_region"], date=o["date"], source_id=tag["SOURCE_ID"], official=ds["_official"], script="scripts/process_satellite_data.py" if ds["_official"] else "backend/app/explorer/atlas.py", app_file=str(src.relative_to(ROOT)).replace("\\", "/"))
        note(g, kind="processed_geotiff", **common)
        note(c, kind="processed_cog", **common)
    if ds["_official"]:
        return
    # Illustrative extras: the clean-truth scene behind each observation, the generator config, ground truth, terrain, zones.
    syn = ATLAS / "synthetic" / root.name
    for f in sorted((syn / "clean_truth").glob("*.tif")) if (syn / "clean_truth").exists() else []:
        d = cp(f, base / "CLEAN_TRUTH" / f"{ds['id']}__clean_truth_{f.stem}.tif")
        note(d, kind="illustrative_clean_truth", dataset_id=ds["id"], region=ds["_region"], official=False, script="backend/app/explorer/atlas.py")
    for n in ("generator_config.json",):
        if (syn / n).exists():
            note(cp(syn / n, base / "METADATA" / f"{ds['id']}__{n}"), kind="generator_config", dataset_id=ds["id"], region=ds["_region"], official=False)
    for n in ("ground_truth.json",):
        if (root / n).exists():
            note(cp(root / n, base / "METADATA" / f"{ds['id']}__{n}"), kind="ground_truth", dataset_id=ds["id"], region=ds["_region"], official=False)
    for sub in ("terrain", "zones"):
        for f in sorted((root / sub).glob("*.tif")) if (root / sub).exists() else []:
            d = cp(f, base / sub.upper() / f"{ds['id']}__{f.name}")
            note(d, kind=f"illustrative_{sub}", dataset_id=ds["id"], region=ds["_region"], official=False, script="backend/app/explorer/atlas.py")


def export_context_rasters() -> None:
    for f in sorted((ATLAS / "processed/official").rglob("context/*.tif")):
        region = f.parent.parent.name
        g = write_geotiff_plain(f, PKG / "02_PROCESSED_OFFICIAL_DATA/GEOTIFF" / f"context__{f.name}")  # noqa: F841
        gp = PKG / "02_PROCESSED_OFFICIAL_DATA/GEOTIFF" / f"context__{f.name}"
        cg = PKG / "02_PROCESSED_OFFICIAL_DATA/COG" / f"context__{f.name}"
        write_cog(gp, cg, "NEAREST")
        for p, k in ((gp, "processed_geotiff"), (cg, "processed_cog")):
            note(p, kind=k, dataset_id=f"context-{f.stem}", region=region, official=True, source_id="jrc_gsw_occurrence", script="scripts/process_satellite_data.py (build_occurrence)", app_file=str(f.relative_to(ROOT)).replace("\\", "/"))


# --------------------------------------------------------------------------------------- vectors
def stringify(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = gdf.copy()
    for c in g.columns:
        if c == "geometry":
            continue
        if g[c].map(lambda v: isinstance(v, (list, dict))).any():
            g[c] = g[c].map(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
    return g


def geod_area_km2(geom) -> float | None:
    if geom is None or geom.geom_type not in ("Polygon", "MultiPolygon"):
        return None
    return abs(GEOD.geometry_area_perimeter(geom)[0]) / 1e6


def vector_png(gdf: gpd.GeoDataFrame, out: Path, title: str, sub: str, color=(90, 150, 230)) -> None:
    minx, miny, maxx, maxy = gdf.total_bounds
    pad = max((maxx - minx), (maxy - miny)) * 0.03 + 1e-4
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    W = 900
    H = max(200, int(W * (maxy - miny) / (maxx - minx) * 1.0)) if (maxx - minx) else 400
    H = min(H, 1000)
    sc = min(W / (maxx - minx), H / (maxy - miny))
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    px = lambda x, y: ((x - minx) * sc, H - (y - miny) * sc)  # noqa: E731
    for g in gdf.geometry:
        if g is None:
            continue
        parts = list(g.geoms) if g.geom_type.startswith("Multi") else [g]
        for p in parts:
            if p.geom_type == "Polygon":
                d.polygon([px(x, y) for x, y in p.exterior.coords], fill=(22, 40, 70), outline=color)
            elif p.geom_type == "Point":
                x, y = px(p.x, p.y)
                d.ellipse([x - 4, y - 4, x + 4, y + 4], outline=color, width=2)
            elif p.geom_type == "LineString":
                d.line([px(x, y) for x, y in p.coords], fill=color, width=2)
    framed(im, title, sub, [(color, f"{len(gdf)} features · extent {minx:.2f},{miny:.2f} to {maxx:.2f},{maxy:.2f} (EPSG:4326)")]).save(out, optimize=True)


def export_vector(src: Path, folder: Path, name: str, title: str, meta: dict, index_kind: str, subset=None) -> None:
    gdf = gpd.read_file(src)
    if subset is not None:
        gdf = gdf[subset(gdf)].reset_index(drop=True)
    if gdf.empty:
        return
    folder.mkdir(parents=True, exist_ok=True)
    gj = folder / f"{name}.geojson"
    gdf.to_file(gj, driver="GeoJSON")
    flat = stringify(gdf)
    gp = folder / f"{name}.gpkg"
    if gp.exists():
        gp.unlink()
    flat.to_file(gp, driver="GPKG", layer=name)
    rows = []
    for _, r in flat.iterrows():
        g = r.geometry
        row = {k: r[k] for k in flat.columns if k != "geometry"}
        c = g.centroid if g is not None else None
        row.update({"centroid_lon": round(c.x, 6) if c is not None else "", "centroid_lat": round(c.y, 6) if c is not None else "", "geometry_type": g.geom_type if g is not None else "",
                    "area_km2_geodesic": round(geod_area_km2(g), 3) if geod_area_km2(g) is not None else "", "geometry_wkt": g.wkt if g is not None and len(g.wkt) <= 30000 else "(too long for CSV: see the GeoJSON or GeoPackage)"})
        rows.append(row)
    write_csv(folder / f"{name}.csv", rows)
    vector_png(gdf, folder / f"{name}.png", title, meta.get("source", ""))
    jdump(folder / f"{name}.metadata.json", {"name": name, "title": title, "feature_count": int(len(gdf)), "crs": "EPSG:4326", "attributes": [c for c in gdf.columns if c != "geometry"], "geometry_types": sorted(set(gdf.geometry.geom_type)), "bounds": [round(v, 6) for v in gdf.total_bounds], "generated_at": now_iso(), **meta})
    for ext, kind in (("geojson", "vector_geojson"), ("gpkg", "vector_gpkg"), ("csv", "vector_csv"), ("png", "preview_vector"), ("metadata.json", "vector_metadata")):
        note(folder / f"{name}.{ext}", kind=kind, dataset_id=meta["dataset_id"], official=meta.get("official", True), source_id=meta.get("source_id", ""), script=meta.get("script", ""), original_file=meta.get("original_file", ""), feature_count=int(len(gdf)))


def export_boundaries() -> None:
    gb = ATLAS / "geographical_boundaries"
    B = PKG / "04_GEOGRAPHICAL_BOUNDARIES"
    S = "scripts/build_geographical_boundaries.py"
    ad1 = "geoBoundaries-IND-ADM1_simplified.geojson"
    ad2 = "geoBoundaries-IND-ADM2_simplified.geojson"
    export_vector(gb / "states/india_states.geojson", B / "STATES", "india_states", "India states and union territories (geoBoundaries ADM1, simplified)", {"dataset_id": "boundaries-states", "source": "geoBoundaries gbOpen, simplified for display", "source_id": "geoboundaries_IND_ADM1", "original_file": ad1, "script": S, "license": "ODbL 1.0 (geoBoundaries gbOpen)"}, "states")
    export_vector(gb / "countries/india.geojson", B / "STATES", "india_country", "India (dissolved from the ADM1 states)", {"dataset_id": "boundaries-country", "source": "union of geoBoundaries ADM1 polygons", "source_id": "geoboundaries_IND_ADM1", "original_file": ad1, "script": S}, "country")
    export_vector(gb / "districts/india_districts.geojson", B / "DISTRICTS", "india_districts", "India districts (geoBoundaries ADM2, simplified)", {"dataset_id": "boundaries-districts", "source": "geoBoundaries gbOpen, simplified for display", "source_id": "geoboundaries_IND_ADM2", "original_file": ad2, "script": S, "license": "ODbL 1.0 (geoBoundaries gbOpen)"}, "districts")
    export_vector(gb / "cities/cities.geojson", B / "CITIES", "cities", "Cities: district outlines used as administrative proxies, or approximate ellipses (see boundary_status)", {"dataset_id": "boundaries-cities", "source": "district proxy / approximate area, NOT an authoritative city boundary", "official": False, "source_id": "geoboundaries_IND_ADM2", "script": S}, "cities")
    feats = gb / "geographical_features/features.geojson"
    for sub, name, lv in (("LAKES", "lakes", {"lake"}), ("RIVERS", "rivers_and_catchments", {"river"}), ("OTHER_FEATURES", "forest_island_glacier_mountain_coast", {"forest", "island", "glacier", "mountain", "coast"})):
        export_vector(feats, B / sub, name, f"Geographical features: {name.replace('_', ' ')}", {"dataset_id": f"boundaries-{name}", "source": "JRC water occurrence >= 10% (lakes), WorldCover (Sundarbans mangrove), otherwise approximate extents; see boundary_status per feature", "official": False, "source_id": "jrc_gsw_occurrence_70E_20N; esa_worldcover_2021_N21E087", "script": S}, "features", subset=lambda g, lv=lv: g["level"].isin(lv))
    export_vector(gb / "localities/localities.geojson", B / "OTHER_FEATURES", "localities_and_landmarks", "Localities and landmarks (approximate areas or points)", {"dataset_id": "boundaries-localities", "source": "approximate areas; not authoritative", "official": False, "script": S}, "localities")


# ----------------------------------------------------------------------------- change detection
def diff_png(diff: np.ndarray, out: Path, title: str, sub: str, vlab: str) -> None:
    rgb = np.zeros((*diff.shape, 3), np.uint8)
    rgb[:] = BG
    for code, c in DIFF_COLORS.items():
        rgb[diff == code] = c[:3]
    r, c = np.indices(diff.shape)
    rgb[(diff == 0) & (((r + c) % 6) < 2)] = HATCH[:3]
    legend = [((56, 139, 253), f"{vlab} unchanged"), ((230, 57, 70), f"{vlab} lost"), ((46, 204, 113), f"{vlab} gained"), ((122, 128, 140), "unchanged other"), ((205, 215, 232), "uncertain / no data (hatched)")]
    framed(fit(Image.fromarray(rgb)), title, sub, legend).save(out, optimize=True)


def before_after_png(w0, ok0, w1, ok1, out: Path, title: str, sub: str, vlab: str, y0, y1) -> None:
    def one(w, ok):
        rgb = np.zeros((*w.shape, 3), np.uint8)
        rgb[:] = (70, 76, 90)
        rgb[w & ok] = (56, 139, 253)
        r, c = np.indices(w.shape)
        rgb[(~ok) & (((r + c) % 6) < 2)] = HATCH[:3]
        return fit(Image.fromarray(rgb), 600)

    a, b = one(w0, ok0), one(w1, ok1)
    im = Image.new("RGB", (a.width + b.width + 12, a.height + 24), BG)
    im.paste(a, (0, 24))
    im.paste(b, (a.width + 12, 24))
    d = ImageDraw.Draw(im)
    d.text((6, 4), f"Before: {y0}", fill=(230, 238, 250), font=FONT)
    d.text((a.width + 18, 4), f"After: {y1}", fill=(230, 238, 250), font=FONT)
    framed(im, title, sub, [((56, 139, 253), f"{vlab} (composite state)"), ((70, 76, 90), "not " + vlab), ((205, 215, 232), "uncertain / no data (hatched)")]).save(out, optimize=True)


def export_changes() -> list[dict]:
    from app.config import Settings
    from app.explorer.change import AnalysisRecord
    from app.explorer.geoutil import area_ha
    from app.explorer.rendering import difference_geotiff
    from app.explorer.schemas import ChangeParams
    from app.explorer.services import ExplorerServices

    svc = ExplorerServices(Settings(explorer_dir=ATLAS / "processed", atlas_dir=ATLAS, explorer_generate_demo=False))
    meta_by_id = {d["id"]: d for d in datasets()}
    results = []
    for ds in svc.datasets.list():
        d = meta_by_id[ds.id]
        reg = REGION_DIR[d["_region"]]
        first, last = ds.observations[0].date.year, ds.observations[-1].date.year
        for v in ds.variables:
            rec = svc.changes.detect(ds, first, last, ChangeParams(variable=v["key"]), ds.meta.get("location", {}).get("name"))
            s = rec.summary if isinstance(rec, AnalysisRecord) else rec
            folder = PKG / "06_CHANGE_DETECTION" / reg / ds.id / f"{v['key']}_{first}_{last}"
            folder.mkdir(parents=True, exist_ok=True)
            label = d["public_label"]
            common = dict(dataset_id=ds.id, region=d["_region"], variable=v["key"], official=d["_official"], script="scripts/build_complete_delivery.py via backend/app/explorer/change.py", analysis_id=s.analysis_id)
            jdump(folder / "metadata.json", {"dataset_id": ds.id, "label": label, "variable": v, "period": [first, last], "summary": s.model_dump(), "generated_at": now_iso(),
                                             "how": "Outputs of ChangeDetectionService.detect(): same-season composites at both ends, geodesic per-row pixel areas, positional-noise filter min_feature_px=" + str(ds.meta.get("min_feature_px", 3)) + ". Rasters below are the exact arrays used.",
                                             "raster_codes": {"state": "1 = class present, 0 = class absent, 255 = no data / uncertain", "change_classification": "0 uncertain, 1 unchanged other, 2 unchanged class, 3 lost, 4 gained", "masks": "1 = member, 0 = not, 255 = no data"}})
            note(folder / "metadata.json", kind="change_metadata", **common)
            if not isinstance(rec, AnalysisRecord):
                results.append({"dataset_id": ds.id, "variable": v["key"], "folder": rel(folder), "outcome": s.outcome, "note": "insufficient data: no rasters are produced and no zero is reported"})
                continue
            diff, w0, ok0, w1, ok1 = rec.diff, rec.w0, rec.ok0, rec.w1, rec.ok1
            valid = ok0 & ok1
            masks = {"initial_state": np.where(ok0, w0, 255), "final_state": np.where(ok1, w1, 255), "change_classification": diff, "gain_mask": np.where(valid, (diff == 4), 255), "loss_mask": np.where(valid, (diff == 3), 255),
                     "unchanged_mask": np.where(valid, ((diff == 1) | (diff == 2)), 255), "filtered_mask": np.where(valid, (((w0 & ~w1) | (~w0 & w1)) & ~((diff == 3) | (diff == 4))), 255), "uncertain_mask": (diff == 0)}
            tags = {"DATASET": ds.id, "VARIABLE": v["key"], "DATA_LABEL": label, "PERIOD": f"{first}-{last}"}
            for k, arr in masks.items():
                p = folder / f"{k}.tif"
                p.write_bytes(difference_geotiff(ds, arr.astype(np.uint8), tags | {"LAYER": k}))
                note(p, kind=f"change_{k}", **common)
            write_cog(folder / "change_classification.tif", folder / "change_classification_cog.tif")
            note(folder / "change_classification_cog.tif", kind="change_cog", **common)
            fc = rec.hotspot_geojson
            jdump(folder / "hotspots.geojson", fc)
            note(folder / "hotspots.geojson", kind="change_hotspots_geojson", **common)
            if fc["features"]:
                g = stringify(gpd.GeoDataFrame.from_features(fc["features"], crs="EPSG:4326"))
                g.to_file(folder / "hotspots.gpkg", driver="GPKG", layer="hotspots")
                note(folder / "hotspots.gpkg", kind="change_hotspots_gpkg", **common)
            a = s.areas
            stats = [{"quantity": k, "value": a.get(k), "unit": "ha" if k.endswith("_ha") else ("%" if "pct" in k else "")} for k in a]
            stats += [{"quantity": f"progression_{p.year}", "value": p.water_ha, "unit": f"ha of {v['label']}"} for p in s.progression]
            write_csv(folder / "statistics.csv", stats)
            note(folder / "statistics.csv", kind="change_statistics", **common)
            title = f"{d['name']}: change in {v['label']} {first}-{last}"
            sub = f"{label} · {s.outcome} · net {a.get('net_ha'):+,.0f} ha" if isinstance(a.get("net_ha"), (int, float)) else f"{label} · {s.outcome}"
            diff_png(diff, folder / "difference_map.png", title, sub, v["label"])
            before_after_png(w0, ok0, w1, ok1, folder / "before_after.png", title + " (before and after)", sub, v["label"], first, last)
            note(folder / "difference_map.png", kind="preview_change", **common)
            note(folder / "before_after.png", kind="preview_before_after", **common)
            blocks = [("h", "Result"), ("p", s.headline), ("table", [["Quantity", "Value"]] + [[r["quantity"], r["value"]] for r in stats[:16]], [260, 200]), ("img", str(folder / "difference_map.png"), 420, "Change classification"), ("img", str(folder / "before_after.png"), 300, "Composite state before and after"),
                      ("h", "Limitations"), *[("small", t) for t in s.limitations]]
            from delivery_common import simple_pdf

            simple_pdf(folder / "analysis_report.pdf", f"Change analysis: {title}", blocks)
            note(folder / "analysis_report.pdf", kind="change_report", **common)
            results.append({"dataset_id": ds.id, "variable": v["key"], "folder": rel(folder), "outcome": s.outcome, "analysis_id": s.analysis_id, "areas": a})
            print(f"change {ds.id} {v['key']} {s.outcome}")
    jdump(PKG / "06_CHANGE_DETECTION/change_index.json", results)
    return results


# ----------------------------------------------------------------- observations and statistics
def export_observations_and_stats() -> None:
    prev = ATLAS / "previews"
    allseries: dict[str, dict] = {}
    for d in datasets():
        root: Path = d["_dir"]
        reg = REGION_DIR[d["_region"]]
        obs_dir = PKG / "05_HISTORICAL_OBSERVATIONS" / reg / d["id"]
        rows = [{"date": o["date"], "quality": o.get("quality"), "valid_fraction": o.get("valid_fraction"), "sensor_or_origin": o.get("sensor"), "source_id": (o.get("provenance") or {}).get("source_id", "generated"), "raster_file_in_package": f"{'02_PROCESSED_OFFICIAL_DATA' if d['_official'] else '03_ILLUSTRATIVE_DEMONSTRATION_DATA/' + reg}/COG/{d['id']}__{o['date']}.tif",
                 **{f"area_ha[{k}]": v for k, v in (o.get("class_area_ha") or {}).items()}} for o in d["observations"]]
        fields = sorted({k for r in rows for k in r}, key=lambda k: (k.startswith("area_ha"), k))
        write_csv(obs_dir / "observations.csv", rows, fields)
        jdump(obs_dir / "dataset_metadata.json", {k: v for k, v in d.items() if not k.startswith("_")})
        note(obs_dir / "observations.csv", kind="observation_index", dataset_id=d["id"], region=d["_region"], official=d["_official"])
        note(obs_dir / "dataset_metadata.json", kind="dataset_metadata", dataset_id=d["id"], region=d["_region"], official=d["_official"])
        for f in sorted((prev / d["id"]).glob("observation_*.png")):
            note(cp(f, obs_dir / f.name), kind="preview_observation", dataset_id=d["id"], region=d["_region"], official=d["_official"])
            note(cp(f, PKG / "08_VISUAL_DATASETS/PROCESSED_PREVIEWS" / f"{d['id']}__{f.name}"), kind="preview_observation", dataset_id=d["id"], region=d["_region"], official=d["_official"])
        for f in (prev / d["id"]).glob("before_after.png"):
            note(cp(f, PKG / "08_VISUAL_DATASETS/BEFORE_AFTER" / f"{d['id']}__first_vs_last_observation.png"), kind="preview_before_after", dataset_id=d["id"], region=d["_region"], official=d["_official"])
        # legend
        lg = Image.new("RGB", (420, 30 + 22 * (len(d["classes"]) + 1)), BG)
        dr = ImageDraw.Draw(lg)
        dr.text((8, 6), f"{d['name']}: legend ({d['public_label']})", fill=(230, 238, 250), font=SMALL)
        for i, (k, nm) in enumerate(d["classes"].items()):
            c = OBS_COLORS.get(int(k), (205, 215, 232))[:3]
            dr.rectangle([10, 30 + 22 * i, 24, 44 + 22 * i], fill=c)
            dr.text((32, 30 + 22 * i), f"{k}  {nm}", fill=(200, 212, 230), font=SMALL)
        lp = PKG / "08_VISUAL_DATASETS/LEGENDS" / f"{d['id']}__legend.png"
        lp.parent.mkdir(parents=True, exist_ok=True)
        lg.save(lp)
        note(lp, kind="legend", dataset_id=d["id"], region=d["_region"], official=d["_official"])
        # statistics
        st = root / "historical_statistics.json"
        if st.exists():
            s = read_json(st)
            note(cp(st, PKG / "07_STATISTICS_AND_ANALYSIS/JSON" / f"{d['id']}__historical_statistics.json"), kind="statistics_json", dataset_id=d["id"], region=d["_region"], official=d["_official"], script="scripts/calculate_historical_statistics.py (backend/app/explorer/stats.py)")
            note(cp(root / "historical_statistics.csv", PKG / "07_STATISTICS_AND_ANALYSIS/CSV" / f"{d['id']}__historical_statistics.csv"), kind="statistics_csv", dataset_id=d["id"], region=d["_region"], official=d["_official"], script="scripts/calculate_historical_statistics.py")
            ser = {v["label"]: [(p["date"], p["area_ha"]) for p in v["series"]] for v in s["variables"].values()}
            if any(len(x) > 1 for x in ser.values()):
                # one chart per group of comparable magnitude would hide small classes, so draw each variable on its own chart
                for key, v in s["variables"].items():
                    pts = [(p["date"], p["area_ha"]) for p in v["series"]]
                    if len(pts) < 2:
                        continue
                    ch = line_chart({v["label"]: pts}, f"{d['name']}: {v['label']}", "area (hectares)", f"{d['public_label']} · values measured from the processed rasters (geodesic areas)")
                    cp_ = PKG / "07_STATISTICS_AND_ANALYSIS/CHARTS" / f"{d['id']}__{key}.png"
                    cp_.parent.mkdir(parents=True, exist_ok=True)
                    ch.save(cp_)
                    note(cp_, kind="statistics_chart", dataset_id=d["id"], region=d["_region"], official=d["_official"])
            allseries[d["id"]] = s
    for n in ("change_summary.csv", "change_summary.json", "historical_statistics.csv"):
        note(cp(DOC / n, PKG / "07_STATISTICS_AND_ANALYSIS" / ("CSV" if n.endswith("csv") else "JSON") / n), kind="statistics_combined", dataset_id="all", official=None)
    for f in (prev).glob("india_overview.png"):
        note(cp(f, PKG / "08_VISUAL_DATASETS/PROCESSED_PREVIEWS/india_overview.png"), kind="preview_overview", dataset_id="all")
    for f in sorted((ROOT / "NASAX_JUDGE_EVIDENCE/07_APPLICATION_DEMO/screenshots").glob("*.jpg")):
        note(cp(f, PKG / "08_VISUAL_DATASETS/APPLICATION_SCREENSHOTS" / f.name), kind="screenshot", dataset_id="application")


def main() -> None:
    if PKG.exists():
        shutil.rmtree(PKG)
    PKG.mkdir(parents=True)
    orig = copy_originals()
    for d in datasets():
        export_dataset_rasters(d)
        print("rasters", d["id"])
    export_context_rasters()
    export_boundaries()
    export_observations_and_stats()
    changes = export_changes()
    jdump(PKG.parent / "_file_index.json", INDEX)
    jdump(PKG.parent / "_originals.json", {k: {"status": v["status"], "path": rel(v["path"]) if v["path"] else None, "entry": v["entry"]} for k, v in orig.items()})
    jdump(PKG.parent / "_changes.json", changes)
    print(f"build done: {len(INDEX)} indexed files")


if __name__ == "__main__":
    main()
