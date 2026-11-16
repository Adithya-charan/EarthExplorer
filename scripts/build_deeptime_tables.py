"""Generate the eight Deep-Time CSV datasets from the built data in datasets/deep_time and the registered originals.

Every row is computed from a real source file (rotation models, PBDB, Macrostrat/ICS time scale, the knowledge tables with
their bibliography ids). Nothing is typed in by hand here except column mappings. Run with the backend virtualenv:

    backend/.venv/Scripts/python -X utf8 scripts/build_deeptime_tables.py

Outputs go to <EVIDENCE>/03_CSV_DATASETS (default F:/NASAX_DEEP_TIME_EVIDENCE) and are mirrored in datasets/deep_time/csv.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.explorer.deeptime import DeepTimeService, EB, PM, key  # noqa: E402
from app.explorer.deeptime_knowledge import HIMALAYA_STAGES, REFERENCE_PLACES  # noqa: E402

DATA = ROOT / "datasets" / "deep_time"
EVID = Path(os.environ.get("DEEPTIME_EVIDENCE", "F:/NASAX_DEEP_TIME_EVIDENCE"))
ORIG = Path(os.environ.get("DEEPTIME_ROOT", "F:/NASAX_DEEPTIME")) / "originals"
CSV_DIR = EVID / "03_CSV_DATASETS"
PROC = "02_PROCESSED_GEOLOGICAL_DATA"
PREV = "05_VISUAL_PROOF/GLOBAL_RECONSTRUCTIONS"

COLUMNS = {
    "india_plate_reconstruction.csv": "reconstruction_id geological_age_ma plate_id plate_name reconstructed_latitude reconstructed_longitude rotation_model reconstruction_source uncertainty source_reference",
    "india_paleogeography_timeline.csv": "record_id age_ma geological_era geological_period region paleogeographic_environment land_sea_context geological_event source_dataset source_reference confidence limitations",
    "himalaya_geological_evolution.csv": "record_id age_ma geological_stage india_plate_position collision_status tectonic_process mountain_building_context geological_evidence source_reference uncertainty",
    "india_dinosaur_fossil_occurrences.csv": "occurrence_id taxon_name higher_taxonomy fossil_type geological_period minimum_age_ma maximum_age_ma locality state latitude longitude formation reference_id source_database data_quality",
    "india_geological_formations.csv": "formation_id formation_name state locality lithology depositional_environment minimum_age_ma maximum_age_ma geological_period coordinates source_database reference_id",
    "geological_events_timeline.csv": "event_id event_name start_age_ma end_age_ma affected_region geological_process description evidence_source confidence uncertainty_notes",
    "geological_reconstruction_metadata.csv": "dataset_id original_filename provider model_name source_url original_format spatial_resolution temporal_resolution CRS license citation downloaded_date checksum processing_method",
    "india_deep_time_visualization_index.csv": "frame_id age_ma reconstruction_id raster_file vector_file coastline_file plate_geometry_file preview_image geological_period source_status interpolation_status",
}

MODEL_ROT = {
    EB: "Zahirovic et al. (2022) optimised-mantle-reference rotation model (EarthByte), anchor plate 0",
    PM: "PALEOMAP Global Plate Model (Scotese 2016), anchor plate 0",
}
MODEL_SRC = {
    EB: "GPlates 2.5 GeoData, EarthByte (Zenodo 14194897): Rotations/Zahirovic_etal_2022_OptimisedMantleRef_and_NNRMantleRef.rot",
    PM: "Scotese PaleoAtlas v3 (EarthByte): PALEOMAP_PlateModel.rot",
}
MODEL_REF = {EB: "B01;B02", PM: "B05"}
SHORT = {EB: "EB", PM: "PM"}


def fmt_age(a: float) -> str:
    return f"{a:g}"


def write(name: str, rows: list[dict]) -> int:
    cols = COLUMNS[name].split()
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    for r in rows:
        extra = set(r) - set(cols)
        miss = [c for c in cols if c not in r]
        assert not extra and not miss, (name, extra, miss)
    with (CSV_DIR / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows({c: ("" if r[c] is None else r[c]) for c in cols} for r in rows)
    mirror = DATA / "csv"
    mirror.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CSV_DIR / name, mirror / name)
    return len(rows)


def land_sea(ctx: str | None) -> str:
    if ctx is None:
        return "not mapped at this age (no Cao et al. 2017 paleogeography)"
    if ctx == "landmass":
        return "land"
    if ctx == "shallow marine":
        return "shallow sea"
    if ctx == "mountains":
        return "land (mountain class)"
    if ctx == "ice sheet":
        return "land ice"
    if ctx.startswith("no mapped land"):
        return "not land or shallow sea in the map (deep ocean or unmapped)"
    raise ValueError(f"unmapped class {ctx!r}")


def reconstruction_id(age: float, model: str) -> str:
    return f"IPR-{SHORT[model]}-{key(age)}"


def main() -> None:
    svc = DeepTimeService(DATA)
    assert svc.available, "run scripts/build_deeptime_data.py first"
    ages = svc.ages
    counts: dict[str, int] = {}

    # ---------------------------------------------------------------- 1. india_plate_reconstruction
    rows = []
    for a in ages:
        fm = svc.frame_meta(a)
        for m in (EB, PM):
            fr = svc.frame(a, m)
            pos = fr["india"][m]["india"]
            dis = fr["models_disagree_km"]
            unc = (
                "Not quantified by the model (rotation files carry no covariance). "
                + (f"The two models place this point {dis:,} km apart at this age. " if dis is not None else "")
                + ("Present day: no reconstruction applied." if a == 0 else fr["interpolation"] + ".")
            )
            rows.append({
                "reconstruction_id": reconstruction_id(a, m), "geological_age_ma": fmt_age(a), "plate_id": 501, "plate_name": "India",
                "reconstructed_latitude": f"{pos[0]:.4f}", "reconstructed_longitude": f"{pos[1]:.4f}",
                "rotation_model": MODEL_ROT[m], "reconstruction_source": MODEL_SRC[m], "uncertainty": unc.strip(), "source_reference": MODEL_REF[m],
            })
        _ = fm
    counts["india_plate_reconstruction.csv"] = write("india_plate_reconstruction.csv", rows)

    # ---------------------------------------------------------------- 2. india_paleogeography_timeline
    rows = []
    ctx_places = [svc.places[p] for p in REFERENCE_PLACES if p in svc.places]
    for a in ages:
        fm = svc.frame_meta(a)
        k = key(a)
        ev = svc.events(a, span=max(0.05, 0.02 * a))
        ev_text = "; ".join(e["event_name"] for e in ev) or "none catalogued at this age"
        interval = fm["models"][EB].get("cao_interval_ma")
        for p in ctx_places:
            ctx = p["cao_context"].get(k)
            rows.append({
                "record_id": f"PGT-{k}-{p['id'].replace(':', '-')}", "age_ma": fmt_age(a), "geological_era": fm["era"], "geological_period": fm["period"],
                "region": f"{p['name']} (modern reference point on the Indian Plate)",
                "paleogeographic_environment": ctx if ctx else "not classified (no Cao et al. 2017 paleogeography at this age)",
                "land_sea_context": land_sea(ctx), "geological_event": ev_text,
                "source_dataset": "Cao et al. (2017) paleogeography polygons (EarthByte/GPlates 2.5 GeoData) at the position of the point carried on the Indian Plate by the Zahirovic et al. (2022) rotation model",
                "source_reference": "B03;B01",
                "confidence": "medium" if (ctx and a <= 100) else ("low" if ctx else "not available"),
                "limitations": (f"Cao interval used: {interval[0]:g}-{interval[1]:g} Ma. " if interval else "")
                + "Modern location used only as a reference point on the plate; the place itself did not exist then. Global classification at coarse resolution, not city-level.",
            })
    counts["india_paleogeography_timeline.csv"] = write("india_paleogeography_timeline.csv", rows)

    # ---------------------------------------------------------------- 3. himalaya_geological_evolution
    rows = []
    for i, s in enumerate(svc.himalaya()["stages"], 1):
        pe, pp = s["india_position"][EB], s["india_position"][PM]
        gap = s["india_eurasia_gap_km"]
        fmtp = lambda p: "n/a" if not p else f"{abs(p[0]):.1f}{'N' if p[0] >= 0 else 'S'}, {abs(p[1]):.1f}{'E' if p[1] >= 0 else 'W'}"  # noqa: E731
        pos = f"EarthByte {fmtp(pe)}; PALEOMAP {fmtp(pp)}; modelled distance to the Eurasian reference point {gap[EB]:,} km (EarthByte), {gap[PM]:,} km (PALEOMAP)" if gap[EB] is not None and gap[PM] is not None else f"EarthByte {fmtp(pe)}; PALEOMAP {fmtp(pp)}"
        rows.append({
            "record_id": f"HGE-{i:02d}", "age_ma": fmt_age(s["age_ma"]), "geological_stage": s["stage"], "india_plate_position": pos,
            "collision_status": s["collision"], "tectonic_process": s["process"], "mountain_building_context": s["mountains"],
            "geological_evidence": s["evidence"], "source_reference": s["sources"], "uncertainty": s["uncertainty"],
        })
    counts["himalaya_geological_evolution.csv"] = write("himalaya_geological_evolution.csv", rows)

    # ---------------------------------------------------------------- 4. fossils (straight from the PBDB-derived records)
    rows = [{c: r[c] for c in COLUMNS["india_dinosaur_fossil_occurrences.csv"].split()} for r in svc.fossils]
    counts["india_dinosaur_fossil_occurrences.csv"] = write("india_dinosaur_fossil_occurrences.csv", rows)

    # ---------------------------------------------------------------- 5. formations
    rows = []
    for r in svc.formations:
        rows.append({
            "formation_id": r["formation_id"], "formation_name": r["formation_name"], "state": r["state"], "locality": r["locality"],
            "lithology": r["lithology"], "depositional_environment": r["depositional_environment"],
            "minimum_age_ma": r["minimum_age_ma"], "maximum_age_ma": r["maximum_age_ma"], "geological_period": r["geological_period"],
            "coordinates": f"{r['latitude']:.4f}, {r['longitude']:.4f}",
            "source_database": r["source_database"], "reference_id": ";".join(r.get("reference_ids") or []),
        })
    counts["india_geological_formations.csv"] = write("india_geological_formations.csv", rows)

    # ---------------------------------------------------------------- 6. events
    rows = [{k: e[k] for k in COLUMNS["geological_events_timeline.csv"].split()} for e in svc.events()]
    counts["geological_events_timeline.csv"] = write("geological_events_timeline.csv", rows)

    # ---------------------------------------------------------------- 7. metadata (originals from the download registry)
    reg = json.loads((ORIG / "_source_registry.json").read_text(encoding="utf-8"))["sources"]
    fmt_of = {".zip": "ZIP archive (GPML, shapefile, rotation, NetCDF members)", ".pdf": "PDF", ".json": "JSON", ".csv": "CSV"}
    spatial = {
        "gplates_2_5_geodata": "Vector polygons at native source resolution; seafloor age grid 6 arc-minute",
        "scotese_paleoatlas_v3": "Raster maps 3600 x 1800 px (0.1 degree) and global plate polygons",
    }
    temporal = {
        "gplates_2_5_geodata": "Continuous rotation model (finite-rotation poles stored from 0 Ma back past the Phanerozoic, evaluated at any age); Cao et al. paleogeography intervals 2-402 Ma",
        "scotese_paleoatlas_v3": "90 paleogeographic maps, 0-750 Ma (5 Myr steps through most of the Mesozoic and Cenozoic); plate model poles in the file reach 1100 Ma",
    }
    model_of = {
        "gplates_2_5_geodata": "Zahirovic et al. (2022) rotation model; Cao et al. (2017) paleogeography",
        "scotese_paleoatlas_v3": "PALEOMAP Global Plate Model / PaleoAtlas (Scotese 2016)",
        "ics_chart_2024_12": "ICS International Chronostratigraphic Chart v2024/12",
    }
    rows = []
    for s in reg:
        ext = Path(s["original_filename"]).suffix.lower()
        sid = s["source_id"]
        is_pbdb = sid.startswith("pbdb")
        is_mac = sid.startswith("macrostrat")
        rows.append({
            "dataset_id": sid, "original_filename": s["original_filename"], "provider": s["provider"],
            "model_name": model_of.get(sid, "The Paleobiology Database data service 1.2" if is_pbdb else ("Macrostrat API v2 (ICS-derived intervals)" if is_mac else "")),
            "source_url": s["source_url"], "original_format": fmt_of.get(ext, ext.lstrip(".").upper()),
            "spatial_resolution": spatial.get(sid, "point records (modern coordinates)" if is_pbdb else "not applicable (time scale)"),
            "temporal_resolution": temporal.get(sid, "record-level age ranges (Ma)" if is_pbdb else "ICS interval boundaries"),
            "CRS": "WGS84 (EPSG:4326)" if sid in spatial or is_pbdb else "not applicable",
            "license": s["license"], "citation": s["citation"], "downloaded_date": s["downloaded_utc"][:10], "checksum": f"sha256:{s['sha256']}",
            "processing_method": {
                "gplates_2_5_geodata": "Unzipped unchanged. Static polygons, coastlines, continental polygons and Cao et al. layers reconstructed with pygplates 1.0.0 (RotationModel.reconstruct, DateLineWrapper), simplified to about 0.03-0.15 degree and written as GeoJSON by scripts/build_deeptime_data.py",
                "scotese_paleoatlas_v3": "Unzipped unchanged. The nearest published map for each frame age is used without interpolation; JPGs are georeferenced as global 0.1-degree rasters (paleo-coordinates). Rotation file read with pygplates",
                "ics_chart_2024_12": "Kept as the official reference; boundary ages used in the app are read from the Macrostrat ICS-derived interval files and cross-checked against the chart text",
            }.get(sid, "Parsed into datasets/deep_time JSON/CSV by scripts/build_deeptime_data.py; no values edited" if (is_pbdb or is_mac) else ""),
        })
    counts["geological_reconstruction_metadata.csv"] = write("geological_reconstruction_metadata.csv", rows)

    # ---------------------------------------------------------------- 8. visualisation index
    rows = []
    for a in ages:
        fm = svc.frame_meta(a)
        k = key(a)
        for m in (EB, PM):
            mm = fm["models"][m]
            if m == PM and mm.get("map_file"):
                n = int(mm["map_age_ma"])
                raster = f"{PROC}/GEOTIFF/paleomap_{n:03d}.tif"
                src = f"model reconstruction + published paleogeographic map '{mm['map_name']}' ({'exact map age' if mm['map_exact'] else 'nearest map age ' + fmt_age(mm['map_age_ma']) + ' Ma, offset ' + fmt_age(mm['map_offset_ma']) + ' Ma'})"
            else:
                raster = ""
                src = "model reconstruction (Zahirovic et al. 2022 rotations" + ("; Cao et al. 2017 paleogeography)" if fm.get("has_cao") and m == EB else "; no paleogeography map at this age)")
            rows.append({
                "frame_id": f"DT-{k}-{SHORT[m]}", "age_ma": fmt_age(a), "reconstruction_id": reconstruction_id(a, m),
                "raster_file": raster, "vector_file": f"{PROC}/GEOPACKAGE/deeptime_frame_{k}.gpkg",
                "coastline_file": f"{PROC}/GEOJSON/frames/{k}/coastlines.geojson" if m == EB else "",
                "plate_geometry_file": f"{PROC}/GEOJSON/frames/{k}/plates.geojson" if m == EB else "",
                "preview_image": f"{PREV}/recon_{k}_{SHORT[m].lower()}.png",
                "geological_period": fm["period"], "source_status": src,
                "interpolation_status": ("present day (no reconstruction)" if a == 0 else fm["interpolation"][m]) + ("; map not interpolated" if m == PM and mm.get("map_file") else ""),
            })
    counts["india_deep_time_visualization_index.csv"] = write("india_deep_time_visualization_index.csv", rows)

    print(json.dumps(counts, indent=2))
    (CSV_DIR / "_row_counts.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
