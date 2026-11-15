"""Run the backend change detection on every atlas dataset and variable and store the results.

For each dataset <d> and variable <v> this writes, under processed/<designation>/<region>/<dataset>/change/:
    <v>_<start>_<end>.summary.json      the full ChangeSummary (areas, hotspots, quality, limitations)
    <v>_<start>_<end>.hotspots.geojson  hotspot polygons with region / year / variable / change-type properties
    <v>_<start>_<end>.difference.tif    0 uncertain, 1 unchanged other, 2 unchanged class, 3 lost, 4 gained
and a combined documentation/change_summary.json plus documentation/change_summary.csv.

Nothing is hardcoded: every figure comes from backend/app/explorer/change.py applied to the observation rasters.
Run:  python scripts/detect_geographical_changes.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from atlas_common import ATLAS, DOC, now_iso, write_json  # noqa: E402
from app.config import Settings  # noqa: E402
from app.explorer.change import AnalysisRecord  # noqa: E402
from app.explorer.rendering import difference_geotiff  # noqa: E402
from app.explorer.schemas import ChangeParams  # noqa: E402
from app.explorer.services import ExplorerServices  # noqa: E402


def main() -> None:
    svc = ExplorerServices(Settings(explorer_dir=ATLAS / "processed", atlas_dir=ATLAS, explorer_generate_demo=False))
    rows: list[dict] = []
    combined: list[dict] = []
    for ds in svc.datasets.list():
        first = ds.observations[0].date.year
        last = ds.observations[-1].date.year
        out_dir = ds.root / "change"
        out_dir.mkdir(exist_ok=True)
        region = ds.root.parent.name if ds.root.parent.name not in ("synthetic", "official") else ds.root.name
        for v in ds.variables:
            res = svc.changes.detect(ds, first, last, ChangeParams(variable=v["key"]), ds.meta.get("location", {}).get("name"))
            summary = res.summary if isinstance(res, AnalysisRecord) else res
            stem = f"{v['key']}_{first}_{last}"
            data = summary.model_dump()
            data["designation"] = ds.meta.get("designation")
            data["data_designation_note"] = "illustrative (generated)" if ds.is_synthetic else "official-derived"
            write_json(out_dir / f"{stem}.summary.json", data)
            if isinstance(res, AnalysisRecord):
                feats = []
                for f in res.hotspot_geojson["features"]:
                    p = dict(f["properties"])
                    p.update(region_id=ds.id, start_year=first, end_year=last, variable=v["key"], change_type="loss" if p["kind"] == "loss" else "gain", data_designation=data["data_designation_note"])
                    feats.append({**f, "properties": p})
                write_json(out_dir / f"{stem}.hotspots.geojson", {"type": "FeatureCollection", "features": feats})
                tags = {"CLASSES": f"0=uncertain,1=unchanged other,2=unchanged {v['label']},3={v['label']} lost,4={v['label']} gained", "DATASET": ds.id, "VARIABLE": v["key"], "DESIGNATION": data["data_designation_note"]}
                (out_dir / f"{stem}.difference.tif").write_bytes(difference_geotiff(ds, res.diff, tags))
            a = summary.areas
            rows.append({
                "dataset_id": ds.id, "designation": ds.meta.get("designation"), "variable": v["key"], "start": first, "end": last, "outcome": summary.outcome, "confidence": summary.confidence or "",
                "initial_ha": a.get("water_start_ha", ""), "final_ha": a.get("water_end_ha", ""), "net_ha": a.get("net_ha", ""), "pct_net_change": a.get("pct_net_change", ""),
                "gained_ha": a.get("gained_ha", ""), "lost_ha": a.get("lost_ha", ""), "analysed_ha": a.get("analysed_ha", ""), "uncertain_ha": a.get("uncertain_ha", ""), "hotspots": len(summary.hotspots),
                "headline": summary.headline,
            })
            combined.append({"dataset_id": ds.id, "variable": v["key"], "start": first, "end": last, "outcome": summary.outcome, "areas": a, "headline": summary.headline, "insufficient": summary.insufficient.model_dump() if summary.insufficient else None})
            print(f"{ds.id:32s} {v['key']:20s} {first}-{last} {summary.outcome:18s} net={a.get('net_ha')} ha")
    write_json(DOC / "change_summary.json", {"generated_at": now_iso(), "method": "backend/app/explorer/change.py (same-season composites, geodesic areas, hotspot labelling)", "results": combined})
    with open(DOC / "change_summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} analyses")


if __name__ == "__main__":
    main()
