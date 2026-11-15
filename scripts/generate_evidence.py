"""Assemble NASAX_JUDGE_EVIDENCE/ from the atlas on disk, with checksums, PDFs, sample API responses and an honest evidence report.

    python scripts/generate_evidence.py

Run after generate_india_atlas.py, generate_previews.py and validate_datasets.py. Screenshots in 07_APPLICATION_DEMO/screenshots
are captured from the running app and are kept if already present. Nothing here is hand-edited data: every table is read from a file.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

import rasterio
from rasterio.windows import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from atlas_common import ATLAS, DOC, REGION_BBOX, ROOT, now_iso, read_json, sha256, write_json  # noqa: E402

EV = ROOT / "NASAX_JUDGE_EVIDENCE"
DIRS = [
    "01_DATASET_CATALOGUE", "02_OFFICIAL_SOURCES", "03_ORIGINAL_SAMPLE_DATA/original_official_files",
    "04_PROCESSED_DATA/geotiff", "04_PROCESSED_DATA/cog", "04_PROCESSED_DATA/geojson", "04_PROCESSED_DATA/csv",
    "05_VISUAL_PROOF/before_after", "05_VISUAL_PROOF/historical_comparisons", "05_VISUAL_PROOF/change_detection", "05_VISUAL_PROOF/india_overview",
    "06_METHODOLOGY", "07_APPLICATION_DEMO/screenshots", "07_APPLICATION_DEMO/sample_api_responses", "07_APPLICATION_DEMO/demonstration_scenarios",
]


def cp(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


# ------------------------------------------------------------------------------------------------ PDFs
def pdf(path: Path, title: str, blocks: list[tuple]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    small = st["BodyText"].clone("s", fontSize=7.5, leading=9.5)
    story = [Paragraph(title, st["Title"]), Paragraph(f"Generated {now_iso()} by scripts/generate_evidence.py", small), Spacer(1, 8)]
    for b in blocks:
        if b[0] == "h":
            story += [Spacer(1, 6), Paragraph(b[1], st["Heading2"])]
        elif b[0] == "p":
            story += [Paragraph(b[1], st["BodyText"]), Spacer(1, 4)]
        elif b[0] == "table":
            rows = [[Paragraph(str(c), small) for c in r] for r in b[1]]
            t = Table(rows, repeatRows=1, colWidths=b[2] if len(b) > 2 else None)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9e4f5")), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [t, Spacer(1, 6)]
    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36, title=title).build(story)


def datasets() -> list[dict]:
    return [read_json(f) | {"_dir": f.parent} for f in sorted((ATLAS / "processed").rglob("dataset.json"))]


def provenance_pdf(path: Path, reg: dict) -> None:
    ent = reg["entries"]
    rows = [["Source", "Provider", "Status", "Size", "SHA-256 (first 16)", "Used by"]]
    for e in ent:
        rows.append([f"{e['id']}<br/>{e.get('original_file_name', '')}", e["providing_organization"], e["verification_status"], f"{e['size_bytes'] / 1e6:.1f} MB" if e.get("size_bytes") else "-", (e.get("sha256") or "-")[:16], ", ".join(e.get("used_by_regions") or [])])
    dsr = [["Dataset", "Public label", "Internal origin", "Observations", "Real source files"]]
    for d in datasets():
        srcs = sorted({(o.get("provenance") or {}).get("source_id", "") for o in d["observations"]} - {""})
        dsr.append([d["name"], d["public_label"], "generated (illustrative)" if d.get("is_synthetic") else "derived from official data", f"{len(d['observations'])} ({d['observations'][0]['date'][:4]}-{d['observations'][-1]['date'][:4]})", "<br/>".join(srcs) or "none: generated"])
    pdf(path, "NASAX data provenance report", [
        ("h", "Principle"),
        ("p", "Every number shown in the application comes from a raster or boundary file in the atlas. Datasets derived from official files are labelled <b>Satellite Observations</b> and carry the SHA-256 of the original file in every observation record. Generated layers are labelled <b>Illustrative Dataset</b>; they are demonstrations, never presented as satellite imagery, and their internal metadata says they were generated."),
        ("h", "Official source registry (verification status of each source)"),
        ("p", "VERIFIED_DOWNLOADED: the file was fetched, hashed and opened with rasterio. VERIFIED_METADATA_ONLY: only the portal or catalogue metadata could be read. ACCESS_REQUIRES_AUTHENTICATION: the data exists but needs an account, so it was not downloaded. No source is marked downloaded unless a file with a recorded checksum is on disk."),
        ("table", rows, [110, 100, 85, 40, 80, 60]),
        ("h", "Datasets and their origin"),
        ("table", dsr, [120, 70, 90, 60, 160]),
        ("h", "What is not available"),
        ("p", "No Landsat, Sentinel-2 or Bhuvan scenes were downloaded for this submission, so no dataset is built from raw imagery processed by NASAX. The official-derived datasets use products that JRC and ESA publish (Global Surface Water, GHSL built-up surface, WorldCover). The Himalayas (Dhauliganga) region is entirely an Illustrative Dataset: no glacier inventory file could be downloaded without authentication."),
    ])


def methodology_pdfs(reg: dict, val: dict) -> None:
    pdf(EV / "06_METHODOLOGY/processing_pipeline.pdf", "NASAX processing pipeline (official-derived datasets)", [
        ("h", "1. Download"), ("p", "scripts/download_official_data.py streams each official file, computes its SHA-256, opens it with rasterio and records provider, identifier, URL, size and status in documentation/source_registry.json. Portal pages that cannot be downloaded are probed and recorded as metadata-only or authentication-required."),
        ("h", "2. Reclassification"), ("p", "scripts/process_satellite_data.py reads the original rasters and writes Cloud Optimized GeoTIFFs on a fixed grid. GHSL built-up surface: a cell is built-up when built m2 divided by cell area is at least 0.15. JRC Global Surface Water transitions: water at the start epoch is classes 1, 3, 4, 6, 7, 8 and at the end epoch 1, 2, 4, 5, 7, 8 (epochs 1984 and 2021). ESA WorldCover 2021 is aggregated 3x by mode and reclassified (class 95 becomes mangrove). Each observation records the operations applied."),
        ("h", "3. Statistics and change detection"), ("p", "backend/app/explorer/stats.py and change.py compute areas with geodesic per-row pixel areas (not a flat pixel count). Change detection compares same-season composites, labels gain and loss, finds hotspots by connected components and fits a Theil-Sen trend. Datasets with a single date, or fewer than two observation years in the requested period, return insufficient_data and never zero change. Classification products use no positional-noise filter (min_feature_px 1); Landsat water uses 3 pixels."),
        ("h", "4. Boundaries"), ("p", "scripts/build_geographical_boundaries.py writes GeoJSON from geoBoundaries ADM1 and ADM2 (simplified), lake outlines derived from JRC water occurrence of at least 10 percent, and the Sundarbans mangrove from WorldCover clipped to West Bengal. Cities, localities and landmarks use approximate areas and are marked approximate_bbox, approximate_point or analysis_window; none is presented as an authoritative boundary."),
        ("h", "5. Validation"), ("p", f"scripts/validate_datasets.py ran {val['total']} checks: {val['summary']['pass']} passed, {val['summary']['warn']} warnings, {val['summary']['fail']} failed. See validation_report.pdf."),
    ])
    pdf(EV / "06_METHODOLOGY/illustrative_data_methodology.pdf", "Illustrative Dataset methodology", [
        ("h", "Purpose"), ("p", "Places where no downloaded official time series exists (Himalayas glaciers, Sundarbans change through time, Hyderabad 2024, the full Bellandur record) use generated layers so the application can demonstrate navigation, timelines, change detection and analysis. They are labelled <b>Illustrative Dataset</b> everywhere in the interface. They are not satellite imagery and are not evidence of real change."),
        ("h", "How they are generated"), ("p", "backend/app/explorer/atlas.py builds a deterministic clean-truth class map per year from smooth noise fields, region-specific rules and a fixed seed, and writes generator_config.json beside the outputs. Himalayas: glacier and snow retreat with a growing glacial lake, fixed elevation. Sundarbans: spatially varying mangrove, water, mudflat, erosion and accretion. Hyderabad: built-up expansion along settlements and corridors. Bellandur Lake: modest water change, aquatic vegetation and wetland, with changes inside the lake kept separate from the surroundings."),
        ("h", "Calibration to official data"), ("p", "Hyderabad and Bellandur growth rates were calibrated so that built-up fractions track the real GHSL values for the same windows (for example Hyderabad built-up about 37.6 thousand ha in 2000 versus 37.7 thousand ha in GHSL). The generator does not claim to reproduce real patterns; it matches totals only."),
        ("h", "Rules"), ("p", "Illustrative datasets are never merged with official ones, are ranked after official data when both can answer a request, carry designation illustrative in dataset.json, and are listed separately in the manifest. Interpolated frames, if any are drawn, would be labelled visualisation-only; the timeline uses real observation dates only."),
    ])
    rows = [["Scope", "Check", "Status", "Detail"]] + [[c["scope"], c["check"], c["status"], c["detail"][:90]] for c in (val["failures"] + val["warnings"])]
    sc: dict[str, list[int]] = {}
    for c in val["checks"]:
        sc.setdefault(c["scope"], [0, 0, 0])[["pass", "warn", "fail"].index(c["status"])] += 1
    pdf(EV / "06_METHODOLOGY/validation_report.pdf", "NASAX validation report", [
        ("p", f"{val['total']} checks: {val['summary']['pass']} passed, {val['summary']['warn']} warnings, {val['summary']['fail']} failed."),
        ("table", [["Scope", "Passed", "Warnings", "Failed"]] + [[k, *v] for k, v in sc.items()]),
        ("h", "Failures and warnings"), ("table", rows) if len(rows) > 1 else ("p", "None."),
    ])


# ---------------------------------------------------------------------------------- API responses
def sample_api_responses() -> None:
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    out = EV / "07_APPLICATION_DEMO/sample_api_responses"
    c = TestClient(create_app(Settings(upload_dir=ROOT / "backend" / "data" / "uploads", explorer_dir=ATLAS / "processed", atlas_dir=ATLAS, explorer_generate_demo=False, groq_api_key=None)))

    def save(name: str, r) -> dict:
        body = r.json()
        write_json(out / f"{name}.json", {"request": f"{r.request.method} {r.request.url.path}{('?' + r.request.url.query.decode()) if r.request.url.query else ''}", "status_code": r.status_code, "response": body})
        return body

    save("datasets", c.get("/api/explorer/datasets"))
    save("suggest_bellan", c.get("/api/explorer/locations/suggest", params={"q": "Bellan"}))
    save("suggest_hyd", c.get("/api/explorer/locations/suggest", params={"q": "Hyd"}))
    for name, q, sy, ey in [("session_bellandur", "Bellandur Lake", 2002, 2022), ("session_hyderabad", "Hyderabad", 2000, 2020), ("session_sundarbans", "Sundarbans", 2000, 2020), ("session_himalayas", "Himalayas", 2001, 2020), ("session_uttarakhand_nearby_data", "Uttarakhand", 2000, 2020), ("session_chennai_no_dataset", "Chennai", 2000, 2020), ("session_unknown_place", "Zzzzqqq", 2000, 2020)]:
        body = save(name, c.post("/api/explorer/session", json={"query": q, "start_year": sy, "end_year": ey}))
        if name == "session_bellandur" and body.get("location"):
            save("boundary_bellandur", c.get(f"/api/explorer/locations/{body['location']['id']}/boundary"))
    save("change_hyderabad_official_built_up", c.post("/api/explorer/analysis/detect-change", json={"dataset_id": "ghsl-built-up-hyderabad", "start_year": 2000, "end_year": 2020}))
    save("change_himalayas_glacier", c.post("/api/explorer/analysis/detect-change", json={"dataset_id": "himalayas-dhauliganga", "start_year": 2001, "end_year": 2020, "params": {"variable": "glacier"}}))
    save("change_single_date_insufficient", c.post("/api/explorer/analysis/detect-change", json={"dataset_id": "worldcover-sundarbans-2021", "start_year": 2000, "end_year": 2024}))
    save("statistics_bellandur", c.get("/api/explorer/datasets/bellandur-lake/statistics"))
    save("catalogue", c.get("/api/explorer/catalogue"))


# ------------------------------------------------------------------------------------------ pieces
def official_windows(reg: dict) -> list[dict]:
    """Pixel-exact windows of the original rasters (the full files are too large to commit; their checksums are in the registry)."""
    out = EV / "03_ORIGINAL_SAMPLE_DATA/original_official_files"
    made = []
    for e in reg["entries"]:
        if e["verification_status"] != "VERIFIED_DOWNLOADED":
            continue
        p = ROOT / e["local_path"]
        if not p.exists():
            made.append({"id": e["id"], "note": "original not on disk; re-run scripts/download_official_data.py"})
            continue
        regions = e.get("used_by_regions") or []
        key = next((r for r in regions if r in REGION_BBOX), None)
        if p.suffix.lower() == ".geojson" or key is None:
            if p.stat().st_size < 10_000_000:
                cp(p, out / p.name)
                made.append({"id": e["id"], "file": p.name, "kind": "unmodified full original", "sha256": sha256(out / p.name)})
            continue
        src = f"zip://{p}!/{[n for n in __import__('zipfile').ZipFile(p).namelist() if n.lower().endswith('.tif')][0]}" if p.suffix == ".zip" else str(p)
        with rasterio.open(src) as s:
            w, so, ea, no = REGION_BBOX[key]
            win = from_bounds(w, so, ea, no, s.transform).round_offsets().round_lengths()
            data = s.read(window=win)
            prof = s.profile | {"driver": "GTiff", "height": data.shape[1], "width": data.shape[2], "transform": s.window_transform(win), "compress": "deflate", "tiled": False}
            prof.pop("blockxsize", None)
            prof.pop("blockysize", None)
            name = f"{Path(e.get('original_file_name', '')).stem}__window_{key}.tif"
            with rasterio.open(out / name, "w", **prof) as d:
                d.write(data)
                d.update_tags(SOURCE_FILE=e.get("original_file_name", ""), SOURCE_SHA256=e["sha256"], NOTE="pixel-exact window of the original official file; full-file checksum in source_registry.json")
        made.append({"id": e["id"], "file": name, "kind": "pixel-exact window of original", "window_region": key, "original_sha256": e["sha256"], "window_sha256": sha256(out / name)})
    write_json(out / "README.json", {"note": "Full originals are 22-80 MB each and are not committed. Each raster below is a pixel-exact window cut from the original (same values, CRS and dtype). The original file's SHA-256 is recorded in 02_OFFICIAL_SOURCES/source_registry.json; scripts/download_official_data.py re-downloads and verifies them.", "files": made})
    return made


def copy_processed() -> None:
    for d in datasets():
        root: Path = d["_dir"]
        for o in d["observations"]:
            cp(root / o["file"], EV / "04_PROCESSED_DATA/cog" / f"{d['id']}__{o['date']}.tif")
        for f in (root / "change").glob("*.difference.tif") if (root / "change").exists() else []:
            cp(f, EV / "04_PROCESSED_DATA/geotiff" / f"{d['id']}__{f.name}")
        for f in (root / "change").glob("*.hotspots.geojson") if (root / "change").exists() else []:
            cp(f, EV / "04_PROCESSED_DATA/geojson" / f"{d['id']}__{f.name}")
        if (root / "historical_statistics.csv").exists():
            cp(root / "historical_statistics.csv", EV / "04_PROCESSED_DATA/csv" / f"{d['id']}__historical_statistics.csv")
    gb = ATLAS / "geographical_boundaries"
    for sub in ("cities", "localities", "geographical_features"):
        for f in (gb / sub).glob("*.geojson"):
            cp(f, EV / "04_PROCESSED_DATA/geojson" / f"boundaries__{sub}__{f.name}")
    for n in ("change_summary.csv", "historical_statistics.csv", "dataset_catalogue.csv"):
        cp(DOC / n, EV / "04_PROCESSED_DATA/csv" / n)


def copy_visuals() -> None:
    pv = ATLAS / "previews"
    for d in datasets():
        for f in (pv / d["id"]).glob("*.png"):
            sub = "before_after" if f.name == "before_after.png" else "change_detection" if f.name.startswith("change_") else "historical_comparisons"
            cp(f, EV / "05_VISUAL_PROOF" / sub / f"{d['id']}__{f.name}")
    if (pv / "india_overview.png").exists():
        cp(pv / "india_overview.png", EV / "05_VISUAL_PROOF/india_overview/india_overview.png")


SCENARIOS = [
    ("1_search_and_suggest", "Type 'Bella' in the search box. Suggestions appear with name, hierarchy and type. Choose 'Bellandur Lake'.", "Globe flies to the lake; the outline shown is derived from JRC water occurrence (solid), never invented."),
    ("2_historical_analysis_bellandur", "Press Explore for 2002 to 2022. Open the Details tab.", "Illustrative Dataset badge; water, lake extent, aquatic vegetation, wetland and built-up can be selected under Measure. Lake change is modest and separate from the surroundings."),
    ("3_official_hyderabad", "Search 'Hyderabad', 2000 to 2020.", "Satellite Observations badge (GHSL built-up, epochs 2000, 2010, 2020). The timeline has three real dates."),
    ("4_himalayas", "Search 'Himalayas' or say 'Show the Himalayas'.", "Illustrative Dataset: glacier, snow, glacial lake and exposed terrain are separate measures."),
    ("5_no_history", "Search 'Chennai'.", "Place is shown; banner says Data Unavailable; no timeline, no analysis, no fictional history."),
    ("6_parent_area", "Search 'Uttarakhand'.", "No dataset covers the whole state; chips offer the dataset that exists inside it."),
    ("7_voice", "Press the microphone and say 'Compare this location between 2000 and 2020'.", "Same function as the Explore button runs; the confirmation text shows what was understood."),
    ("8_back_forward", "After two searches press Back, then Forward.", "Location, years, measure, map mode, timeline date and camera are restored."),
    ("9_insufficient", "Open the Sundarbans WorldCover dataset for 2000 to 2024.", "Single-date data: outcome is insufficient_data with a reason, never 'zero change'."),
]


def write_scenarios() -> None:
    d = EV / "07_APPLICATION_DEMO/demonstration_scenarios"
    write_json(d / "scenarios.json", [{"id": a, "steps": b, "expected": c} for a, b, c in SCENARIOS])
    (d / "README.md").write_text("# Demonstration scenarios\n\n" + "\n".join(f"## {a}\n\n**Do:** {b}\n\n**Expect:** {c}\n" for a, b, c in SCENARIOS), encoding="utf-8")


def evidence_report(reg: dict, val: dict) -> None:
    ds = datasets()
    off = [d for d in ds if d["designation"] != "illustrative"]
    ill = [d for d in ds if d["designation"] == "illustrative"]
    st: dict[str, int] = {}
    for e in reg["entries"]:
        st[e["verification_status"]] = st.get(e["verification_status"], 0) + 1
    md = f"""# NASAX evidence report

Generated {now_iso()}.

## What is official
- {len(off)} dataset(s) derived from official files: {', '.join(d['name'] for d in off)}. Label in the app: **Satellite Observations**.
- Official sources registered: {len(reg['entries'])} ({', '.join(f'{v} {k}' for k, v in st.items())}). Checksums are in `02_OFFICIAL_SOURCES/source_registry.json`.
- Boundaries: geoBoundaries ADM1 and ADM2 (36 states and union territories, 735 districts) plus lake outlines derived from JRC water occurrence and the Sundarbans mangrove from ESA WorldCover.

## What is illustrative
- {len(ill)} generated dataset(s): {', '.join(d['name'] for d in ill)}. Label in the app: **Illustrative Dataset**. They are demonstrations calibrated to real totals where official data exist, not satellite imagery. The Himalayas region is entirely illustrative.
- City, locality and landmark outlines are approximate areas (marked as such); they are not authoritative boundaries.

## What was not obtained
- No Landsat, Sentinel-2 or Bhuvan scenes were downloaded. Sources needing an account are recorded as ACCESS_REQUIRES_AUTHENTICATION; portal-only sources as VERIFIED_METADATA_ONLY.
- WorldCover 2021 is a single date, so it supports no change analysis (the app says so).

## Validation
{val['total']} automated checks: {val['summary']['pass']} passed, {val['summary']['warn']} warnings, {val['summary']['fail']} failed (`06_METHODOLOGY/validation_report.pdf`).

## How to reproduce
```
python scripts/generate_india_atlas.py --all
python scripts/generate_previews.py
python scripts/validate_datasets.py
python scripts/generate_evidence.py
```
"""
    (EV / "EVIDENCE_REPORT.md").write_text(md, encoding="utf-8")


def checksums() -> int:
    lines = []
    for p in sorted(EV.rglob("*")):
        if p.is_file() and p.name != "CHECKSUMS.sha256":
            lines.append(f"{sha256(p)}  {p.relative_to(EV).as_posix()}")
    (EV / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main() -> None:
    shots = EV / "07_APPLICATION_DEMO/screenshots"
    keep = {p: p.read_bytes() for p in shots.glob("*")} if shots.exists() else {}
    if EV.exists():
        shutil.rmtree(EV)
    for d in DIRS:
        (EV / d).mkdir(parents=True, exist_ok=True)
    for p, b in keep.items():
        (shots / p.name).write_bytes(b)
    reg = read_json(DOC / "source_registry.json")
    val = read_json(DOC / "validation_report.json")
    if not val:
        raise SystemExit("run scripts/validate_datasets.py first")
    for n in ("dataset_catalogue.csv", "dataset_catalogue.pdf"):
        cp(DOC / n, EV / "01_DATASET_CATALOGUE" / n)
    cp(ATLAS / "manifest.json", EV / "01_DATASET_CATALOGUE/manifest.json")
    cp(DOC / "source_registry.json", EV / "02_OFFICIAL_SOURCES/source_registry.json")
    with open(EV / "02_OFFICIAL_SOURCES/official_sources.csv", "w", newline="", encoding="utf-8") as fh:
        cols = ["id", "variable", "providing_organization", "official_dataset_url", "dataset_identifier", "original_file_name", "acquisition_or_temporal_coverage", "spatial_resolution", "license_or_terms", "download_url", "size_bytes", "sha256", "download_date", "verification_status", "verification_note"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(reg["entries"])
    provenance_pdf(DOC / "data_provenance_report.pdf", reg)
    cp(DOC / "data_provenance_report.pdf", EV / "02_OFFICIAL_SOURCES/data_provenance_report.pdf")
    official_windows(reg)
    copy_processed()
    copy_visuals()
    methodology_pdfs(reg, val)
    write_scenarios()
    sample_api_responses()
    evidence_report(reg, val)
    n = checksums()
    size = sum(p.stat().st_size for p in EV.rglob("*") if p.is_file())
    print(f"NASAX_JUDGE_EVIDENCE: {n} files, {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
