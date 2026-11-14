"""Verify the live CMR record for GPM_3IMERGM v07 and (optionally) download exactly one sample granule.

    python scripts/nasa_sample.py verify                      # CMR only, no credentials, no download
    python scripts/nasa_sample.py sample --month 2019-07      # downloads ONE granule (needs Earthdata login)
    python scripts/nasa_sample.py inspect --file <path>       # inspect an already downloaded granule

The data folder comes from EARTHTREND_NASA_DATA_DIR. Credentials come from the environment (EARTHDATA_USERNAME /
EARTHDATA_PASSWORD or EARTHDATA_TOKEN) and are never printed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.errors import AppError  # noqa: E402
from app.nasa import auth  # noqa: E402
from app.nasa.cmr import CmrClient, monthly_completeness  # noqa: E402
from app.nasa.config import DataLayout, resolve_data_dir  # noqa: E402
from app.nasa.download import Downloader  # noqa: E402
from app.nasa.inspect_hdf5 import inspect_granule, quality_report  # noqa: E402

SHORT, VERSION = "GPM_3IMERGM", "07"
EXPECTED_DOI = "10.5067/GPM/IMERG/3B-MONTH/07"


def verify(cmr: CmrClient) -> dict:
    coll = cmr.find_collection(SHORT, VERSION)
    umm = coll["umm"]
    granules, hits = cmr.granules(coll["concept_id"])
    comp = monthly_completeness(granules)
    versions = sorted({g.file_name.split(".")[-2] for g in granules})
    out = {
        "queried_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collection_concept_id": coll["concept_id"],
        "doi": umm.get("DOI", {}).get("DOI"),
        "doi_matches_expected": umm.get("DOI", {}).get("DOI") == EXPECTED_DOI,
        "version": umm.get("Version"),
        "file_version_labels": versions,
        "collection_temporal": umm["TemporalExtents"][0]["RangeDateTimes"][0],
        "granule_hits": hits,
        "first_granule": granules[0].granule_ur,
        "last_granule": granules[-1].granule_ur,
        "completeness": comp.__dict__ | {"complete": comp.complete},
        "total_cmr_size_mb": round(sum(g.size_mb or 0 for g in granules), 1),
    }
    return out, granules, coll


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["verify", "sample", "inspect"])
    ap.add_argument("--month", default="2019-07", help="YYYY-MM of the single sample granule")
    ap.add_argument("--file", help="path of a downloaded granule (inspect)")
    args = ap.parse_args()

    try:
        if args.command == "inspect":
            p = Path(args.file)
            print(json.dumps({"inspection": inspect_granule(p), "quality": quality_report(p)}, indent=2, default=str)[:20000])
            return 0

        cmr = CmrClient()
        v, granules, coll = verify(cmr)
        print(json.dumps(v, indent=2))
        if args.command == "verify":
            return 0

        g = next((x for x in granules if x.month_key == args.month), None)
        if g is None:
            print(f"No granule for {args.month} in CMR.", file=sys.stderr)
            return 2
        root = resolve_data_dir()
        layout = DataLayout(root).ensure()
        free_gb = shutil.disk_usage(root).free / 1e9
        print(json.dumps({"sample": {"granule_ur": g.granule_ur, "begin": g.begin, "end": g.end, "cmr_size_mb": g.size_mb, "url": g.https_url, "destination": str(layout.raw), "free_disk_gb": round(free_gb, 1)}}, indent=2))
        if free_gb < 1:
            print("Less than 1 GB free at the destination; stopping.", file=sys.stderr)
            return 2
        session = auth.earthdata_session()
        collection = {"concept_id": coll["concept_id"], "doi": v["doi"], "provider": coll["provider"], "title": coll["umm"].get("EntryTitle")}
        entry = Downloader(layout, session).download(g, SHORT, VERSION, collection)
        print(json.dumps({"downloaded": entry.__dict__}, indent=2))
        path = root / entry.relative_path
        insp = inspect_granule(path, cmr_size_mb=g.size_mb, granule_begin=g.begin, granule_end=g.end)
        qual = quality_report(path, granule_begin=g.begin)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = layout.reports / f"{SHORT}.{VERSION}.{args.month}.sample.{stamp}.json"
        out.write_text(json.dumps({"verify": v, "download": entry.__dict__, "inspection": insp, "quality": qual}, indent=2, default=str), encoding="utf-8")
        print(f"Report written to {out}")
        return 0 if insp["ok"] else 1
    except AppError as e:
        print(f"[{e.code}] {e.message}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
