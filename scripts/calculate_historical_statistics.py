"""Per-dataset historical statistics (class areas per observation, per-variable series, zone breakdowns).

Writes processed/<designation>/<region>/<dataset>/historical_statistics.json plus region CSVs and the combined
documentation/historical_statistics.csv. Computed by backend/app/explorer/stats.py from the observation rasters.
Only variables that exist in a dataset appear; nothing is filled in.
Run:  python scripts/calculate_historical_statistics.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from atlas_common import ATLAS, DOC, now_iso, write_json  # noqa: E402
from app.config import Settings  # noqa: E402
from app.explorer.services import ExplorerServices  # noqa: E402

FIELDS = ["dataset_id", "designation", "date", "variable", "label", "area_ha", "share_of_valid_pct", "zone", "nodata_pct", "quality"]


def main() -> None:
    svc = ExplorerServices(Settings(explorer_dir=ATLAS / "processed", atlas_dir=ATLAS, explorer_generate_demo=False))
    allrows: list[dict] = []
    for ds in svc.datasets.list():
        st = svc.statistics(ds)
        st["generated_at"] = now_iso()
        write_json(ds.root / "historical_statistics.json", st)
        rows: list[dict] = []
        obs = {o["date"]: o for o in st["observations"]}
        for key, v in st["variables"].items():
            for p in v["series"]:
                o = obs.get(p["date"], {})
                rows.append({"dataset_id": ds.id, "designation": st["designation"], "date": p["date"], "variable": key, "label": v["label"], "area_ha": p["area_ha"], "share_of_valid_pct": p["share_of_valid_pct"], "zone": "whole footprint", "nodata_pct": o.get("nodata_pct", ""), "quality": o.get("quality", "")})
        for zone, d in (st.get("zones") or {}).items():
            for key, v in d.items():
                for p in v["series"]:
                    rows.append({"dataset_id": ds.id, "designation": st["designation"], "date": p["date"], "variable": key, "label": v["label"], "area_ha": p["area_ha"], "share_of_valid_pct": p["share_of_valid_pct"], "zone": zone, "nodata_pct": "", "quality": ""})
        with open(ds.root / "historical_statistics.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        allrows += rows
        print(f"{ds.id}: {len(st['observations'])} observations, {len(st['variables'])} variables, {len(rows)} rows")
    with open(DOC / "historical_statistics.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(allrows)
    print(f"wrote {len(allrows)} rows to documentation/historical_statistics.csv")


if __name__ == "__main__":
    main()
