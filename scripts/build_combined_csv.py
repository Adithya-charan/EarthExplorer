"""One combined CSV of every atlas dataset: one row per dataset x observation date x class, with full metadata and provenance."""
import csv, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from atlas_common import ATLAS, DOC

OUT = DOC / "NASAX_COMBINED_DATASET.csv"
cols = ["dataset_id","dataset_name","state_folder","region_hint","product","provider","licence","designation","crs","resolution_m",
        "centre_lat","centre_lon","bbox_west","bbox_south","bbox_east","bbox_north",
        "observation_date","date_semantics","quality","valid_fraction","sensor","class_name","class_area_ha","is_tracked_variable",
        "source_file","source_sha256","source_download_url","original_temporal_coverage","processing_operations","limitation"]
rows = []
for f in sorted((ATLAS / "processed").rglob("dataset.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    loc = d.get("location", {}); b = d["bbox"]
    tracked = [v["label"].split()[0].lower() for v in d.get("variables", [])]
    for o in d["observations"]:
        p = o.get("provenance", {})
        for cname, ha in (o.get("class_area_ha") or {}).items():
            rows.append({
                "dataset_id": d["id"], "dataset_name": d["name"], "state_folder": f.parent.parent.name, "region_hint": loc.get("hint", ""),
                "product": d.get("product", ""), "provider": d.get("source", ""), "licence": d.get("license", ""), "designation": d.get("designation", ""),
                "crs": d.get("crs", ""), "resolution_m": d.get("resolution_m", ""), "centre_lat": loc.get("lat", ""), "centre_lon": loc.get("lon", ""),
                "bbox_west": b[0], "bbox_south": b[1], "bbox_east": b[2], "bbox_north": b[3],
                "observation_date": o["date"], "date_semantics": p.get("date_semantics", ""), "quality": o.get("quality", ""), "valid_fraction": o.get("valid_fraction", ""), "sensor": o.get("sensor", ""),
                "class_name": cname, "class_area_ha": ha, "is_tracked_variable": any(cname.lower().startswith(t) for t in tracked),
                "source_file": p.get("original_file", ""), "source_sha256": p.get("sha256", ""), "source_download_url": p.get("download_url", ""),
                "original_temporal_coverage": p.get("temporal_coverage", ""), "processing_operations": " | ".join(p.get("processing_operations", [])), "limitation": p.get("limitation", ""),
            })
with open(OUT, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
print(len(rows), "rows,", len({r["dataset_id"] for r in rows}), "datasets ->", OUT)
