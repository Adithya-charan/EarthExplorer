"""Historical statistics per dataset, computed from the observation rasters (never typed in).

Areas use the dataset's per-row geodesic pixel area. Cloud / no-data pixels are excluded from the denominators and
reported separately, so a missing observation is never read as "zero".
"""

from __future__ import annotations

from typing import Any

import numpy as np
import rasterio

from app.errors import AppError
from app.explorer.datasets import Dataset, DatasetService
from app.explorer.geoutil import area_ha


def _label(ds: Dataset, code: int) -> str:
    return str(ds.meta.get("classes", {}).get(str(code), f"class {code}"))


def dataset_statistics(svc: DatasetService, ds: Dataset) -> dict[str, Any]:
    rows = ds.row_area_m2
    assert rows is not None
    U = ds.uncertain
    zone = None
    zinfo = ds.meta.get("zones")
    if zinfo:
        try:
            with rasterio.open(ds.root / zinfo["file"]) as z:
                zone = z.read(1)
            if zone.shape != (ds.height, ds.width):
                zone = None
        except Exception:
            zone = None
    obs_out: list[dict[str, Any]] = []
    series: dict[str, list[dict[str, Any]]] = {v["key"]: [] for v in ds.variables}
    zseries: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for o in ds.observations:
        entry: dict[str, Any] = {"date": o.iso, "quality": o.quality, "valid_fraction": round(o.valid_fraction, 4)}
        try:
            a = svc.read(ds, o)
        except AppError as exc:
            entry.update(readable=False, problem=exc.message)
            obs_out.append(entry)
            continue
        valid = a != U
        total = area_ha(np.ones_like(valid), rows)
        vh = area_ha(valid, rows)
        entry.update(
            readable=True, footprint_ha=round(total, 2), valid_ha=round(vh, 2), nodata_ha=round(area_ha(~valid, rows), 2), nodata_pct=round(100 * (1 - float(valid.mean())), 2),
            class_area_ha={_label(ds, int(c)): round(area_ha(a == c, rows), 2) for c in np.unique(a) if c != U},
        )
        for v in ds.variables:
            m = np.isin(a, v["class"]) & valid
            ha = area_ha(m, rows)
            series[v["key"]].append({"date": o.iso, "area_ha": round(ha, 2), "share_of_valid_pct": round(100 * ha / vh, 3) if vh else None})
            if zone is not None:
                for zv, zname in ((1, "inside lake basin"), (0, "surroundings")):
                    zm = zone == zv
                    zvalid = area_ha(valid & zm, rows)
                    zha = area_ha(m & zm, rows)
                    zseries.setdefault(zname, {}).setdefault(v["key"], []).append({"date": o.iso, "area_ha": round(zha, 2), "share_of_valid_pct": round(100 * zha / zvalid, 3) if zvalid else None})
        obs_out.append(entry)
    variables: dict[str, Any] = {}
    for v in ds.variables:
        s = series[v["key"]]
        item: dict[str, Any] = {"label": v["label"], "classes": v["class"], "primary": v["primary"], "series": s}
        if len(s) >= 2:
            first, last = s[0], s[-1]
            net = last["area_ha"] - first["area_ha"]
            item.update(first_date=first["date"], last_date=last["date"], net_change_ha=round(net, 2), net_change_pct=None if first["area_ha"] == 0 else round(100 * net / first["area_ha"], 2))
        variables[v["key"]] = item
    out: dict[str, Any] = {
        "dataset_id": ds.id, "name": ds.meta["name"], "designation": ds.meta.get("designation", "illustrative" if ds.is_synthetic else "official"), "public_label": ds.meta.get("public_label"),
        "method": "Per-observation class areas from the classified rasters using geodesic pixel areas; cloud and no-data pixels are excluded from shares and reported as no-data.",
        "observations": obs_out, "variables": variables,
    }
    if zseries:
        out["zones"] = {z: {k: {"label": variables[k]["label"], "series": s} for k, s in d.items()} for z, d in zseries.items()}
        out["zones_note"] = "Inside lake basin versus surroundings, so changes within the lake are reported apart from changes around it."
    return out
