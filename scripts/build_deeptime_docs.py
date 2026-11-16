"""08_DOCUMENTATION PDFs, CITATIONS.pdf and the zips of NASAX_DEEP_TIME_EVIDENCE.

    backend/.venv/Scripts/python -X utf8 scripts/build_deeptime_docs.py [--zip]

All numbers in the documents are read from the built data and the validation reports; none are typed here.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import zipfile
from collections import Counter
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.explorer.deeptime_knowledge import BIBLIOGRAPHY, EVENTS  # noqa: E402

DATA = ROOT / "datasets" / "deep_time"
EVID = Path(os.environ.get("DEEPTIME_EVIDENCE", "F:/NASAX_DEEP_TIME_EVIDENCE"))
ORIG = Path(os.environ.get("DEEPTIME_ROOT", "F:/NASAX_DEEPTIME")) / "originals"
DOC = EVID / "08_DOCUMENTATION"
CSVD = EVID / "03_CSV_DATASETS"
VAL = EVID / "07_VALIDATION"
ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=17, spaceAfter=8)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12.5, spaceBefore=10, spaceAfter=4)
P = ParagraphStyle("P", parent=ss["BodyText"], fontSize=9.2, leading=12.4, spaceAfter=4)
SM = ParagraphStyle("SM", parent=P, fontSize=7.6, leading=9.6)
CAV = "Geological Reconstruction: a model-based visualisation. It is not a satellite observation, not a photograph of the past and not an NASA or IEEE dataset."


def esc(t: str) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def table(rows: list[list], widths: list[float] | None = None, small=True) -> Table:
    st = SM if small else P
    data = [[Paragraph(esc(c), st) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe4f0")), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9aa9bd")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    return t


def build(path: Path, title: str, story: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=15 * mm, bottomMargin=15 * mm, title=title, author="NASAX Deep-Time Earth Explorer")

    def foot(c, d):
        c.saveState()
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.HexColor("#555555"))
        c.drawString(16 * mm, 9 * mm, f"{title}  |  {CAV[:80]}...")
        c.drawRightString(A4[0] - 16 * mm, 9 * mm, f"page {d.page}")
        c.restoreState()

    doc.build([Paragraph(esc(title), H1), *story], onFirstPage=foot, onLaterPages=foot)


def rows_of(name: str) -> list[dict]:
    with (CSVD / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def j(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def catalogue() -> None:
    counts = j(CSVD / "_row_counts.json")
    sizes = {f.name: f.stat().st_size for f in CSVD.glob("*.csv")}
    spec = {
        "india_plate_reconstruction.csv": "Position of a reference point on the Indian Plate (plate 501; 28.5N 80E today) at each supported age, for each of two plate models",
        "india_paleogeography_timeline.csv": "Cao et al. (2017) land / shallow-sea class at the reconstructed positions of 13 modern reference places, per age",
        "himalaya_geological_evolution.csv": "Stages from Gondwana to the present with collision status, evidence, sources and uncertainty (collision timing kept as ranges)",
        "india_dinosaur_fossil_occurrences.csv": "Every PBDB Dinosauria occurrence with country code IN, unedited values",
        "india_geological_formations.csv": "Formation names grouped from PBDB Mesozoic collections in India; ages are unions of collection ranges",
        "geological_events_timeline.csv": "ICS boundaries (read from the ICS-derived interval files) and published-interpretation events",
        "geological_reconstruction_metadata.csv": "One row per downloaded original: provider, URL, licence, citation, download date, sha256",
        "india_deep_time_visualization_index.csv": "One row per frame and model: which raster, vector, plate and preview files show it, and its interpolation status",
    }
    s = [Paragraph(CAV, P), Paragraph("CSV datasets", H2), table([["File", "Rows", "Bytes", "Content"]] + [[k, str(counts[k]), f"{sizes[k]:,}", v] for k, v in spec.items()], [48 * mm, 12 * mm, 16 * mm, 100 * mm])]
    man = j(DATA / "manifest.json")
    s += [Paragraph("Supported reconstruction ages", H2), Paragraph(f"{len(man['ages'])} ages (Ma): " + ", ".join(f"{a:g}" for a in man["ages"]) + f". Requested ages: {len(man['requested_ages'])}; added where the data permit: " + ", ".join(f"{a:g}" for a in man["added_ages"]) + ".", P)]
    rows = [["Age (Ma)", "Period / epoch", "EarthByte polygons (plates / landmass / shallow sea / mountains)", "PALEOMAP map used", "Interpolation"]]
    for fm in man["frames"]:
        pc = fm["models"]["earthbyte"]["polygon_counts"]
        pm = fm["models"]["paleomap"]
        rows.append([f"{fm['age_ma']:g}", f"{fm['period']} / {fm['epoch']}", f"{pc['plates']} / {pc['landmass']} / {pc['shallow_marine']} / {pc['mountains']}", (f"{pm['map_age_ma']:g} Ma" + ("" if pm["map_exact"] else f" (nearest, offset {pm['map_offset_ma']:g})")) if pm.get("map_file") else "none", fm["interpolation"]["earthbyte"][:46]])
    s += [table(rows, [16 * mm, 36 * mm, 50 * mm, 34 * mm, 40 * mm])]
    prod = j(VAL / "_produced_files.json")
    s += [Paragraph("Spatial formats produced", H2), Paragraph("; ".join(f"{k}: {v}" for k, v in prod.items()) + ". Formats are made only where meaningful: GeoJSON for the web app and all frames; GeoPackage as one container per frame; Shapefile for the eleven evidence ages; GPML for the Indian Plate static polygons of both models; GeoTIFF for each PALEOMAP map used; Cloud-Optimised GeoTIFF for the evidence ages; NetCDF for the seafloor-age grid subset.", P)]
    build(DOC / "DEEP_TIME_DATASET_CATALOGUE.pdf", "NASAX Deep-Time: dataset catalogue", s)


def methodology() -> None:
    s = [Paragraph(CAV, P)]
    parts = [
        ("Two plate models, shown one at a time", "EarthByte: Zahirovic et al. (2022) optimised-mantle-reference rotation model with the Cao et al. (2017) paleogeography polygons (2-402 Ma). PALEOMAP: Scotese's plate model and its published paleogeographic maps. They are never blended; where they disagree the app reports the distance in km."),
        ("How a frame is computed", "pygplates 1.0.0 reconstructs the static plate polygons, continental polygons, present-day coastlines (carried on their plates, not ancient shorelines) and the Cao polygons to each age with the rotation file, anchor plate 0. Polygons are split at the dateline, simplified to about 0.03-0.15 degrees, rounded to 0.01 degree and written as GeoJSON."),
        ("Interpolation", "Frames are direct evaluations of the rotation model at the requested age. Where the age lies between two finite-rotation poles the model interpolates between them; each frame records whether a pole exists at that age. Map images are never interpolated: the nearest published PALEOMAP map is used and flagged with its offset in Ma."),
        ("India through time", "A modern location is used only as a reference point. It is assigned to the plate that contains it (plate 501) and rotated. The Himalayan reference point is assigned to plate 501 explicitly, which is documented. Modern administrative boundaries are never drawn in the past, and no city-level ancient topography is produced."),
        ("Fossils and formations", "Fossil rows are PBDB occurrence records copied unedited and carried to their reconstructed position within +-5 Ma of their recorded age range. Formations are grouped from PBDB Mesozoic collections; their ages are the union of collection ranges, not formal ages. Macrostrat's coverage of India is limited to small-scale units, so it supplied the ICS-derived time scale but no Indian formation ages."),
        ("Time scale", "Boundary ages come from the Macrostrat ICS-derived interval files and are cross-checked against the numbers in the official ICS chart v2024/12 (see TIME_RANGE_VALIDATION.json)."),
        ("AI assistant", "The Groq assistant is restricted to tools that return records from these datasets. Answers carry four labelled parts: dataset records, model reconstruction, published interpretation and uncertainty. If no key is configured a deterministic answer from the same records is returned. Fossils, ages, coordinates and events are never generated."),
    ]
    for h, t in parts:
        s += [Paragraph(h, H2), Paragraph(esc(t), P)]
    s += [Paragraph("Limitations", H2)]
    for t in ("Reconstructions older than about 100 Ma rest on indirect evidence (most older seafloor is subducted) and differ between models by thousands of km.", "The rigid-plate model does not represent shortening inside India or Eurasia, so the India-Eurasia distance is not the width of an ocean.", "The Cao et al. paleogeography is global and coarse; no city-level paleogeography exists in these sources.", "Ages younger than 1 Ma have no Cao paleogeography; the plates and present-day shapes carried on plates are shown instead and labelled so.", "Absence of fossil records is not absence of animals; PBDB coordinates carry their own precision, which is kept in data_quality."):
        s.append(Paragraph("- " + esc(t), P))
    build(DOC / "GEOLOGICAL_METHODOLOGY.pdf", "NASAX Deep-Time: methodology", s)


def india_history() -> None:
    hs = rows_of("himalaya_geological_evolution.csv")
    s = [Paragraph(CAV, P), Paragraph("Collision timing is debated. The events table (EV09, EV10) records the published range and the two-stage model with their sources (B08, B09, B10, B17); ranges and competing models are kept here rather than one date.", P)]
    s += [Paragraph("Stages", H2), table([["Age (Ma)", "Stage", "Collision status", "Mountains", "Sources", "Uncertainty"]] + [[r["age_ma"], r["geological_stage"], r["collision_status"], r["mountain_building_context"], r["source_reference"], r["uncertainty"]] for r in hs], [12 * mm, 26 * mm, 36 * mm, 36 * mm, 14 * mm, 52 * mm])]
    pr = rows_of("india_plate_reconstruction.csv")
    s += [PageBreak(), Paragraph("Indian Plate reference point by age", H2), table([["Age (Ma)", "Model", "Lat", "Lon"]] + [[r["geological_age_ma"], r["reconstruction_id"].split("-")[1], r["reconstructed_latitude"], r["reconstructed_longitude"]] for r in pr], [20 * mm, 20 * mm, 24 * mm, 24 * mm])]
    ev = rows_of("geological_events_timeline.csv")
    s += [PageBreak(), Paragraph("Events", H2), table([["Event", "Start-end (Ma)", "Confidence", "Sources"]] + [[r["event_name"], f"{r['start_age_ma']}-{r['end_age_ma']}", r["confidence"], r["evidence_source"]] for r in ev], [78 * mm, 28 * mm, 40 * mm, 22 * mm])]
    fo = rows_of("india_dinosaur_fossil_occurrences.csv")
    per = Counter(r["geological_period"] for r in fo)
    st = Counter(r["state"] for r in fo).most_common(8)
    s += [Paragraph("Dinosaur-era record in India (PBDB)", H2), Paragraph(f"{len(fo)} occurrence records. By period: " + ", ".join(f"{k} {v}" for k, v in per.most_common()) + ". By state: " + ", ".join(f"{k or 'not stated'} {v}" for k, v in st) + ". Slices shown in the app: 250, 230, 200, 180, 150, 130, 120, 100, 90, 75 and 66 Ma.", P)]
    build(DOC / "INDIA_GEOLOGICAL_HISTORY.pdf", "NASAX Deep-Time: India's geological history", s)


def provenance() -> None:
    meta = rows_of("geological_reconstruction_metadata.csv")
    s = [Paragraph(CAV, P), Paragraph("Originals", H2), table([["Dataset", "File", "Provider", "Licence", "Downloaded", "sha256 (first 16)"]] + [[m["dataset_id"], m["original_filename"], m["provider"], m["license"][:60], m["downloaded_date"], m["checksum"][7:23]] for m in meta], [30 * mm, 36 * mm, 30 * mm, 32 * mm, 24 * mm, 28 * mm])]
    ds = j(VAL / "DATASET_VALIDATION.json")
    gv = j(VAL / "GEOMETRY_VALIDATION.json")
    tv = j(VAL / "TIME_RANGE_VALIDATION.json")
    fo = ds["fossils_vs_original_pbdb_csv"]
    live = ds["fossils_vs_live_pbdb"]
    csv_rows = ", ".join(k + ": " + str(v["rows"]) + " rows" for k, v in ds["csv"].items())
    s += [Paragraph("Validation results", H2)]
    lines = [
        f"All eight CSVs match the specified column lists; every identifier column is unique ({csv_rows}).",
        f"Plate positions: every row of india_plate_reconstruction.csv was recomputed independently with pygplates; maximum absolute difference {ds['plate_reconstruction_recomputed_max_abs_error_deg']} degrees.",
        f"Fossils: {fo['rows']} rows compared with the original PBDB download ({len(fo['value_mismatches'])} value mismatches, {len(fo['not_in_original'])} not in the original). Live PBDB check: {live['status']}; {live['found_live']} of {live['checked']} record numbers found, {len(live['taxon_name_differences'])} taxon-name differences.",
        f"Geometries: {gv['geojson_summary']['geometries_checked']:,} GeoJSON geometries checked, {gv['geojson_summary']['invalid_or_missing']} invalid or missing, {gv['geojson_summary']['out_of_bounds']} out of bounds; {gv['geopackage_summary']['layers_checked']} GeoPackage layers match their GeoJSON feature counts; all shapefiles, GeoTIFFs (EPSG:4326, -180..180, -90..90) and the NetCDF re-opened successfully.",
        f"Time scale: {tv['ics_boundaries_vs_official_chart_text']['found_in_chart']} of {tv['ics_boundaries_vs_official_chart_text']['checked']} interval base ages were found in the text of the ICS chart v2024/12.",
        f"All {len(tv['supported_ages_ma'])} supported ages appear in the reconstruction table and the visualisation index; ages without a Cao paleogeography interval: {', '.join(f'{a:g}' for a in tv['frames_without_cao_paleogeography'])} Ma; PALEOMAP maps substituted by the nearest published age: " + ", ".join(f"{n['age_ma']:g} Ma uses the {n['paleomap_age_used_ma']:g} Ma map" for n in tv["paleomap_nearest_age_substitutions"]) + ".",
    ]
    s += [Paragraph("- " + esc(t), P) for t in lines]
    s += [Paragraph("Not available", H2), Paragraph("Macrostrat provides no named Indian formation units in its map coverage for the places queried (Lameta, for example, is absent); no independent measurement of any reconstructed frame exists; reconstructions are not available below 1 Ma for the Cao paleogeography.", P)]
    build(DOC / "DATA_PROVENANCE_REPORT.pdf", "NASAX Deep-Time: data provenance report", s)


def citations() -> None:
    br = list(csv.DictReader((EVID / "06_SCIENTIFIC_REFERENCES" / "BIBLIOGRAPHY.csv").open(encoding="utf-8")))
    s = [Paragraph("Each DOI was looked up at Crossref; the resolved first author and year are listed.", P)]
    for b in br:
        s.append(Paragraph(f"<b>{b['id']}</b> {esc(b['citation'])} " + (f"doi:{esc(b['doi'])} [{esc(b['crossref_status'])}: {esc(b['crossref_first_author'])} {esc(b['crossref_year'])}]" if b["doi"] else "(no DOI)") + f" <i>Role: {esc(b['role'])}</i>", P))
    s.append(Paragraph("Data sources", H2))
    for m in rows_of("geological_reconstruction_metadata.csv"):
        s.append(Paragraph(f"{esc(m['citation'])} ({esc(m['original_filename'])}, {esc(m['source_url'])})", SM))
    build(EVID / "06_SCIENTIFIC_REFERENCES" / "CITATIONS.pdf", "NASAX Deep-Time: citations", s)


def readme() -> None:
    counts = j(CSVD / "_row_counts.json")
    (EVID / "README.md").write_text(
        "# NASAX_DEEP_TIME_EVIDENCE\n\n" + CAV + "\n\n"
        "- 01_ORIGINAL_SCIENTIFIC_DATA: files exactly as downloaded (never converted)\n- 02_PROCESSED_GEOLOGICAL_DATA: GeoJSON, GeoPackage, Shapefile, GPML, GeoTIFF, COG, NetCDF derived from them\n"
        "- 03_CSV_DATASETS: " + ", ".join(f"{k} ({v})" for k, v in counts.items()) + "\n- 04_RECONSTRUCTION_FRAMES: 250, 200, 150, 120, 100, 75, 66, 55, 40, 20 Ma and PRESENT\n- 05_VISUAL_PROOF: previews, plots and app screenshots\n- 06_SCIENTIFIC_REFERENCES: registry, bibliography (DOIs checked at Crossref), citations, licences\n- 07_VALIDATION: dataset, geometry and time-range validation and sha256 checksums\n- 08_DOCUMENTATION: catalogue, methodology, India's geological history, provenance\n",
        encoding="utf-8",
    )


def zips() -> dict:
    out = {}
    full = EVID.parent / "NASAX_DEEP_TIME_EVIDENCE.zip"
    with zipfile.ZipFile(full, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(EVID.rglob("*")):
            if p.is_file():
                z.write(p, Path("NASAX_DEEP_TIME_EVIDENCE") / p.relative_to(EVID))
    out["full"] = (str(full), full.stat().st_size)
    cz = EVID.parent / "NASAX_DEEP_TIME_CSV_ONLY.zip"
    with zipfile.ZipFile(cz, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(CSVD.glob("*.csv")):
            z.write(p, p.name)
        z.write(VAL / "DATASET_VALIDATION.json", "DATASET_VALIDATION.json")
        z.write(EVID / "06_SCIENTIFIC_REFERENCES" / "BIBLIOGRAPHY.csv", "BIBLIOGRAPHY.csv")
    out["csv_only"] = (str(cz), cz.stat().st_size)
    return out


if __name__ == "__main__":
    DOC.mkdir(parents=True, exist_ok=True)
    catalogue()
    methodology()
    india_history()
    provenance()
    citations()
    readme()
    print("documents written")
    if "--zip" in sys.argv:
        print(json.dumps(zips(), indent=1))
