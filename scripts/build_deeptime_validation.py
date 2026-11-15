"""06_SCIENTIFIC_REFERENCES and 07_VALIDATION of NASAX_DEEP_TIME_EVIDENCE.

    backend/.venv/Scripts/python -X utf8 scripts/build_deeptime_validation.py

Checks are independent re-derivations, not echoes of the build: plate positions are recomputed with pygplates, fossil values
are compared with the original PBDB download and with the live PBDB service, DOIs are looked up at Crossref, ICS boundary ages
are looked for in the text of the official ICS chart, and every produced geometry is re-opened and tested.
Only public identifiers (PBDB record numbers, DOIs) are sent to those services.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import pygplates
import rasterio
import requests
import xarray as xr
from shapely.geometry import shape
from shapely.validation import explain_validity

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.explorer.deeptime import key as akey  # noqa: E402
from app.explorer.deeptime_knowledge import BIBLIOGRAPHY  # noqa: E402

DATA = ROOT / "datasets" / "deep_time"
EVID = Path(os.environ.get("DEEPTIME_EVIDENCE", "F:/NASAX_DEEP_TIME_EVIDENCE"))
ORIG = Path(os.environ.get("DEEPTIME_ROOT", "F:/NASAX_DEEPTIME")) / "originals"
CSVD = EVID / "03_CSV_DATASETS"
REFD = EVID / "06_SCIENTIFIC_REFERENCES"
VALD = EVID / "07_VALIDATION"
UA = {"User-Agent": "NASAX-validation/1.0"}
SPEC = {
    "india_plate_reconstruction.csv": "reconstruction_id geological_age_ma plate_id plate_name reconstructed_latitude reconstructed_longitude rotation_model reconstruction_source uncertainty source_reference",
    "india_paleogeography_timeline.csv": "record_id age_ma geological_era geological_period region paleogeographic_environment land_sea_context geological_event source_dataset source_reference confidence limitations",
    "himalaya_geological_evolution.csv": "record_id age_ma geological_stage india_plate_position collision_status tectonic_process mountain_building_context geological_evidence source_reference uncertainty",
    "india_dinosaur_fossil_occurrences.csv": "occurrence_id taxon_name higher_taxonomy fossil_type geological_period minimum_age_ma maximum_age_ma locality state latitude longitude formation reference_id source_database data_quality",
    "india_geological_formations.csv": "formation_id formation_name state locality lithology depositional_environment minimum_age_ma maximum_age_ma geological_period coordinates source_database reference_id",
    "geological_events_timeline.csv": "event_id event_name start_age_ma end_age_ma affected_region geological_process description evidence_source confidence uncertainty_notes",
    "geological_reconstruction_metadata.csv": "dataset_id original_filename provider model_name source_url original_format spatial_resolution temporal_resolution CRS license citation downloaded_date checksum processing_method",
    "india_deep_time_visualization_index.csv": "frame_id age_ma reconstruction_id raster_file vector_file coastline_file plate_geometry_file preview_image geological_period source_status interpolation_status",
}
ID_COL = {"india_plate_reconstruction.csv": "reconstruction_id", "india_paleogeography_timeline.csv": "record_id", "himalaya_geological_evolution.csv": "record_id", "india_dinosaur_fossil_occurrences.csv": "occurrence_id", "india_geological_formations.csv": "formation_id", "geological_events_timeline.csv": "event_id", "geological_reconstruction_metadata.csv": "dataset_id", "india_deep_time_visualization_index.csv": "frame_id"}


def rows_of(name: str) -> list[dict]:
    with (CSVD / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# --------------------------------------------------------------------------------------------- 06 references
def references() -> dict:
    REFD.mkdir(parents=True, exist_ok=True)
    rows, ok = [], 0
    for b in BIBLIOGRAPHY:
        row = {"id": b["id"], "citation": b["citation"], "doi": b["doi"], "role": b["role"], "crossref_status": "no DOI", "crossref_title": "", "crossref_first_author": "", "crossref_year": ""}
        if b["doi"]:
            try:
                r = requests.get("https://api.crossref.org/works/" + b["doi"], headers=UA, timeout=30)
                if r.status_code == 200:
                    m = r.json()["message"]
                    row.update(crossref_status="resolved", crossref_title=(m.get("title") or [""])[0], crossref_first_author=((m.get("author") or [{}])[0]).get("family", ""), crossref_year=str(((m.get("issued", {}).get("date-parts") or [[None]])[0][0]) or ""))
                    ok += 1
                else:
                    row["crossref_status"] = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                row["crossref_status"] = f"error: {type(e).__name__}"
        rows.append(row)
    with (REFD / "BIBLIOGRAPHY.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    reg = json.loads((ORIG / "_source_registry.json").read_text(encoding="utf-8"))
    reg["derived_products"] = [
        {"id": "deep_time_frames", "description": "Reconstructed GeoJSON frames (34 ages x layers) produced with pygplates 1.0.0 from the GPlates 2.5 GeoData and PALEOMAP files", "script": "scripts/build_deeptime_data.py"},
        {"id": "deep_time_csv", "description": "Eight CSV datasets generated from the frames, PBDB records and the referenced knowledge tables", "script": "scripts/build_deeptime_tables.py"},
    ]
    reg["not_used"] = [
        {"source": "Macrostrat geologic map units for India", "reason": "Macrostrat's map coverage of India is limited to small-scale units; no named Indian formations (for example Lameta) were found, so formation ages come from PBDB collections and are flagged as such"},
        {"source": "Muller et al. 2022 / Merdith et al. alternative reconstructions in the GPlates package", "reason": "Present in the original archive, not used for display so that each frame stays consistent within one model"},
    ]
    (REFD / "SOURCE_REGISTRY.json").write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    lic = REFD / "LICENSES"
    lic.mkdir(exist_ok=True)
    el = ORIG / "EARTHBYTE" / "extracted" / "License.txt"
    if el.exists():
        shutil.copyfile(el, lic / "EARTHBYTE_PALEOMAP_License.txt")
    lines = ["# Licences of the sources used", "", "Licence statements are copied from each provider's download page or file; nothing here is legal advice.", ""]
    for s in reg["sources"]:
        lines += [f"## {s['source_id']}", f"- File: {s['original_filename']}", f"- Provider: {s['provider']}", f"- Licence: {s['license']}", f"- URL: {s['source_url']}", f"- Citation: {s['citation']}", ""]
    (lic / "LICENSES.md").write_text("\n".join(lines), encoding="utf-8")
    return {"dois": sum(1 for b in BIBLIOGRAPHY if b["doi"]), "resolved": ok}


# --------------------------------------------------------------------------------------------- 07 validation
def dataset_validation() -> dict:
    res: dict = {"csv": {}}
    for name, cols in SPEC.items():
        rs = rows_of(name)
        with (CSVD / name).open(encoding="utf-8", newline="") as f:
            header = next(csv.reader(f))
        ids = [r[ID_COL[name]] for r in rs]
        res["csv"][name] = {"rows": len(rs), "header_matches_spec": header == cols.split(), "ids_unique": len(set(ids)) == len(ids), "empty_id": sum(1 for i in ids if not i.strip())}
    # --- plate reconstruction: recompute every row independently with pygplates
    rot_eb = pygplates.RotationModel(str(next((ORIG / "GPLATES/extracted").rglob("Zahirovic_etal_2022_OptimisedMantleRef_and_NNRMantleRef.rot"))))
    rot_pm = pygplates.RotationModel(str(next((ORIG / "EARTHBYTE/extracted").rglob("PALEOMAP_PlateModel.rot"))))
    maxd = 0.0
    for r in rows_of("india_plate_reconstruction.csv"):
        rm = rot_eb if "-EB-" in r["reconstruction_id"] else rot_pm
        lat, lon = (pygplates.PointOnSphere(28.5, 80.0) if False else None) or (None, None)
        pt = rm.get_rotation(float(r["geological_age_ma"]), 501, 0, anchor_plate_id=0) * pygplates.PointOnSphere(28.5, 80.0)
        la, lo = pt.to_lat_lon()
        maxd = max(maxd, abs(la - float(r["reconstructed_latitude"])), abs(lo - float(r["reconstructed_longitude"])))
    res["plate_reconstruction_recomputed_max_abs_error_deg"] = round(maxd, 5)
    res["plate_reconstruction_ok"] = maxd < 1e-3
    # --- fossils vs original PBDB CSV
    orig = {}
    lines = (ORIG / "PALEOBIOLOGY_DATABASE/pbdb_occs_Dinosauria_IN.csv").read_text(encoding="utf-8").splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith('"occurrence_no"'))
    hdr = next(csv.reader([lines[i]]))
    for row in csv.reader(lines[i + 1 :]):
        if len(row) >= len(hdr):
            d = dict(zip(hdr, row))
            orig[f"PBDB:occ:{d['occurrence_no']}"] = d
    fos = rows_of("india_dinosaur_fossil_occurrences.csv")
    mism, missing = [], []
    for r in fos:
        o = orig.get(r["occurrence_id"])
        if not o:
            missing.append(r["occurrence_id"])
            continue
        checks = [("taxon", r["taxon_name"] == o["accepted_name"]), ("min", abs(float(r["minimum_age_ma"]) - float(o["min_ma"])) < 1e-9), ("max", abs(float(r["maximum_age_ma"]) - float(o["max_ma"])) < 1e-9), ("lat", abs(float(r["latitude"]) - float(o["lat"])) < 1e-6), ("lon", abs(float(r["longitude"]) - float(o["lng"])) < 1e-6)]
        bad = [k for k, v in checks if not v]
        if bad:
            mism.append({"id": r["occurrence_id"], "fields": bad})
    res["fossils_vs_original_pbdb_csv"] = {"rows": len(fos), "not_in_original": missing, "value_mismatches": mism, "original_rows": len(orig)}
    # --- fossils vs the live PBDB service (record numbers only are sent)
    live_ids, live_missing, live_name_diff, status = set(), [], [], "ok"
    nums = [r["occurrence_id"].split(":")[-1] for r in fos]
    try:
        for k in range(0, len(nums), 100):
            batch = nums[k : k + 100]
            r = requests.get("https://paleobiodb.org/data1.2/occs/list.json", params={"occ_id": ",".join(batch), "show": "class"}, headers=UA, timeout=60)
            r.raise_for_status()
            for o in r.json()["records"]:
                live_ids.add(o["oid"].replace("occ:", ""))
                mine = next((x for x in fos if x["occurrence_id"].endswith(":" + o["oid"].replace("occ:", ""))), None)
                if mine and mine["taxon_name"] != o.get("tna"):
                    live_name_diff.append({"id": mine["occurrence_id"], "csv": mine["taxon_name"], "live": o.get("tna")})
        live_missing = [n for n in nums if n not in live_ids]
    except requests.RequestException as e:
        status = f"could not reach PBDB: {type(e).__name__}"
    res["fossils_vs_live_pbdb"] = {"status": status, "checked": len(nums), "found_live": len(live_ids), "not_found_live": live_missing, "taxon_name_differences": live_name_diff}
    # --- references used by fossils exist in the downloaded PBDB reference table
    refs = set()
    with (ORIG / "PALEOBIOLOGY_DATABASE/pbdb_refs_Dinosauria_IN.csv").open(encoding="utf-8") as f:
        ls = f.read().splitlines()
    j = next(k for k, ln in enumerate(ls) if ln.startswith('"reference_no"'))
    h2 = next(csv.reader([ls[j]]))
    for row in csv.reader(ls[j + 1 :]):
        if row:
            refs.add("PBDB:ref:" + dict(zip(h2, row))["reference_no"])
    res["fossil_reference_ids_in_pbdb_reference_download"] = {"rows": len(fos), "missing": [r["occurrence_id"] for r in fos if r["reference_id"] not in refs]}
    # --- bibliography ids cited in CSVs exist
    bib = {b["id"] for b in BIBLIOGRAPHY}
    cited = set()
    for name, col in (("india_plate_reconstruction.csv", "source_reference"), ("india_paleogeography_timeline.csv", "source_reference"), ("himalaya_geological_evolution.csv", "source_reference"), ("geological_events_timeline.csv", "evidence_source")):
        for r in rows_of(name):
            cited |= {x for x in re.split(r"[;,\s]+", r[col]) if x}
    res["bibliography_ids_cited_but_undefined"] = sorted(cited - bib)
    # --- index files exist
    miss = []
    for r in rows_of("india_deep_time_visualization_index.csv"):
        for c in ("raster_file", "vector_file", "coastline_file", "plate_geometry_file", "preview_image"):
            if r[c] and not (EVID / r[c]).exists():
                miss.append(r[c])
    res["visualization_index_missing_files"] = sorted(set(miss))
    # --- formation checks
    fm = rows_of("india_geological_formations.csv")
    res["formations"] = {"rows": len(fm), "min_gt_max": [r["formation_id"] for r in fm if float(r["minimum_age_ma"]) > float(r["maximum_age_ma"])], "note": "Ages are the union of PBDB collection age ranges, not formal formation ages"}
    return res


def geometry_validation() -> dict:
    out: dict = {"geojson": {}, "geopackage": {}, "shapefile": {}, "geotiff": {}, "cog": {}, "netcdf": {}, "gpml": {}}
    inv_total = oob = n_total = 0
    for k in sorted(p for p in (EVID / "02_PROCESSED_GEOLOGICAL_DATA/GEOJSON/frames").iterdir() if p.is_dir()):
        for f in k.glob("*.geojson"):
            fc = json.loads(f.read_text(encoding="utf-8"))
            bad = 0
            for ft in fc["features"]:
                g = ft["geometry"]
                if not g:
                    bad += 1
                    continue
                s = shape(g)
                n_total += 1
                if not s.is_valid:
                    bad += 1
                b = s.bounds
                if b[0] < -180.001 or b[2] > 180.001 or b[1] < -90.001 or b[3] > 90.001:
                    oob += 1
            inv_total += bad
            out["geojson"][f"{k.name}/{f.name}"] = {"features": len(fc["features"]), "invalid": bad}
    out["geojson_summary"] = {"geometries_checked": n_total, "invalid_or_missing": inv_total, "out_of_bounds": oob}
    # GPKG layer counts == geojson
    mism = []
    for gp in sorted((EVID / "02_PROCESSED_GEOLOGICAL_DATA/GEOPACKAGE").glob("*.gpkg")):
        k = gp.stem.replace("deeptime_frame_", "")
        import pyogrio

        for layer, _ in pyogrio.list_layers(gp):
            n = len(gpd.read_file(gp, layer=layer))
            ref = len(json.loads((DATA / "frames" / k / f"{layer}.geojson").read_text(encoding="utf-8"))["features"])
            out["geopackage"][f"{gp.name}:{layer}"] = {"features": n, "matches_geojson": n == ref}
            if n != ref:
                mism.append(f"{gp.name}:{layer}")
    out["geopackage_summary"] = {"layers_checked": len(out["geopackage"]), "mismatches": mism}
    for shp in sorted((EVID / "02_PROCESSED_GEOLOGICAL_DATA/SHAPEFILE").rglob("*.shp")):
        g = gpd.read_file(shp)
        k = shp.parent.name.replace("_Ma", "")
        ref = len(json.loads((DATA / "frames" / k / f"{shp.stem}.geojson").read_text(encoding="utf-8"))["features"])
        out["shapefile"][str(shp.relative_to(EVID)).replace("\\", "/")] = {"features": len(g), "matches_geojson": len(g) == ref, "crs": str(g.crs)}
    for tif in sorted((EVID / "02_PROCESSED_GEOLOGICAL_DATA/GEOTIFF").glob("*.tif")):
        with rasterio.open(tif) as d:
            out["geotiff"][tif.name] = {"size": [d.width, d.height], "bands": d.count, "crs": str(d.crs), "bounds": list(d.bounds), "ok": d.crs.to_epsg() == 4326 and tuple(d.bounds) == (-180.0, -90.0, 180.0, 90.0)}
    for tif in sorted((EVID / "02_PROCESSED_GEOLOGICAL_DATA/COG").glob("*.tif")):
        with rasterio.open(tif) as d:
            out["cog"][tif.name] = {"driver": d.driver, "tiled": bool(d.profile.get("tiled")), "overviews": d.overviews(1), "crs": str(d.crs)}
    nc = next((EVID / "02_PROCESSED_GEOLOGICAL_DATA/NETCDF").glob("*.nc"))
    ds = xr.open_dataset(nc, engine="h5netcdf")
    z = ds["z"].values
    out["netcdf"][nc.name] = {"dims": {k: int(v) for k, v in ds.sizes.items()}, "valid_cells": int((~__import__("numpy").isnan(z)).sum()), "min_age_myr": float(__import__("numpy").nanmin(z)), "max_age_myr": float(__import__("numpy").nanmax(z))}
    for g in sorted((EVID / "02_PROCESSED_GEOLOGICAL_DATA/GPML").glob("*.gpml")):
        fc = pygplates.FeatureCollection(str(g))
        out["gpml"][g.name] = {"features": len(list(fc)), "plate_ids": sorted({f.get_reconstruction_plate_id() for f in fc})}
    return out


def time_validation() -> dict:
    man = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    req = [0, 0.001, 0.01, 0.1, 1, 5, 10, 20, 30, 40, 50, 55, 66, 75, 90, 100, 120, 140, 150, 180, 200, 230, 250]
    ages = set(man["ages"])
    rec = {float(r["geological_age_ma"]) for r in rows_of("india_plate_reconstruction.csv")}
    viz = {float(r["age_ma"]) for r in rows_of("india_deep_time_visualization_index.csv")}
    res = {"requested_ages_all_supported": all(a in ages for a in req), "requested_ages_missing": [a for a in req if a not in ages], "reconstruction_csv_covers_all_frames": rec == ages, "visualization_index_covers_all_frames": viz == ages, "supported_ages_ma": sorted(ages)}
    # frame-level checks
    notes = []
    for fm in man["frames"]:
        pm = fm["models"]["paleomap"]
        if pm.get("map_file") and not pm.get("map_exact"):
            notes.append({"age_ma": fm["age_ma"], "paleomap_age_used_ma": pm["map_age_ma"], "offset_ma": pm["map_offset_ma"], "note": "nearest published map used, not interpolated"})
    res["paleomap_nearest_age_substitutions"] = notes
    res["frames_without_cao_paleogeography"] = [fm["age_ma"] for fm in man["frames"] if not fm.get("has_cao")]
    # ICS boundary cross-check against the chart text
    # Text of the official chart, extracted once with pypdf (a venv without pypdf reads the cached text file).
    txt = (ORIG.parent / "ics_chart_text.txt").read_text(encoding="utf-8")
    nums = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", txt)}
    found, notfound = [], []
    for lvl in ("eras", "periods", "epochs", "ages"):
        d = json.loads((ORIG / f"MACROSTRAT/macrostrat_intervals_{lvl}.json").read_text(encoding="utf-8"))["success"]["data"]
        for x in d:
            b = x["b_age"]
            if b is None or b >= 540:
                continue
            (found if any(abs(b - n) < 1e-6 for n in nums) else notfound).append({"interval": x["name"], "level": lvl, "base_ma": b})
    res["ics_boundaries_vs_official_chart_text"] = {"checked": len(found) + len(notfound), "found_in_chart": len(found), "not_found_in_chart": notfound, "note": "Boundary ages from the Macrostrat ICS-derived files are searched as numbers in the text of the ICS v2024/12 chart"}
    # ranges
    bad = []
    for r in rows_of("india_dinosaur_fossil_occurrences.csv"):
        if not (0 <= float(r["minimum_age_ma"]) <= float(r["maximum_age_ma"]) <= 252):
            bad.append(r["occurrence_id"])
    ev_bad = [r["event_id"] for r in rows_of("geological_events_timeline.csv") if float(r["start_age_ma"]) < float(r["end_age_ma"])]
    res["fossil_age_range_problems"] = bad
    res["event_start_younger_than_end"] = ev_bad
    res["fossil_period_vs_age"] = _period_check()
    return res


def _period_check() -> dict:
    ts = json.loads((DATA / "timescale.json").read_text(encoding="utf-8"))
    per = {p["name"]: (p["t_age"], p["b_age"]) for p in ts["periods"]}
    off = []
    for r in rows_of("india_dinosaur_fossil_occurrences.csv"):
        lo, hi = float(r["minimum_age_ma"]), float(r["maximum_age_ma"])
        names = [n.strip() for n in re.split(r" to |/|,", r["geological_period"]) if n.strip()]
        for n in names:
            if n in per and not (hi >= per[n][0] and lo <= per[n][1]):
                off.append({"id": r["occurrence_id"], "period": n, "range": [lo, hi]})
    return {"records_whose_period_label_disagrees_with_age_range": off}


def checksums() -> int:
    lines = []
    for p in sorted(EVID.rglob("*")):
        if p.is_file() and p.name != "CHECKSUMS.sha256":
            lines.append(f"{sha(p)}  {p.relative_to(EVID).as_posix()}")
    (VALD / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main() -> None:
    VALD.mkdir(parents=True, exist_ok=True)
    print("references", references(), flush=True)
    ds = dataset_validation()
    (VALD / "DATASET_VALIDATION.json").write_text(json.dumps(ds, indent=2, ensure_ascii=False), encoding="utf-8")
    print("dataset ok", flush=True)
    gv = geometry_validation()
    (VALD / "GEOMETRY_VALIDATION.json").write_text(json.dumps(gv, indent=2, ensure_ascii=False), encoding="utf-8")
    print("geometry", gv["geojson_summary"], gv["geopackage_summary"], flush=True)
    tv = time_validation()
    (VALD / "TIME_RANGE_VALIDATION.json").write_text(json.dumps(tv, indent=2, ensure_ascii=False), encoding="utf-8")
    print("time", {k: tv[k] for k in ("requested_ages_all_supported", "reconstruction_csv_covers_all_frames", "visualization_index_covers_all_frames")}, flush=True)
    print("checksums", checksums())
    summary = {
        "csv": {k: v for k, v in ds["csv"].items()},
        "plate_reconstruction_ok": ds["plate_reconstruction_ok"], "fossil_original_mismatches": len(ds["fossils_vs_original_pbdb_csv"]["value_mismatches"]) + len(ds["fossils_vs_original_pbdb_csv"]["not_in_original"]),
        "fossil_live": ds["fossils_vs_live_pbdb"]["status"], "fossil_not_found_live": len(ds["fossils_vs_live_pbdb"]["not_found_live"]),
        "geometry_invalid": gv["geojson_summary"]["invalid_or_missing"], "ics_not_found": len(tv["ics_boundaries_vs_official_chart_text"]["not_found_in_chart"]),
    }
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
