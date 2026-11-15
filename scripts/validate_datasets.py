"""Validate the atlas: structure, rasters, provenance, checksums, boundaries, labels and change results.

Writes documentation/validation_report.json (and prints a summary). Exit code 1 if any check FAILS; warnings do not fail.
Run:  python scripts/validate_datasets.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atlas_common import ATLAS, DOC, ROOT, now_iso, read_json, sha256, write_json  # noqa: E402

ALLOWED_STATUS = {"VERIFIED_DOWNLOADED", "VERIFIED_METADATA_ONLY", "ACCESS_REQUIRES_AUTHENTICATION", "NOT_ACCESSED"}
BOUNDARY_STATUS = {"authoritative_simplified", "derived_from_official_data", "administrative_proxy", "analysis_window", "approximate_bbox", "approximate_point"}
FORBIDDEN_PUBLIC = ("synthetic", "simulated")
REQUIRED = ["id", "name", "designation", "public_label", "source", "crs", "bbox", "classes", "variables", "coverage", "observations", "provenance"]

checks: list[dict] = []


def check(scope: str, name: str, ok: bool, detail: str = "", warn: bool = False) -> None:
    checks.append({"scope": scope, "check": name, "status": "pass" if ok else ("warn" if warn else "fail"), "detail": detail})


def validate_dataset(f: Path, registry: dict[str, dict]) -> None:
    d = read_json(f)
    root = f.parent
    sc = d.get("id", str(f))
    miss = [k for k in REQUIRED if k not in d]
    check(sc, "required metadata fields present", not miss, ", ".join(miss))
    pl = (d.get("public_label") or "").lower()
    check(sc, "public label never says synthetic or simulated", not any(w in pl for w in FORBIDDEN_PUBLIC), d.get("public_label", ""))
    check(sc, "public label matches designation", (d["designation"] == "illustrative") == (d["public_label"] == "Illustrative Dataset"), f"{d['designation']} / {d['public_label']}")
    if d["designation"] != "illustrative":
        check(sc, "official-derived dataset is not flagged as generated", not d.get("is_synthetic", False))
    dates = [o["date"] for o in d["observations"]]
    check(sc, "observation dates strictly increasing", dates == sorted(set(dates)), ", ".join(dates))
    shapes, classes = set(), set(map(int, d["classes"]))
    allowed = classes | {int(d.get("uncertain_value", 255))}
    for o in d["observations"]:
        p = root / o["file"]
        if not p.exists():
            check(sc, f"observation file exists: {o['file']}", False)
            continue
        with rasterio.open(p) as s:
            arr = s.read(1)
            shapes.add(arr.shape)
            vals = {int(v) for v in np.unique(arr)}
            check(sc, f"{o['date']} CRS is EPSG:4326", s.crs is not None and s.crs.to_epsg() == 4326, str(s.crs))
            check(sc, f"{o['date']} class codes all documented", vals <= allowed, f"undocumented: {sorted(vals - allowed)}")
            check(sc, f"{o['date']} tiled (cloud optimised layout)", bool(s.profile.get("tiled")), warn=True)
            valid = float((arr != d.get("uncertain_value", 255)).mean())
            check(sc, f"{o['date']} recorded valid fraction matches raster", abs(valid - o["valid_fraction"]) < 0.01, f"raster {valid:.3f} vs recorded {o['valid_fraction']}")
            check(sc, f"{o['date']} is not blank", len(vals - {int(d.get('uncertain_value', 255))}) >= 1)
            b = s.bounds
            check(sc, f"{o['date']} bounds match dataset bbox", all(abs(x - y) < 0.01 for x, y in zip([b.left, b.bottom, b.right, b.top], d["bbox"])), f"{tuple(round(v, 4) for v in b)}")
        prov = o.get("provenance") or {}
        if d["designation"] == "official_derived":
            sid = prov.get("source_id")
            reg = registry.get(sid or "")
            check(sc, f"{o['date']} source id is in the source registry", reg is not None, str(sid))
            if reg:
                check(sc, f"{o['date']} source was really downloaded", reg["verification_status"] == "VERIFIED_DOWNLOADED", reg["verification_status"])
                orig = ROOT / reg["local_path"] if reg.get("local_path") else None
                if orig and orig.exists():
                    check(sc, f"{o['date']} original file checksum matches the registry", sha256(orig) == reg["sha256"], reg["sha256"][:12])
                else:
                    check(sc, f"{o['date']} original file present locally", False, "re-run scripts/download_official_data.py", warn=True)
        else:
            check(sc, f"{o['date']} illustrative provenance says generated", prov.get("designation") == "illustrative" and "generated" in (prov.get("processing") or ""), str(prov.get("processing")))
    check(sc, "all observations share one grid", len(shapes) <= 1, str(shapes))
    check(sc, "variables reference documented classes", all(set(v["class"] if isinstance(v["class"], list) else [v["class"]]) <= classes for v in d["variables"]))
    check(sc, "exactly one primary variable", sum(1 for v in d["variables"] if v.get("primary")) == 1)
    for v in d["variables"]:
        cands = list((root / "change").glob(f"{v['key']}_*.summary.json"))
        check(sc, f"change analysis exists for {v['key']}", bool(cands), warn=True)
        for c in cands:
            s = read_json(c)
            a = s.get("areas") or {}
            if s["outcome"] == "insufficient_data":
                check(sc, f"{c.name}: insufficient data is not reported as zero change", not a.get("net_ha") and a.get("net_ha") != 0, str(a.get("net_ha")))
            else:
                check(sc, f"{c.name}: net change equals gained minus lost", abs((a.get("gained_ha") or 0) - (a.get("lost_ha") or 0) - (a.get("net_ha") or 0)) < 0.05, f"{a.get('gained_ha')} - {a.get('lost_ha')} = {a.get('net_ha')}")
                parts = (a.get("unchanged_water_ha") or 0) + (a.get("unchanged_land_ha") or 0) + (a.get("gained_ha") or 0) + (a.get("lost_ha") or 0) + (a.get("noise_filtered_ha") or 0)
                check(sc, f"{c.name}: changed, unchanged and noise-filtered areas add up to the analysed area", abs(parts - (a.get("analysed_ha") or 0)) < 1.0, f"{parts:.1f} vs {a.get('analysed_ha')}")
                if int(d.get("min_feature_px", 3)) == 1:
                    ok = abs((a.get("water_end_ha") or 0) - (a.get("water_start_ha") or 0) - (a.get("net_ha") or 0)) < 0.5
                    check(sc, f"{c.name}: no noise filter, so net change equals end minus start", ok, f"{a.get('water_start_ha')} -> {a.get('water_end_ha')} = {a.get('net_ha')}")
            txt = json.dumps(s).lower()
            check(sc, f"{c.name}: no forbidden public wording", "simulated demonstration" not in txt)


def validate_boundaries() -> None:
    bdir = ATLAS / "geographical_boundaries"
    idx = read_json(bdir / "index.json", {})
    check("boundaries", "index present", bool(idx))
    n = bad = 0
    for sub in ("countries", "states", "districts", "cities", "localities", "geographical_features"):
        for f in sorted((bdir / sub).glob("*.geojson")):
            data = read_json(f)
            check("boundaries", f"{sub}/{f.name} is a FeatureCollection", data.get("type") == "FeatureCollection")
            for ft in data["features"]:
                n += 1
                p = ft["properties"]
                ok = p.get("boundary_status") in BOUNDARY_STATUS and ft.get("geometry") is not None
                if ok:
                    g = shape(ft["geometry"])
                    ok = (not g.is_empty) and g.is_valid
                if not ok:
                    bad += 1
                    check("boundaries", f"feature {p.get('name')} ({sub}) valid", False, str(p.get("boundary_status")))
                if p.get("boundary_status") in {"approximate_bbox", "approximate_point", "analysis_window"}:
                    check("boundaries", f"{p.get('name')}: approximate outline is not labelled authoritative", not p.get("authoritative", False))
    check("boundaries", f"{n} features checked, geometry non-empty and valid, status known", bad == 0, f"{bad} problems")


def validate_registry() -> dict[str, dict]:
    reg = read_json(DOC / "source_registry.json", {"entries": []})
    out = {e["id"]: e for e in reg["entries"]}
    check("registry", "has entries", bool(out))
    for e in reg["entries"]:
        check("registry", f"{e['id']} status is one of the allowed values", e["verification_status"] in ALLOWED_STATUS, e["verification_status"])
        if e["verification_status"] == "VERIFIED_DOWNLOADED":
            p = ROOT / e["local_path"]
            check("registry", f"{e['id']} download has a checksum and size", bool(e.get("sha256")) and bool(e.get("size_bytes")))
            check("registry", f"{e['id']} file is on disk and unchanged", p.exists() and sha256(p) == e["sha256"], "re-run the downloader if missing", warn=not p.exists())
        else:
            check("registry", f"{e['id']} does not claim a checksum it did not compute", not e.get("sha256"))
    return out


def main() -> int:
    registry = validate_registry()
    for f in sorted((ATLAS / "processed").rglob("dataset.json")):
        validate_dataset(f, registry)
    validate_boundaries()
    for name in ("manifest.json",):
        check("package", f"{name} exists", (ATLAS / name).exists())
    for name in ("source_registry.json", "dataset_catalogue.csv", "dataset_catalogue.pdf", "historical_statistics.csv", "change_summary.json"):
        check("package", f"documentation/{name} exists", (DOC / name).exists())
    counts = {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "warn", "fail")}
    write_json(DOC / "validation_report.json", {"generated_at": now_iso(), "summary": counts, "total": len(checks), "failures": [c for c in checks if c["status"] == "fail"], "warnings": [c for c in checks if c["status"] == "warn"], "checks": checks})
    print(f"{len(checks)} checks: {counts['pass']} passed, {counts['warn']} warnings, {counts['fail']} failed")
    for c in checks:
        if c["status"] != "pass":
            print(f"  [{c['status'].upper()}] {c['scope']}: {c['check']} {c['detail']}")
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
