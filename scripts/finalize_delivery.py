"""Finish NASAX_COMPLETE_DATASET_DELIVERY/ (step 2 of 2): inventory, processing register, application mapping, validation, PDFs, archives.

Run after build_complete_delivery.py:   python scripts/finalize_delivery.py
Everything is read from the files in the package and the project; no value is typed in by hand.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))
from delivery_common import (ATLAS, DOC, OUT_ROOT, PKG, REGION_DIR, REGION_NAME, ROOT, approx_res_m, datasets, jdump, now_iso, raster_info, read_json, rel, sha256, simple_pdf, write_csv)  # noqa: E402

INDEX: dict[str, dict] = read_json(OUT_ROOT / "_file_index.json")
ORIG: dict = read_json(OUT_ROOT / "_originals.json")
CHANGES: list[dict] = read_json(OUT_ROOT / "_changes.json")
REG = {e["id"]: e for e in read_json(DOC / "source_registry.json")["entries"]}
DS = {d["id"]: d for d in datasets()}
RASTER_EXT = {".tif", ".tiff"}
VECTOR_EXT = {".gpkg", ".geojson"}


def line_of(path: str, pattern: str) -> str:
    """The real line number of a code construct, so the mapping cites the repository and not memory."""
    p = ROOT / path
    for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(pattern, ln):
            return f"{path}:{i}"
    return f"{path}:(not found)"


CODE = {
    "obs_layer": line_of("backend/app/routers/explorer.py", r'"/datasets/\{dataset_id\}/observations/\{iso\}/layer\.png"'),
    "analysis_layer": line_of("backend/app/routers/explorer.py", r'"/analysis/\{analysis_id\}/layers/\{name\}"'),
    "hotspots": line_of("backend/app/routers/explorer.py", r'"/analysis/\{analysis_id\}/hotspots"'),
    "boundary": line_of("backend/app/routers/explorer.py", r'"/locations/\{location_id:path\}/boundary"'),
    "stats": line_of("backend/app/routers/explorer.py", r'"/datasets/\{dataset_id\}/statistics"'),
    "detect": line_of("backend/app/routers/explorer.py", r'"/analysis/detect-change"'),
    "plan": line_of("frontend/src/lib/explorer/logic.ts", r"export function planLayers"),
    "loader": line_of("backend/app/explorer/datasets.py", r"rglob"),
}


def region_of_path(p: str) -> str:
    for k, v in REGION_DIR.items():
        if f"/{v}/" in p or f"/{v.lower()}/" in p:
            return k
    return ""


# -------------------------------------------------------------------------------------- inventory
def usage_for(kind: str, dsid: str, date: str = "") -> str:
    d = DS.get(dsid)
    if kind in ("processed_cog", "processed_geotiff"):
        if kind == "processed_geotiff":
            return "Plain GeoTIFF copy for inspection; the application loads the COG-layout file in processed/ (same values)."
        return f"LOADED by the application (backend/app/explorer/datasets.py rglob of dataset.json) and rendered by GET /api/explorer/datasets/{dsid}/observations/{date}/layer.png; used in latest, history, before/after and swipe modes and as input to change detection."
    if kind.startswith("change_") and kind != "change_hotspots_geojson":
        return "Exact array produced by ChangeDetectionService for this analysis; difference.png/difference.tif are served by GET /api/explorer/analysis/{id}/layers/{name}."
    if kind == "change_hotspots_geojson":
        return "Served by GET /api/explorer/analysis/{id}/hotspots and drawn as hotspot polygons on the globe."
    if kind == "original":
        return "Input to processing only. Not loaded by the running application."
    if kind.startswith("vector_"):
        return "Place boundary: read by the gazetteer (backend/app/explorer/gazetteer.py) and returned by GET /api/explorer/locations/{id}/boundary; drawn on the globe (solid cyan if authoritative, dashed amber if approximate)."
    if kind in ("illustrative_zones",):
        return "LOADED by backend/app/explorer/stats.py to split lake-basin and surroundings statistics."
    if kind in ("illustrative_clean_truth", "illustrative_terrain", "generator_config", "ground_truth"):
        return "Not loaded by the running application; kept to show how the Illustrative Dataset was generated."
    return ""


def build_inventory() -> list[dict]:
    rows = []
    n = 0
    prov_by = {}
    for d in DS.values():
        for o in d["observations"]:
            prov_by[(d["id"], o["date"])] = o.get("provenance") or {}
    for p in sorted(PKG.rglob("*")):
        if not p.is_file():
            continue
        r = rel(p)
        meta = INDEX.get(r, {})
        kind = meta.get("kind", "")
        if p.suffix.lower() not in RASTER_EXT | VECTOR_EXT and not (kind == "original" and p.suffix.lower() == ".zip") and not kind.startswith("official_export_"):
            continue
        if kind in ("preview_original",):
            continue
        n += 1
        dsid = meta.get("dataset_id", "")
        d = DS.get(dsid)
        is_raster = p.suffix.lower() in RASTER_EXT or kind == "original" and p.suffix.lower() in RASTER_EXT
        row = {"File ID": f"NASAX-F{n:04d}", "Dataset ID": dsid, "Dataset name": d["name"] if d else (REG.get(dsid, {}).get("variable") or dsid), "Region": REGION_NAME.get(meta.get("region", ""), meta.get("region", ""))}
        date = meta.get("date", "")
        prov = prov_by.get((dsid, date), {})
        src_id = meta.get("source_id") or prov.get("source_id", "")
        reg = REG.get(src_id, {})
        row.update({
            "Provider": (d["source"] if d else "") or reg.get("providing_organization", ""), "Source collection": prov.get("dataset_identifier") or reg.get("dataset_identifier", ""), "Geography": REGION_NAME.get(meta.get("region", ""), ""),
            "Observation year": date[:4], "Observation date": date, "Original filename": meta.get("original_file") or prov.get("original_file", "") or (reg.get("original_file_name", "") if kind == "original" else ""),
            "Original format": (reg.get("original_file_format", "") if reg else ""), "Processed filename": "" if kind == "original" else p.name, "Processed format": "" if kind == "original" else p.suffix.lstrip(".").upper(),
        })
        if p.suffix.lower() in RASTER_EXT:
            try:
                info = raster_info(p)
                row.update({"Spatial resolution": approx_res_m(info), "CRS": info["crs"], "Dimensions": info["dimensions"], "Number of bands": info["bands"], "Data type": info["dtype"], "NoData value": info["nodata"]})
            except Exception as exc:  # noqa: BLE001
                row["Spatial resolution"] = f"unreadable: {exc}"
        elif p.suffix.lower() in VECTOR_EXT:
            row.update({"CRS": "EPSG:4326", "Dimensions": f"{meta.get('feature_count', '')} features", "Spatial resolution": "vector", "Number of bands": "", "Data type": "vector", "NoData value": ""})
        row.update({
            "Application usage": usage_for(kind, dsid, date), "Processing script": meta.get("script", ""), "Processing method": ("; ".join((prov.get("processing_operations") or []))) or (d["provenance"].get("processing", "") if d and not d["_official"] else ""),
            "Source status": reg.get("verification_status", "ILLUSTRATIVE (generated, no external source)" if (d and not d["_official"]) else ("DERIVED" if meta.get("official") else "")), "SHA-256 checksum": sha256(p),
            "Local file path": f"{p}", "Package path": r, "File kind": kind,
        })
        if kind == "original":
            row["Original filename"] = p.name
            row["Source status"] = ORIG.get(src_id, {}).get("status", "")
        rows.append(row)
    return rows


# -------------------------------------------------------------------------- processing register
def processing_register() -> list[dict]:
    rows = []
    for d in DS.values():
        root: Path = d["_dir"]
        pipe = read_json(root / "pipeline.json", {})
        steps = pipe.get("steps", [])
        o0 = d["observations"][0]
        prov = o0.get("provenance") or {}
        reg = REG.get(prov.get("source_id", ""), {})
        stats_csv = f"07_STATISTICS_AND_ANALYSIS/CSV/{d['id']}__historical_statistics.csv"
        changes = [c for c in CHANGES if c["dataset_id"] == d["id"]]
        clip = sorted({json.dumps(s.get("clip")) for s in steps if s.get("clip")})
        is_off = d["_official"]
        if is_off:
            row = {"Dataset ID": d["id"], "Dataset": d["name"], "Designation": "official_derived (Satellite Observations)", "Region": REGION_NAME[d["_region"]], "Original source": reg.get("providing_organization", ""), "Source product": reg.get("dataset_identifier", ""),
                   "Original files": "; ".join(sorted({(o.get("provenance") or {}).get("original_file", "") for o in d["observations"]})), "Original resolution": f"{prov.get('original_resolution_deg')} deg", "Original CRS": prov.get("original_crs", ""),
                   "Clipping": f"pixel windows (col, row, width, height): {', '.join(clip)}; analysis window bbox {d['bbox']}", "Reprojection": "; ".join(sorted({str(s.get('crs')) for s in steps if s.get('crs')})) or "none recorded", "Alignment": "; ".join(sorted({str(s.get('align')) for s in steps if s.get('align')})),
                   "Classification": "; ".join(sorted({str(s.get('classify')) for s in steps if s.get('classify')})), "Operations recorded": "; ".join(prov.get("processing_operations") or []), "Processing code": f"scripts/process_satellite_data.py ({'build_ghsl' if 'ghsl' in d['id'] else 'build_jrc_transitions' if 'jrc' in d['id'] else 'build_worldcover'})",
                   "Output files": f"{len(d['observations'])} COG observations: " + ", ".join(o["file"] for o in d["observations"]), "Statistics": stats_csv,
                   "Change detection": "; ".join(f"{c['variable']}: {c['outcome']}" for c in changes) or "none", "Limitation": prov.get("limitation") or prov.get("note", ""), "Date semantics": prov.get("date_semantics", d["provenance"].get("note", ""))}
        else:
            cfg = read_json(ATLAS / "synthetic" / root.name / "generator_config.json", {})
            row = {"Dataset ID": d["id"], "Dataset": d["name"], "Designation": "illustrative (Illustrative Dataset, generated)", "Region": REGION_NAME[d["_region"]], "Original source": "none: generated demonstration layer, not satellite imagery", "Source product": "backend/app/explorer/atlas.py",
                   "Original files": "none", "Original resolution": f"{cfg.get('res_deg')} deg (generator setting)", "Original CRS": "EPSG:4326", "Clipping": f"generated directly on bbox {cfg.get('bbox')}", "Reprojection": "none", "Alignment": "single generated grid",
                   "Classification": "class codes assigned by the generator rules: " + " | ".join(cfg.get("rules", [])), "Operations recorded": f"seed {cfg.get('seed')}; years {cfg.get('years')}; per-year cloud/no-data fractions in generator_config.json; clean truth degraded into the observation",
                   "Processing code": "backend/app/explorer/atlas.py", "Output files": f"{len(d['observations'])} COG observations", "Statistics": stats_csv, "Change detection": "; ".join(f"{c['variable']}: {c['outcome']}" for c in changes) or "none", "Limitation": d.get("simulated_label", ""), "Date semantics": "years chosen by the generator; not acquisition dates of any satellite"}
        row["Application integration"] = f"dataset.json + observations/*.tif loaded from datasets/india_historical_atlas/processed ({CODE['loader']}); layers via {CODE['obs_layer']}; change layers via {CODE['analysis_layer']}; frontend {CODE['plan']}"
        rows.append(row)
    for name, how in (("boundaries-states / districts", "geoBoundaries ADM1/ADM2 original GeoJSON copied unchanged to 01_ORIGINAL_OFFICIAL_DATA/GEOBOUNDARIES; scripts/build_geographical_boundaries.py rounds coordinates to 4 decimals, repairs invalid rings with buffer(0), adds ids, hierarchy and boundary_status."),
                      ("boundaries-lakes", "Lake outlines are polygons of JRC water occurrence >= 10% (rasterio.features.shapes) clipped to a window around each lake; Himayat Sagar had no usable pixels and is an approximate point."),
                      ("boundaries-Sundarbans mangrove", "WorldCover class 95 (mangrove) polygons clipped to the West Bengal state outline."),
                      ("boundaries-cities/localities", "Approximate ellipses or district proxies; never presented as authoritative.")):
        rows.append({"Dataset ID": name.split(" ")[0], "Dataset": name, "Designation": "boundary", "Region": "India", "Processing code": "scripts/build_geographical_boundaries.py", "Operations recorded": how, "Application integration": f"gazetteer + {CODE['boundary']}"})
    return rows


# ----------------------------------------------------------------------------------- app mapping
def app_mapping() -> list[dict]:
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    client = TestClient(create_app(Settings(upload_dir=OUT_ROOT / "_uploads", explorer_dir=ATLAS / "processed", atlas_dir=ATLAS, explorer_generate_demo=False, groq_api_key=None)))
    rows = []
    for d in DS.values():
        reg = REGION_DIR[d["_region"]]
        base = "02_PROCESSED_OFFICIAL_DATA" if d["_official"] else f"03_ILLUSTRATIVE_DEMONSTRATION_DATA/{reg}"
        for o in d["observations"]:
            ep = f"/api/explorer/datasets/{d['id']}/observations/{o['date']}/layer.png"
            r = client.get(ep)
            primary = [v["label"] for v in d["variables"] if v.get("primary")]
            rows.append({"UI layer name": f"{d['name']} · {o['date'][:4]} ({d['public_label']})", "Region": REGION_NAME[d["_region"]], "Measure type": "land-cover classes (" + ", ".join(v["label"] for v in d["variables"]) + ")", "Observation date": o["date"], "Backend endpoint": f"GET {ep}",
                         "HTTP status when exercised": r.status_code, "Dataset ID": d["id"], "Original source ID": (o.get("provenance") or {}).get("source_id", "none (generated)"), "Processed file": f"{base}/COG/{d['id']}__{o['date']}.tif", "Application file": f"datasets/india_historical_atlas/processed/{rel(d['_dir'] / o['file'], ATLAS / 'processed')}",
                         "File format": "COG (GeoTIFF)", "Analysis function": f"rendering.observation_png ({CODE['obs_layer']})", "Statistics file": f"07_STATISTICS_AND_ANALYSIS/CSV/{d['id']}__historical_statistics.csv", "Display mode": f"map modes latest/history/before-after/swipe via {CODE['plan']}; primary measure {primary}"})
    for c in CHANGES:
        d = DS[c["dataset_id"]]
        base = f"06_CHANGE_DETECTION/{REGION_DIR[d['_region']]}/{d['id']}/{c['variable']}_{c['folder'].rsplit('_', 2)[-2]}_{c['folder'].rsplit('_', 1)[-1]}"
        aid = c.get("analysis_id")
        status = ""
        if aid and c["variable"] == next(v["key"] for v in d["variables"] if v.get("primary")):
            y0, y1 = (int(x) for x in c["folder"].rsplit("_", 2)[-2:])
            dr = client.post("/api/explorer/analysis/detect-change", json={"dataset_id": d["id"], "start_year": y0, "end_year": y1, "params": {"variable": c["variable"]}})
            live = dr.json().get("analysis_id") if dr.status_code == 200 else None
            status = f"detect-change {dr.status_code}"
            if live:
                aid = live
                fc = client.get(f"/api/explorer/analysis/{aid}/hotspots")
                lr = client.get(f"/api/explorer/analysis/{aid}/layers/difference.png")
                status += f"; hotspots {fc.status_code}; difference.png {lr.status_code}"
        rows.append({"UI layer name": f"{d['name']} · change in {c['variable']} ({d['public_label']})", "Region": REGION_NAME[d["_region"]], "Measure type": c["variable"], "Observation date": c["folder"].rsplit("/", 1)[-1], "Backend endpoint": f"POST /api/explorer/analysis/detect-change then GET /api/explorer/analysis/{aid}/layers/difference.png and /hotspots" if aid else "POST /api/explorer/analysis/detect-change (insufficient data, no layer)",
                     "HTTP status when exercised": status or "not exercised for non-primary variables (same code path)", "Dataset ID": d["id"], "Original source ID": (d["observations"][0].get("provenance") or {}).get("source_id", "none (generated)"), "Processed file": f"{base}/change_classification_cog.tif" if aid else "", "Application file": "computed in memory from the observation COGs; not stored by the app",
                     "File format": "COG (GeoTIFF) + GeoJSON hotspots", "Analysis function": f"ChangeDetectionService.detect ({CODE['detect']})", "Statistics file": f"{base}/statistics.csv", "Display mode": f"difference / hotspots map modes ({CODE['plan']})"})
    for cat, src in (("states", "04_GEOGRAPHICAL_BOUNDARIES/STATES/india_states.geojson"), ("districts", "04_GEOGRAPHICAL_BOUNDARIES/DISTRICTS/india_districts.geojson"), ("cities", "04_GEOGRAPHICAL_BOUNDARIES/CITIES/cities.geojson"), ("lakes", "04_GEOGRAPHICAL_BOUNDARIES/LAKES/lakes.geojson"), ("rivers", "04_GEOGRAPHICAL_BOUNDARIES/RIVERS/rivers_and_catchments.geojson"),
                     ("other features", "04_GEOGRAPHICAL_BOUNDARIES/OTHER_FEATURES/forest_island_glacier_mountain_coast.geojson"), ("localities", "04_GEOGRAPHICAL_BOUNDARIES/OTHER_FEATURES/localities_and_landmarks.geojson")):
        rows.append({"UI layer name": f"Place outline: {cat}", "Region": "India", "Measure type": "boundary", "Observation date": "", "Backend endpoint": "GET /api/explorer/locations/{id}/boundary", "HTTP status when exercised": "see tests/test_atlas.py::test_boundaries_are_real_or_honestly_approximate", "Dataset ID": f"boundaries-{cat.split()[0]}", "Original source ID": "geoboundaries_IND_ADM1/ADM2 or derived (see metadata)",
                     "Processed file": src, "Application file": f"datasets/india_historical_atlas/geographical_boundaries/{src.split('/')[-1]}", "File format": "GeoJSON", "Analysis function": f"AtlasGazetteer.boundary ({CODE['boundary']})", "Statistics file": "", "Display mode": "globe outline: solid if authoritative, dashed amber if approximate"})
    return rows


# --------------------------------------------------------------------------------------- validation
def validate() -> tuple[list[dict], list[dict]]:
    from app.explorer.geoutil import area_ha, pixel_area_m2_per_row

    checks: list[dict] = []

    def ck(scope, name, ok, detail="", warn=False):
        checks.append({"scope": scope, "check": name, "status": "pass" if ok else ("warn" if warn else "fail"), "detail": str(detail)})

    integrity = []
    seen: dict[str, str] = {}
    for p in sorted(PKG.rglob("*")):
        if not p.is_file():
            continue
        r = rel(p)
        sha = sha256(p)
        meta = INDEX.get(r, {})
        status = "listed"
        if p.suffix.lower() in RASTER_EXT:
            sc = r
            try:
                i = raster_info(p)
                ok = i["width"] > 0 and i["height"] > 0 and bool(i["crs"]) and i["bands"] >= 1
                ck(sc, "raster opens, CRS valid, dimensions valid", ok, f"{i['crs']} {i['dimensions']} bands={i['bands']} nodata={i['nodata']}")
                with rasterio.open(p) as s:
                    a = s.read(1, out_shape=(min(s.height, 600), min(s.width, 600)))
                    allnd = s.nodata is not None and bool(np.all(a == s.nodata))
                ck(sc, "raster contains valid (non-nodata) values", not allnd, f"dtype {i['dtype']}", warn=meta.get("kind", "").startswith("change_") and allnd)
                ck(sc, "georeferencing preserved (bounds in plausible range)", -180 <= i["bounds"][0] < i["bounds"][2] <= 180 and -90 <= i["bounds"][1] < i["bounds"][3] <= 90)
                if meta.get("kind") in ("processed_cog", "change_cog") or r.endswith("_cog.tif"):
                    ck(sc, "COG: LAYOUT=COG, tiled, compressed", i["layout"] == "COG" and i["tiled"] and bool(i["compression"]), f"layout={i['layout']} tiled={i['tiled']} compression={i['compression']}")
                    ck(sc, "COG: has overviews or is smaller than one block", bool(i["overviews"]) or max(i["width"], i["height"]) <= 512, f"overviews {i['overviews']}")
                status = "raster ok"
            except Exception as exc:  # noqa: BLE001
                ck(sc, "raster opens", False, exc)
                status = "FAILED"
        elif p.suffix.lower() in VECTOR_EXT and meta.get("kind", "").startswith(("vector", "change_hotspots")):
            sc = r
            try:
                g = gpd.read_file(p)
                ck(sc, "vector opens, CRS valid", g.crs is not None and g.crs.to_epsg() == 4326, f"{g.crs} features={len(g)}")
                ck(sc, "geometries valid and non-empty", bool(len(g) == 0 or (g.geometry.is_valid.all() and (~g.geometry.is_empty).all())), f"{int((~g.geometry.is_valid).sum())} invalid")
                if len(g):
                    b = g.total_bounds
                    ck(sc, "coordinates inside India's expected extent", 60 <= b[0] and b[2] <= 100 and 5 <= b[1] and b[3] <= 40, [round(v, 3) for v in b])
                if "boundaries" in r.lower() or "04_GEO" in r:
                    ck(sc, "required attributes present (id, name, boundary_status)", all(c in g.columns for c in ("id", "name", "boundary_status")), list(g.columns)[:8])
                status = "vector ok"
            except Exception as exc:  # noqa: BLE001
                ck(sc, "vector opens", False, exc)
                status = "FAILED"
        if sha in seen and p.suffix.lower() in RASTER_EXT | VECTOR_EXT and meta.get("kind") not in ("processed_geotiff",) and not meta.get("kind", "").startswith("official_export_"):
            ck("integrity", f"no duplicate file contents: {r}", False, f"identical to {seen[sha]}", warn=True)
        seen.setdefault(sha, r)
        integrity.append({"file": r, "bytes": p.stat().st_size, "sha256": sha, "kind": meta.get("kind", ""), "validation": status})
    # originals
    for sid, o in ORIG.items():
        ck("originals", f"{sid}: recovered and checksum equals the registry", o["status"] == "RECOVERED", o["status"])
        src = ROOT / o["entry"]["local_path"]
        if o["path"]:
            ck("originals", f"{sid}: byte-identical to the downloaded source (not overwritten)", sha256(src) == sha256(PKG / o["path"]), o["path"])
    # statistics recomputed from the exported masks
    for c in CHANGES:
        if "areas" not in c:
            ck("statistics", f"{c['dataset_id']}/{c['variable']}: insufficient data reports no numbers", True, c["outcome"])
            continue
        folder = PKG / c["folder"]
        a = c["areas"]
        with rasterio.open(folder / "change_classification.tif") as s:
            diff = s.read(1)
            rows_m2 = pixel_area_m2_per_row(s.transform, s.height, s.crs)
        rec = {k: area_ha(diff == code, rows_m2) for k, code in (("gained_ha", 4), ("lost_ha", 3))}
        for k, v in rec.items():
            ck("statistics", f"{c['dataset_id']}/{c['variable']}: {k} recomputed from the exported raster equals the reported value", abs(v - a[k]) < 0.05, f"{v:.2f} vs {a[k]}")
        total = a["unchanged_water_ha"] + a["unchanged_land_ha"] + a["gained_ha"] + a["lost_ha"] + a.get("noise_filtered_ha", 0)
        ck("statistics", f"{c['dataset_id']}/{c['variable']}: gain + loss + unchanged + filtered reconcile with the analysed area", abs(total - a["analysed_ha"]) < 1.0, f"{total:.2f} vs {a['analysed_ha']}")
        with rasterio.open(folder / "filtered_mask.tif") as s:
            fm = s.read(1)
        ck("statistics", f"{c['dataset_id']}/{c['variable']}: filtered mask area equals noise_filtered_ha", abs(area_ha(fm == 1, rows_m2) - a.get("noise_filtered_ha", 0)) < 0.05)
    for d in DS.values():
        st = read_json(d["_dir"] / "historical_statistics.json")
        first = d["observations"][0]
        with rasterio.open(d["_dir"] / first["file"]) as s:
            arr = s.read(1)
            rm = pixel_area_m2_per_row(s.transform, s.height, s.crs)
            tag = s.tags().get("DATE") or s.tags().get("OBSERVATION_DATE")
        k, v = next(iter(st["variables"].items()))
        cls = next(x["class"] for x in d["variables"] if x["key"] == k)
        cls = cls if isinstance(cls, list) else [cls]
        val = area_ha(np.isin(arr, cls), rm)
        ck("statistics", f"{d['id']}: first-date {k} area in the statistics file equals the area recomputed from the raster", abs(val - v["series"][0]["area_ha"]) < 0.05, f"{val:.2f} vs {v['series'][0]['area_ha']}")
        if tag:
            ck("dates", f"{d['id']}: raster DATE tag equals dataset.json date", tag[:10] == first["date"][:10] or tag[:4] == first["date"][:4], f"{tag} vs {first['date']}", warn=True)
    ck("integrity", "every package file has a checksum", all(r["sha256"] for r in integrity), f"{len(integrity)} files")
    missing = [k for k in INDEX if not (PKG / k).exists()]
    ck("integrity", "every file in the build index exists", not missing, missing[:5])
    return checks, integrity


# --------------------------------------------------------------------------------------- documents
def region_counts(inv):
    out = {}
    for r in inv:
        out[r["Region"]] = out.get(r["Region"], 0) + 1
    return out


def write_documents(inv, reg_rows, mapping, checks) -> None:
    pv = PKG / "08_VISUAL_DATASETS/PROCESSED_PREVIEWS"
    S = PKG / "08_VISUAL_DATASETS/APPLICATION_SCREENSHOTS"
    summ = {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "warn", "fail")}
    # per-dataset PDFs
    for d in DS.values():
        o0, o1 = d["observations"][0], d["observations"][-1]
        reg = [r for r in reg_rows if r["Dataset ID"] == d["id"]][0]
        ba = PKG / "08_VISUAL_DATASETS/BEFORE_AFTER" / f"{d['id']}__first_vs_last_observation.png"
        blocks = [("h", "Identity"), ("table", [["Field", "Value"], ["Dataset ID", d["id"]], ["Public label", d["public_label"]], ["Provider / origin", d["source"]], ["Product", d["product"]], ["Region", REGION_NAME[d["_region"]]], ["Observation dates", ", ".join(o["date"] for o in d["observations"])], ["Resolution", f"{d['resolution_m']} m"], ["CRS", d["crs"]], ["License", d.get("license", "generated for NASAX")]], [140, 380]),
                  ("h", "Processing (read from the code and pipeline.json)"), ("table", [["Step", "Record"]] + [[k, v] for k, v in reg.items() if k not in ("Dataset ID", "Dataset", "Region")], [120, 400]), ("h", "Evidence"), ("img", str(ba), 330, "First versus last observation")]
        simple_pdf(PKG / "09_PROCESSING_METHODOLOGY/DATASET_DOCS" / f"{d['id']}.pdf", f"Dataset documentation: {d['name']}", blocks)
    for cat in ("STATES", "DISTRICTS", "CITIES", "LAKES", "RIVERS", "OTHER_FEATURES"):
        files = sorted((PKG / "04_GEOGRAPHICAL_BOUNDARIES" / cat).glob("*.metadata.json"))
        blocks = []
        for f in files:
            m = read_json(f)
            png = f.with_name(f.name.replace(".metadata.json", ".png"))
            blocks += [("h", m["title"]), ("table", [["Field", "Value"], ["Features", m["feature_count"]], ["CRS", m["crs"]], ["Source", m.get("source", "")], ["Source ID", m.get("source_id", "")], ["Attributes", ", ".join(m["attributes"])], ["Official", m.get("official")]], [100, 420]), ("img", str(png), 300, "Map preview")]
        simple_pdf(PKG / "04_GEOGRAPHICAL_BOUNDARIES" / cat / f"{cat}_documentation.pdf", f"Vector dataset documentation: {cat}", blocks)
    # statistics report
    sb = [("p", "Every figure comes from backend/app/explorer/stats.py applied to the processed rasters; the CSV files in this folder carry the same values.")]
    for d in DS.values():
        sb.append(("h", f"{d['name']} ({d['public_label']})"))
        for f in sorted((PKG / "07_STATISTICS_AND_ANALYSIS/CHARTS").glob(f"{d['id']}__*.png"))[:3]:
            sb.append(("img", str(f), 220, f.name))
    simple_pdf(PKG / "07_STATISTICS_AND_ANALYSIS/STATISTICS_REPORT.pdf", "NASAX historical statistics report", sb)
    # processing report
    prb = [("p", "This register states what the scripts actually did. Nothing in it is a template: values are read from dataset.json, pipeline.json and generator_config.json.")]
    for r in reg_rows:
        prb += [("h", r.get("Dataset", "")), ("table", [["Field", "Record"]] + [[k, v] for k, v in r.items() if k != "Dataset"], [130, 390])]
    simple_pdf(PKG / "09_PROCESSING_METHODOLOGY/PROCESSING_REPORT.pdf", "NASAX dataset processing report", prb)
    # validation report
    val_rows = [["Scope", "Check", "Status", "Detail"]] + [[c["scope"][:50], c["check"][:90], c["status"], c["detail"][:70]] for c in checks if c["status"] != "pass"]
    by: dict[str, list[int]] = {}
    for c in checks:
        by.setdefault(c["scope"].split("/")[0] if "/" in c["scope"] else c["scope"], [0, 0, 0])[["pass", "warn", "fail"].index(c["status"])] += 1
    simple_pdf(PKG / "11_VALIDATION/VALIDATION_REPORT.pdf", "NASAX complete dataset validation report", [("p", f"{len(checks)} checks: {summ['pass']} passed, {summ['warn']} warnings, {summ['fail']} failed."), ("table", [["Group", "Pass", "Warn", "Fail"]] + [[k, *v] for k, v in sorted(by.items())]), ("h", "Warnings and failures"), ("table", val_rows) if len(val_rows) > 1 else ("p", "None.")])
    # the long judge document
    big = [("h", "1. Project overview"), ("p", "NASAX is an Earth Time Machine: a 3D globe that shows where historical observations exist, compares two dates, and measures change. This document describes every dataset the application loads and how each was obtained, processed and displayed."),
          ("h", "2. Dataset architecture"), ("p", "datasets/india_historical_atlas/processed/<designation>/<region>/<dataset>/ holds dataset.json and observations/*.tif (COG). The backend discovers every dataset.json at start-up; change detection and statistics are computed from those rasters on request."), ("img", str(pv / "india_overview.png"), 330, "Dataset footprints on the India overview"),
          ("h", "3-8. Providers, identifiers, coverage, resolution and formats"),
          ("table", [["Dataset ID", "Label", "Provider", "Dates", "Resolution", "Region"]] + [[d["id"], d["public_label"], d["source"][:60], f"{d['observations'][0]['date'][:4]}-{d['observations'][-1]['date'][:4]} ({len(d['observations'])})", f"{d['resolution_m']} m", REGION_NAME[d["_region"]]] for d in DS.values()], [95, 70, 150, 70, 50, 85]),
          ("h", "5. Original data examples")]
    for p in sorted((PKG / "08_VISUAL_DATASETS/ORIGINAL_PREVIEWS").glob("*.png")):
        big.append(("img", str(p), 260, f"Original official file window: {p.stem}"))
    big += [("h", "9-12. Original versus processed formats, pipeline, clipping, reprojection and classification"), ("p", "Originals are kept byte-for-byte in 01_ORIGINAL_OFFICIAL_DATA. Processing clips a pixel window, keeps EPSG:4326 (no reprojection was needed: every source is already geographic), and reclassifies: GHSL built-up if built m2 / cell area >= 0.15; JRC transitions to water/not-water at 1984 and 2021; WorldCover aggregated 3x by mode with class 95 as mangrove."),
            ("table", [["Dataset", "Clipping", "Reprojection", "Classification"]] + [[r["Dataset"], str(r.get("Clipping", ""))[:110], str(r.get("Reprojection", ""))[:50], str(r.get("Classification", ""))[:150]] for r in reg_rows if "Clipping" in r], [110, 150, 70, 190]),
            ("h", "13-14. Change detection and historical statistics"), ("p", "Same-season composites at both ends; areas use geodesic per-row pixel areas; a pixel is 'class present' if present in at least half of its valid observations; changes narrower than the dataset noise filter (1 px for classification products, 3 px for Landsat-derived water) are reported as 'filtered' and counted separately so gain + loss + unchanged + filtered equals the analysed area. Datasets with fewer than two observation years report insufficient data, never zero."),
            ]
    for c in CHANGES:
        if "areas" in c and c["variable"] == next(v["key"] for v in DS[c["dataset_id"]]["variables"] if v.get("primary")):
            big += [("h3", f"{DS[c['dataset_id']]['name']}: {c['variable']}"), ("img", str(PKG / c["folder"] / "difference_map.png"), 300, f"Change classification ({DS[c['dataset_id']]['public_label']})"), ("img", str(PKG / c["folder"] / "before_after.png"), 240, "Before and after")]
    big += [("h", "15. Dataset-to-application mapping"), ("table", [["UI layer", "Endpoint", "Processed file"]] + [[m["UI layer name"], m["Backend endpoint"][:70], m["Processed file"][:80]] for m in mapping[:40]], [170, 170, 190]), ("p", f"The full mapping ({len(mapping)} rows) is APPLICATION_DATA_MAPPING.csv. Endpoints were exercised against the running application code; the status column records the HTTP result."),
            ("h", "16-17. Quality, limitations and the official / illustrative distinction"), ("p", "Satellite Observations are derived from files really downloaded from JRC and ESA (JRC Global Surface Water, GHSL, ESA WorldCover). GHSL epochs are modelled products; JRC 1984 and 2021 are epoch states, not acquisition dates; WorldCover is a single date and supports no change analysis. Illustrative Datasets are generated, labelled as such, and carry no scientific claim. No Landsat, Sentinel-2 or Bhuvan scenes were obtained; five sources need an account (see SOURCES_NOT_DOWNLOADED.json). The Himalayas region has no official-derived data. Years requested for comparison but absent from the official data (for example Hyderabad 2005, 2015, 2024) exist only in the Illustrative Dataset."),
            ("h", "18. Checksums and verification"), ("p", f"{len(inv)} dataset files are inventoried with SHA-256; validation ran {len(checks)} checks ({summ['pass']} pass, {summ['warn']} warn, {summ['fail']} fail). See 11_VALIDATION and 10_DATA_PROVENANCE/CHECKSUMS.sha256."), ("h", "19. Application screenshots")]
    for p in sorted(S.glob("*.jpg")):
        big.append(("img", str(p), 300, p.name))
    big += [("h", "20. Official documentation"), ("table", [["Source", "Official URL", "Status"]] + [[e["id"], e.get("official_dataset_url", ""), e["verification_status"]] for e in REG.values()], [150, 270, 100])]
    simple_pdf(PKG / "NASAX_Complete_Earth_Observation_Dataset_and_Processing_Documentation.pdf", "NASAX — Complete Earth Observation Dataset & Processing Documentation", big)
    shutil.copy2(PKG / "NASAX_Complete_Earth_Observation_Dataset_and_Processing_Documentation.pdf", PKG / "09_PROCESSING_METHODOLOGY/NASAX_Complete_Earth_Observation_Dataset_and_Processing_Documentation.pdf")


def provenance_files() -> None:
    P = PKG / "10_DATA_PROVENANCE"
    jdump(P / "SOURCE_REGISTRY.json", read_json(DOC / "source_registry.json"))
    for sid, e in REG.items():
        (P / "LICENSES").mkdir(parents=True, exist_ok=True)
        (P / "LICENSES" / f"{sid}.txt").write_text(f"{e.get('providing_organization')}\n{e.get('dataset_identifier')}\n\nLicense / terms as recorded in the source registry:\n{e.get('license_or_terms') or 'not recorded: see the provider page'}\n\nOfficial page: {e.get('official_dataset_url')}\n", encoding="utf-8")
        jdump(P / "SOURCE_DOCUMENTATION" / f"{sid}.json", e)


def zip_dirs(name: str, parts: list[Path]) -> Path:
    z = OUT_ROOT / name
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for part in parts:
            files = [part] if part.is_file() else sorted(q for q in part.rglob("*") if q.is_file())
            for f in files:
                zf.write(f, f"NASAX_COMPLETE_DATASET_DELIVERY/{f.relative_to(PKG).as_posix()}")
    return z


def official_exports() -> None:
    import csv as _csv
    base = PKG / "02_PROCESSED_OFFICIAL_DATA"
    for d in DS.values():
        if not d["_official"]:
            continue
        def reg(dst: Path, src: Path, kind: str, **kw):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            INDEX[rel(dst)] = {"kind": kind, "dataset_id": d["id"], "region": d["_region"], "official": True, **kw}
        for c in CHANGES:
            if c["dataset_id"] != d["id"] or "areas" not in c:
                continue
            f = PKG / c["folder"]
            tag = f"{d['id']}__{c['variable']}__{c['folder'].rsplit('/', 1)[-1]}"
            reg(base / "GEOJSON" / f"{tag}__hotspots.geojson", f / "hotspots.geojson", "official_export_geojson")
            reg(base / "GEOPACKAGE" / f"{tag}__hotspots.gpkg", f / "hotspots.gpkg", "official_export_gpkg")
        reg(base / "CSV" / f"{d['id']}__historical_statistics.csv", PKG / f"07_STATISTICS_AND_ANALYSIS/CSV/{d['id']}__historical_statistics.csv", "official_export_csv")
        reg(base / "JSON" / f"{d['id']}__historical_statistics.json", d["_dir"] / "historical_statistics.json", "official_export_json")
        reg(base / "JSON" / f"{d['id']}__dataset.json", d["_dir"] / "dataset.json", "official_export_json")
        if (d["_dir"] / "pipeline.json").exists():
            reg(base / "JSON" / f"{d['id']}__pipeline.json", d["_dir"] / "pipeline.json", "official_export_json")


def main() -> None:
    official_exports()
    print("inventory")
    inv = build_inventory()
    write_csv(PKG / "MASTER_DATASET_INVENTORY.csv", inv)
    jdump(PKG / "MASTER_DATASET_INVENTORY.json", inv)
    print("processing register")
    reg_rows = processing_register()
    fields = sorted({k for r in reg_rows for k in r}, key=lambda k: list(reg_rows[0]).index(k) if k in reg_rows[0] else 99)
    write_csv(PKG / "09_PROCESSING_METHODOLOGY/PROCESSING_REGISTER.csv", reg_rows, fields)
    jdump(PKG / "09_PROCESSING_METHODOLOGY/PROCESSING_REGISTER.json", reg_rows)
    print("application mapping")
    mapping = app_mapping()
    write_csv(PKG / "APPLICATION_DATA_MAPPING.csv", mapping)
    provenance_files()
    print("validation")
    checks, integrity = validate()
    summ = {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "warn", "fail")}
    jdump(PKG / "11_VALIDATION/VALIDATION_REPORT.json", {"generated_at": now_iso(), "summary": summ, "total": len(checks), "checks": checks})
    write_csv(PKG / "11_VALIDATION/FILE_INTEGRITY_REPORT.csv", integrity)
    print("documents")
    write_documents(inv, reg_rows, mapping, checks)
    (PKG / "README_DATASET_GUIDE.md").write_text("# NASAX complete dataset delivery\nSee README_DATASET_GUIDE.pdf.\n", encoding="utf-8")
    simple_pdf(PKG / "README_DATASET_GUIDE.pdf", "NASAX complete dataset delivery: guide", [
        ("p", "Start with MASTER_DATASET_INVENTORY.csv (one row per raster/vector file with provider, source, CRS, dimensions, checksum and how the application uses it), then APPLICATION_DATA_MAPPING.csv (UI layer to endpoint to file), then 09_PROCESSING_METHODOLOGY/PROCESSING_REGISTER.csv."),
        ("table", [["Folder", "Contents"], ["01_ORIGINAL_OFFICIAL_DATA", "Original downloads, byte-for-byte, verified against the registry checksum"], ["02_PROCESSED_OFFICIAL_DATA", "GeoTIFF and COG rasters derived from the originals"], ["03_ILLUSTRATIVE_DEMONSTRATION_DATA", "Generated demonstration layers (Illustrative Dataset), per region"],
                   ["04_GEOGRAPHICAL_BOUNDARIES", "GeoJSON, GeoPackage, CSV, PNG, metadata and PDF per boundary level"], ["05_HISTORICAL_OBSERVATIONS", "Observation index and previews per dataset"], ["06_CHANGE_DETECTION", "Per analysis: state, classification, gain/loss/unchanged/filtered masks, hotspots, statistics, maps, PDF"],
                   ["07_STATISTICS_AND_ANALYSIS", "CSV, JSON, charts, report"], ["08_VISUAL_DATASETS", "Original and processed previews, before/after, legends, screenshots"], ["09_PROCESSING_METHODOLOGY", "Processing register and report, per-dataset PDFs, full documentation"], ["10_DATA_PROVENANCE", "Source registry, licences, source documentation, checksums"], ["11_VALIDATION", "Validation report and file integrity report"]], [180, 340]),
        ("p", "Official versus illustrative: files under 01 and 02 come from, or are derived from, real downloads. Files under 03 are generated and labelled Illustrative Dataset; they are never satellite imagery. Data not obtained is listed in 01_ORIGINAL_OFFICIAL_DATA/OTHER_VERIFIED_SOURCES/SOURCES_NOT_DOWNLOADED.json.")])
    # checksums for the whole package
    lines = [f"{sha256(p)}  {rel(p)}" for p in sorted(PKG.rglob("*")) if p.is_file() and p.name != "CHECKSUMS.sha256"]
    (PKG / "10_DATA_PROVENANCE/CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # NASAX_-prefixed copies of the key tables beside the package
    for src, dst in ((PKG / "MASTER_DATASET_INVENTORY.csv", "NASAX_COMPLETE_DATASET_INVENTORY.csv"), (PKG / "09_PROCESSING_METHODOLOGY/PROCESSING_REGISTER.csv", "NASAX_DATASET_PROCESSING_REGISTER.csv"), (PKG / "09_PROCESSING_METHODOLOGY/PROCESSING_REGISTER.json", "NASAX_DATASET_PROCESSING_REGISTER.json"),
                     (PKG / "09_PROCESSING_METHODOLOGY/PROCESSING_REPORT.pdf", "NASAX_DATASET_PROCESSING_REPORT.pdf"), (PKG / "APPLICATION_DATA_MAPPING.csv", "NASAX_APPLICATION_DATA_MAPPING.csv"), (PKG / "11_VALIDATION/VALIDATION_REPORT.pdf", "NASAX_COMPLETE_DATASET_VALIDATION_REPORT.pdf"), (PKG / "11_VALIDATION/VALIDATION_REPORT.json", "NASAX_COMPLETE_DATASET_VALIDATION_REPORT.json")):
        shutil.copy2(src, OUT_ROOT / dst)
    print("archives")
    P = PKG
    zip_dirs("NASAX_OFFICIAL_ORIGINAL_DATA.zip", [P / "01_ORIGINAL_OFFICIAL_DATA", P / "10_DATA_PROVENANCE/SOURCE_REGISTRY.json"])
    zip_dirs("NASAX_PROCESSED_DATASETS.zip", [P / d for d in ("02_PROCESSED_OFFICIAL_DATA", "04_GEOGRAPHICAL_BOUNDARIES", "05_HISTORICAL_OBSERVATIONS", "06_CHANGE_DETECTION", "07_STATISTICS_AND_ANALYSIS")])
    zip_dirs("NASAX_ILLUSTRATIVE_DATASETS.zip", [P / "03_ILLUSTRATIVE_DEMONSTRATION_DATA"])
    zip_dirs("NASAX_JUDGE_DOCUMENTATION.zip", [P / d for d in ("08_VISUAL_DATASETS", "09_PROCESSING_METHODOLOGY", "10_DATA_PROVENANCE", "11_VALIDATION", "README_DATASET_GUIDE.pdf", "MASTER_DATASET_INVENTORY.csv", "MASTER_DATASET_INVENTORY.json", "APPLICATION_DATA_MAPPING.csv", "NASAX_Complete_Earth_Observation_Dataset_and_Processing_Documentation.pdf")])
    zip_dirs("NASAX_COMPLETE_DATASET_DELIVERY.zip", [P])
    print("finalize done", summ)


if __name__ == "__main__":
    main()
