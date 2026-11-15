"""Build (or rebuild) the India Historical Atlas end to end, then write its manifest and dataset catalogue.

    python scripts/generate_india_atlas.py             # manifest + catalogue only (fast; uses what is on disk)
    python scripts/generate_india_atlas.py --all       # every step, in order, including official downloads
    python scripts/generate_india_atlas.py --steps illustrative,boundaries,statistics

Steps (in order): official (download), illustrative (generated demonstration layers), process (official -> datasets),
boundaries, statistics, changes, manifest. A step that fails is reported and does not stop the others, because the app
must keep working when external data is unavailable. Adding a place = add a Region in backend/app/explorer/atlas.py or a
processing recipe in scripts/process_satellite_data.py, then re-run this script.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atlas_common import ATLAS, BACKEND, DOC, ROOT, now_iso, read_json, sha256, write_json  # noqa: E402

PY = sys.executable
SCRIPTS = ROOT / "scripts"
STEPS: dict[str, list[str]] = {
    "official": [PY, "-X", "utf8", str(SCRIPTS / "download_official_data.py")],
    "illustrative": [PY, "-X", "utf8", "-m", "app.explorer.atlas"],
    "process": [PY, "-X", "utf8", str(SCRIPTS / "process_satellite_data.py")],
    "boundaries": [PY, "-X", "utf8", str(SCRIPTS / "build_geographical_boundaries.py")],
    "statistics": [PY, "-X", "utf8", str(SCRIPTS / "calculate_historical_statistics.py")],
    "changes": [PY, "-X", "utf8", str(SCRIPTS / "detect_geographical_changes.py")],
}
FIELDS = ["dataset_id", "name", "region_folder", "designation", "public_label", "provider", "product", "license", "format", "crs", "resolution_m", "temporal_resolution", "observations", "first_date", "last_date", "variables", "bbox_w", "bbox_s", "bbox_e", "bbox_n", "path", "provenance_note"]


def run(step: str) -> bool:
    cwd = BACKEND if step == "illustrative" else ROOT
    print(f"\n=== {step} ===", flush=True)
    r = subprocess.run(STEPS[step], cwd=cwd)
    if r.returncode != 0:
        print(f"!! step '{step}' failed with exit code {r.returncode}; continuing")
    return r.returncode == 0


def dataset_files() -> list[Path]:
    return sorted(p for p in (ATLAS / "processed").rglob("dataset.json") if len(p.relative_to(ATLAS / "processed").parts) <= 4)


def build_manifest() -> list[dict]:
    rows: list[dict] = []
    entries: list[dict] = []
    for f in dataset_files():
        d = read_json(f)
        root = f.parent
        obs = d.get("observations", [])
        files = []
        for o in obs:
            fp = root / o["file"]
            if fp.exists():
                files.append({"date": o["date"], "file": str(fp.relative_to(ATLAS)).replace("\\", "/"), "bytes": fp.stat().st_size, "sha256": sha256(fp), "quality": o.get("quality"), "valid_fraction": o.get("valid_fraction")})
        b = d.get("bbox") or [None] * 4
        rel = str(root.relative_to(ATLAS)).replace("\\", "/")
        rows.append({
            "dataset_id": d["id"], "name": d["name"], "region_folder": root.parent.name if root.parent.name not in ("synthetic", "official") else root.name, "designation": d.get("designation"),
            "public_label": d.get("public_label"), "provider": d.get("source"), "product": d.get("product"), "license": d.get("license", "generated for NASAX, no third-party licence"), "format": d.get("format"),
            "crs": d.get("crs"), "resolution_m": d.get("resolution_m"), "temporal_resolution": d.get("temporal_resolution"), "observations": len(obs),
            "first_date": obs[0]["date"] if obs else "", "last_date": obs[-1]["date"] if obs else "", "variables": "; ".join(v["label"] for v in d.get("variables", [])),
            "bbox_w": b[0], "bbox_s": b[1], "bbox_e": b[2], "bbox_n": b[3], "path": rel, "provenance_note": (d.get("provenance") or {}).get("note", ""),
        })
        entries.append({"id": d["id"], "path": rel, "designation": d.get("designation"), "public_label": d.get("public_label"), "internal_origin": "generated (illustrative)" if d.get("is_synthetic") else "derived from official data",
                        "bbox": d.get("bbox"), "observation_files": files, "variables": d.get("variables", []),
                        "documents": {n: f"{rel}/{n}" for n in ("pipeline.json", "historical_statistics.json", "historical_statistics.csv", "ground_truth.json") if (root / n).exists()},
                        "change_products": sorted(str(p.relative_to(ATLAS)).replace("\\", "/") for p in (root / "change").glob("*")) if (root / "change").exists() else []})
    reg = read_json(DOC / "source_registry.json", {"entries": []})
    status: dict[str, int] = {}
    for e in reg["entries"]:
        status[e["verification_status"]] = status.get(e["verification_status"], 0) + 1
    bidx = read_json(ATLAS / "geographical_boundaries" / "index.json", {})
    write_json(ATLAS / "manifest.json", {
        "schema": "nasax-atlas-manifest-1", "name": "NASAX India Historical Atlas", "generated_at": now_iso(),
        "layout": {"synthetic": "generated clean-truth rasters and generator configs (internal origin, shown publicly as 'Illustrative Dataset')", "official": "original official files downloaded by scripts/download_official_data.py (not committed; re-download)",
                   "processed": "analysis-ready Cloud Optimized GeoTIFF datasets with dataset.json provenance", "geographical_boundaries": "GeoJSON boundaries by level", "documentation": "registry, catalogue, validation and provenance reports"},
        "datasets": entries, "official_source_status": status, "boundary_files": bidx.get("files", {}), "boundary_status_counts": bidx.get("status_counts", {}),
    })
    return rows


def write_catalogue(rows: list[dict]) -> None:
    DOC.mkdir(exist_ok=True)
    with open(DOC / "dataset_catalogue.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    small = st["BodyText"].clone("small", fontSize=7.5, leading=9)
    doc = SimpleDocTemplate(str(DOC / "dataset_catalogue.pdf"), pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24, title="NASAX dataset catalogue")
    story = [Paragraph("NASAX India Historical Atlas: dataset catalogue", st["Title"]), Paragraph(f"Generated {now_iso()}. Satellite Observations are derived from official files that are listed with checksums in the source registry. Illustrative Datasets are generated demonstration layers, not satellite imagery.", st["BodyText"]), Spacer(1, 8)]
    head = ["Dataset", "Label", "Provider / product", "Dates", "Obs", "Resolution", "Variables", "Licence"]
    data = [head] + [[Paragraph(r["name"], small), Paragraph(str(r["public_label"]), small), Paragraph(f"{r['provider']}<br/>{r['product']}", small), f"{r['first_date'][:4]}-{r['last_date'][:4]}", r["observations"], f"{float(r['resolution_m']):.0f} m", Paragraph(r["variables"], small), Paragraph(str(r["license"]), small)] for r in rows]
    t = Table(data, repeatRows=1, colWidths=[120, 70, 190, 52, 28, 50, 130, 120])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b2a4a")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(t)
    doc.build(story)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="run every step")
    ap.add_argument("--steps", default="", help="comma list of: " + ",".join(STEPS))
    a = ap.parse_args()
    chosen = list(STEPS) if a.all else [s for s in a.steps.split(",") if s]
    for s in chosen:
        if s not in STEPS:
            ap.error(f"unknown step {s}")
    failed = [s for s in chosen if not run(s)]
    print("\n=== manifest and catalogue ===")
    rows = build_manifest()
    write_catalogue(rows)
    print(f"{len(rows)} datasets catalogued; wrote manifest.json, documentation/dataset_catalogue.csv and .pdf")
    if failed:
        print("steps that failed:", ", ".join(failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(a if (a := main()) else 0)
