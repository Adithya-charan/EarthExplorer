"""ChangeDetectionService: same-season water-extent change between two periods, with honest outcomes.

Outcomes
    change_detected    gross change above the thresholds, at least one hotspot, larger than year-to-year scatter
    no_clear_change    enough usable data, but nothing exceeds the thresholds (or it is within normal scatter)
    insufficient_data  not enough usable same-season observations in one or both periods (never reported as "no change")

Method (all numbers come from the rasters; nothing is typed in):
    1. Both ends of the requested period are reduced to *same-season composites*: only calendar months that have a
       usable observation in both windows are used, so a wet-season picture is never compared with a dry-season one.
    2. A pixel is water in a composite when it is water in >= ``water_frequency`` of its valid observations; pixels without
       enough valid observations (cloud / gaps) are uncertain and are excluded from every area.
    3. Gain / loss / unchanged masks come from the two composites on one common grid. Features narrower than
       ``min_feature_px`` pixels are treated as positional noise and removed.
    4. Areas use per-row geodesic pixel areas (never raw degrees); hotspot polygons are re-measured in a local UTM CRS.
    5. Year-by-year composites give the progression, a Theil-Sen trend and the year-to-year scatter used as a noise test.
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from rasterio.features import shapes
from scipy import ndimage as ndi
from scipy import stats
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from app.errors import AppError
from app.explorer.datasets import Dataset, DatasetService, Obs
from app.explorer.geoutil import area_ha, compass
from app.explorer.rendering import D_GAIN, D_LAND, D_LOSS, D_UNCERTAIN, D_WATER
from app.explorer.schemas import ChangeParams, ChangeSummary, DatasetInfo, Hotspot, Insufficient, PeriodCheck, ProgressionPoint

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
S8 = np.ones((3, 3), dtype=bool)


@dataclass
class AnalysisRecord:
    id: str
    dataset_id: str
    summary: ChangeSummary
    diff: np.ndarray | None = None
    w0: np.ndarray | None = None
    ok0: np.ndarray | None = None
    w1: np.ndarray | None = None
    ok1: np.ndarray | None = None
    hotspot_geojson: dict[str, Any] = field(default_factory=lambda: {"type": "FeatureCollection", "features": []})


# ----------------------------------------------------------------------------- period handling
def coverage_years(ds: Dataset) -> tuple[int, int]:
    return int(ds.meta["coverage"]["start"][:4]), int(ds.meta["coverage"]["end"][:4])


def check_period(ds: Dataset, start_year: int, end_year: int) -> PeriodCheck:
    cs, ce = coverage_years(ds)
    req = {"start_year": start_year, "end_year": end_year}
    supported = dict(ds.meta["coverage"])
    msgs: list[str] = []
    if end_year < cs or start_year > ce:
        msgs.append(f"{ds.meta['name']} has observations only from {supported['start'][:7]} to {supported['end'][:7]}; nothing falls inside {start_year}–{end_year}.")
        msgs.append(f"Choose a period inside {cs}–{ce}.")
        return PeriodCheck(requested=req, supported=supported, effective=None, status="outside", messages=msgs)
    es, ee = max(start_year, cs), min(end_year, ce)
    if es >= ee:
        msgs.append(f"Only {es} overlaps the dataset ({cs}–{ce}), which is too short to compare two periods.")
        return PeriodCheck(requested=req, supported=supported, effective={"start_year": es, "end_year": ee}, status="too_short", messages=msgs)
    if (es, ee) != (start_year, end_year):
        msgs.append(f"The dataset covers {cs}–{ce}, so the analysis uses {es}–{ee} instead of {start_year}–{end_year}. Nothing was estimated for the missing years.")
        return PeriodCheck(requested=req, supported=supported, effective={"start_year": es, "end_year": ee}, status="clipped", messages=msgs)
    return PeriodCheck(requested=req, supported=supported, effective={"start_year": es, "end_year": ee}, status="ok", messages=[])


def dataset_info(svc: DatasetService, ds: Dataset) -> DatasetInfo:
    m = ds.meta
    return DatasetInfo(
        id=ds.id, name=m["name"], description=m.get("description", ""), is_synthetic=ds.is_synthetic, simulated_label=m.get("simulated_label"),
        source=m.get("source", "unknown"), product=m.get("product", ""), format=m.get("format", ""), crs=str(m.get("crs", "")),
        resolution_m=float(m.get("resolution_m", 0.0)), temporal_resolution=m["temporal_resolution"], bbox=ds.bbox, coverage=dict(m["coverage"]),
        observation_count=len(ds.observations), usable_count=len(svc.usable(ds)), classes=dict(m.get("classes", {})),
        real_dataset_targets=list(m.get("real_dataset_targets", [])), issues=list(ds.issues),
    )


# ----------------------------------------------------------------------------------- helpers
def _composite(arrs: list[np.ndarray], water_class: int, uncertain: int, freq: float, min_obs_fraction: float) -> tuple[np.ndarray, np.ndarray]:
    stack = np.stack(arrs)
    valid = stack != uncertain
    vc = valid.sum(axis=0)
    wc = ((stack == water_class) & valid).sum(axis=0)
    ok = vc >= max(1, math.ceil(min_obs_fraction * len(arrs)))
    water = ok & (wc >= freq * np.maximum(vc, 1))
    return water, ok


def _clean(mask: np.ndarray, min_feature_px: int) -> np.ndarray:
    """Remove features narrower than ``min_feature_px`` pixels (positional noise) and tiny specks."""
    if not mask.any():
        return mask
    k = max(1, min_feature_px - 1)
    out = ndi.binary_opening(mask, structure=np.ones((k, k), dtype=bool)) if k > 1 else mask
    labels, n = ndi.label(out, structure=S8)
    if n:
        sizes = ndi.sum(out, labels, index=np.arange(1, n + 1))
        small = np.isin(labels, np.where(sizes < min_feature_px * min_feature_px)[0] + 1)
        out = out & ~small
    return out


def _fmt_months(months: list[int]) -> str:
    return ", ".join(MONTHS[m - 1] for m in sorted(months))


def _window_obs(ds: Dataset, svc: DatasetService, years: range, min_valid: float) -> tuple[list[Obs], list[str]]:
    """Usable observations in the window plus a plain-language list of what was excluded and why."""
    use: list[Obs] = []
    notes: list[str] = []
    for o in ds.observations:
        if o.date.year not in years:
            continue
        if o.broken:
            notes.append(f"{o.iso[:7]}: file could not be read")
        elif o.valid_fraction < min_valid:
            notes.append(f"{o.iso[:7]}: only {o.valid_fraction:.0%} of pixels were valid (minimum {min_valid:.0%})")
        else:
            use.append(o)
    return use, notes


def _lonlat_transformer(ds: Dataset):
    return None if ds.crs.is_geographic else Transformer.from_crs(ds.crs, 4326, always_xy=True)


def _pix_lonlat(ds: Dataset, rows: np.ndarray, cols: np.ndarray, tr) -> tuple[float, float]:
    x = ds.transform.c + (cols.mean() + 0.5) * ds.transform.a
    y = ds.transform.f + (rows.mean() + 0.5) * ds.transform.e
    if tr is not None:
        x, y = tr.transform(x, y)
    return float(x), float(y)


# ----------------------------------------------------------------------------------- service
class ChangeDetectionService:
    def __init__(self, datasets: DatasetService, cache_size: int = 24):
        self.datasets = datasets
        self._cache: OrderedDict[str, AnalysisRecord] = OrderedDict()
        self._size = cache_size
        self._lock = threading.Lock()

    def get(self, analysis_id: str) -> AnalysisRecord:
        with self._lock:
            rec = self._cache.get(analysis_id)
            if rec is not None:
                self._cache.move_to_end(analysis_id)
        if rec is None:
            raise AppError(404, "analysis_not_found", "That analysis is no longer in memory. Run the change detection again.")
        return rec

    def _store(self, rec: AnalysisRecord) -> None:
        with self._lock:
            self._cache[rec.id] = rec
            while len(self._cache) > self._size:
                self._cache.popitem(last=False)

    # -------------------------------------------------------------------------------- C outcomes
    def no_dataset(self, location_name: str | None, start_year: int, end_year: int) -> ChangeSummary:
        where = location_name or "this location"
        ins = Insufficient(
            code="no_dataset", reason=f"None of the loaded datasets covers {where}, so no observations are available to compare.",
            missing=["a dataset whose footprint contains the location"],
            available_dates=[],
        )
        return ChangeSummary(
            outcome="insufficient_data", headline=f"Insufficient data: no dataset covers {where}.", location_name=location_name,
            what_was_analysed=f"No analysis was run for {start_year}–{end_year} because there are no observations for this place.",
            insufficient=ins, limitations=["Change is not assessed without observations. This is not a finding of 'no change'."],
        )

    def _insufficient(self, ds: Dataset, svc_info: DatasetInfo, loc: str | None, period: PeriodCheck, code: str, reason: str, missing: list[str], p: ChangeParams) -> ChangeSummary:
        usable = self.datasets.usable(ds, p.min_obs_valid_fraction)
        by_year: dict[int, int] = {}
        for o in usable:
            by_year[o.date.year] = by_year.get(o.date.year, 0) + 1
        need = p.min_valid_obs_monthly if ds.temporal == "monthly" else p.min_valid_obs_yearly
        ok_years = sorted(y for y, n in by_year.items() if n >= (need if ds.temporal == "monthly" else 1))
        suggested = {"start_year": ok_years[0], "end_year": ok_years[-1]} if len(ok_years) >= 2 else None
        ins = Insufficient(code=code, reason=reason, missing=missing, available_dates=[o.iso[:7] if ds.temporal == "monthly" else o.iso[:4] for o in usable][:120], suggested_period=suggested)
        return ChangeSummary(
            outcome="insufficient_data", headline="Insufficient data to assess change for this period.", dataset=svc_info, location_name=loc, period=period,
            what_was_analysed="The data were checked against the minimum requirements below; no comparison was made.", insufficient=ins,
            limitations=["This is not a finding of 'no change': the observations needed to decide are missing."],
            thresholds=p.model_dump(), bbox=ds.bbox, is_synthetic=ds.is_synthetic, simulated_label=ds.meta.get("simulated_label"),
        )

    # ------------------------------------------------------------------------------------ main
    def detect(self, ds: Dataset, start_year: int, end_year: int, params: ChangeParams | None = None, location_name: str | None = None) -> AnalysisRecord | ChangeSummary:
        p = params or ChangeParams()
        info = dataset_info(self.datasets, ds)
        period = check_period(ds, start_year, end_year)
        if period.status in ("outside", "too_short"):
            return self._insufficient(ds, info, location_name, period, f"period_{period.status}", " ".join(period.messages), ["observations inside the requested period"], p)
        es, ee = period.effective["start_year"], period.effective["end_year"]  # type: ignore[index]
        w = min(p.window_years, max(1, (ee - es + 1) // 2))
        yrs0, yrs1 = range(es, es + w), range(ee - w + 1, ee + 1)
        need = p.min_valid_obs_monthly if ds.temporal == "monthly" else p.min_valid_obs_yearly

        o0, n0 = _window_obs(ds, self.datasets, yrs0, p.min_obs_valid_fraction)
        o1, n1 = _window_obs(ds, self.datasets, yrs1, p.min_obs_valid_fraction)
        notes: list[str] = []
        arrays: dict[str, np.ndarray] = {}

        def load(lst: list[Obs]) -> list[Obs]:
            out = []
            for o in lst:
                try:
                    arrays[o.iso] = self.datasets.read(ds, o)
                    out.append(o)
                except AppError:
                    notes.append(f"{o.iso[:7]}: file could not be read and was skipped")
            return out

        o0, o1 = load(o0), load(o1)
        label0 = f"{yrs0.start}" if w == 1 else f"{yrs0.start}–{yrs0.stop - 1}"
        label1 = f"{yrs1.start}" if w == 1 else f"{yrs1.start}–{yrs1.stop - 1}"
        if not o0 or not o1:
            missing = []
            for lab, o_, nn in ((label0, o0, n0), (label1, o1, n1)):
                if not o_:
                    missing.append(f"usable observations in {lab}" + (f" ({'; '.join(nn)})" if nn else " (none exist in the dataset)"))
            side = label0 if not o0 else label1
            return self._insufficient(ds, info, location_name, period, "no_usable_observations", f"There is no usable observation in {side}, so that end of the period cannot be described.", missing + notes, p)

        months0, months1 = {o.date.month for o in o0}, {o.date.month for o in o1}
        common = sorted(months0 & months1)
        if not common:
            return self._insufficient(ds, info, location_name, period, "no_common_season", f"{label0} and {label1} have no calendar month in common, so a like-for-like comparison is impossible (seasonal differences would look like change).", ["observations from the same season in both periods"] + notes, p)
        s0 = [o for o in o0 if o.date.month in common]
        s1 = [o for o in o1 if o.date.month in common]
        if len(s0) < need or len(s1) < need:
            short = label0 if len(s0) < need else label1
            return self._insufficient(
                ds, info, location_name, period, "too_few_observations",
                f"Only {min(len(s0), len(s1))} usable same-season observation(s) exist in {short}; at least {need} are needed for a {ds.temporal} dataset (matched months: {_fmt_months(common)}).",
                [f"{need - len(s0)} more usable observation(s) in {label0}" if len(s0) < need else "", f"{need - len(s1)} more usable observation(s) in {label1}" if len(s1) < need else ""] + (n0 + n1 + notes)[:6], p,
            )

        W, U = ds.water_class, ds.uncertain
        w0, ok0 = _composite([arrays[o.iso] for o in s0], W, U, p.water_frequency, p.min_pixel_obs_fraction)
        w1, ok1 = _composite([arrays[o.iso] for o in s1], W, U, p.water_frequency, p.min_pixel_obs_fraction)
        valid = ok0 & ok1
        rows = ds.row_area_m2
        assert rows is not None
        total_ha = area_ha(np.ones_like(valid), rows)
        loss = _clean(w0 & ~w1 & valid, p.min_feature_px)
        gain = _clean(~w0 & w1 & valid, p.min_feature_px)
        diff = np.full(valid.shape, D_UNCERTAIN, dtype=np.uint8)
        diff[valid & ~w1] = D_LAND
        diff[valid & w1] = D_WATER
        diff[loss] = D_LOSS
        diff[gain] = D_GAIN

        water_start_ha, water_end_ha = area_ha(w0 & valid, rows), area_ha(w1 & valid, rows)
        lost_ha, gained_ha = area_ha(loss, rows), area_ha(gain, rows)
        unchanged_water_ha = area_ha(w0 & w1 & valid & ~loss & ~gain, rows)
        unchanged_land_ha = area_ha(~w0 & ~w1 & valid & ~loss & ~gain, rows)
        analysed_ha, uncertain_ha = area_ha(valid, rows), area_ha(~valid, rows)
        net_ha = gained_ha - lost_ha
        pct_net = 100.0 * net_ha / water_start_ha if water_start_ha > 0 else None
        pct_gross = 100.0 * (gained_ha + lost_ha) / water_start_ha if water_start_ha > 0 else None

        aid = hashlib.sha1(f"{ds.id}|{es}|{ee}|{p.model_dump_json()}|{len(ds.observations)}".encode()).hexdigest()[:12]
        hotspots, fc = self._hotspots(ds, loss, gain, w0, valid, aid, p.min_hotspot_ha)
        progression = self._progression(ds, arrays, common, es, ee, w0, ok0, p)
        trend, sigma = self._trend(progression)

        # seasonal amplitude from the starting window (reported, and used in the limitations)
        shares = []
        for o in s0:
            a = arrays[o.iso]
            v = a != U
            if v.any():
                shares.append(float(((a == W) & v).sum() / v.sum()))
        seasonal_amp = 100.0 * (max(shares) - min(shares)) / (sum(shares) / len(shares)) if len(shares) >= 4 and sum(shares) > 0 else None

        gross_ha = gained_ha + lost_ha
        big_enough = pct_gross is not None and pct_gross >= p.min_change_pct and any(h.area_ha >= p.min_hotspot_ha for h in hotspots)
        above_noise = True if sigma is None else gross_ha >= p.noise_factor * sigma
        outcome = "change_detected" if big_enough and above_noise else "no_clear_change"

        mean_vf = float(np.mean([o.valid_fraction for o in s0 + s1]))
        pts, reasons = 0, []
        for lab, n in ((label0, len(s0)), (label1, len(s1))):
            if ds.temporal == "monthly":
                pts += 2 if n >= 6 else 1 if n >= 3 else 0
                reasons.append(f"{n} usable same-season observation(s) in {lab}")
            else:
                pts += 1 if n >= 1 else 0
                reasons.append(f"{n} usable observation(s) in {lab}")
        pts += 2 if mean_vf >= 0.85 else 1 if mean_vf >= 0.65 else 0
        reasons.append(f"mean valid-pixel share of the observations used: {mean_vf:.0%}")
        unc_share = uncertain_ha / total_ha if total_ha else 0
        pts += 1 if unc_share <= 0.10 else 0
        reasons.append(f"{unc_share:.0%} of the footprint is uncertain (cloud or gaps) and excluded")
        pts += 1 if len(progression) >= 5 else 0
        confidence = "high" if pts >= 6 else "medium" if pts >= 4 else "low"
        if ds.temporal != "monthly" and (len(s0) < 2 or len(s1) < 2) and confidence == "high":
            confidence = "medium"
            reasons.append("each end rests on a single yearly observation")

        limits = self._limitations(ds, info, p, common, n0 + n1 + notes, period, seasonal_amp, sigma, trend)
        most = self._most_affected(hotspots)
        lab_period = f"{es}–{ee}"
        if outcome == "change_detected":
            headline = f"Change detected: {lost_ha:.1f} ha of water lost and {gained_ha:.1f} ha gained between {es} and {ee} (net {net_ha:+.1f} ha{'' if pct_net is None else f', {pct_net:+.1f}%'})."
        else:
            why = ""
            if big_enough and not above_noise:
                why = " The measured difference is no larger than normal year-to-year scatter."
            headline = f"No clear change in water extent between {es} and {ee} (net {net_ha:+.1f} ha{'' if pct_net is None else f', {pct_net:+.1f}%'}).{why}"

        first, last = min(s0, key=lambda o: o.date), max(s1, key=lambda o: o.date)
        base = "/api/explorer"
        summary = ChangeSummary(
            outcome=outcome, headline=headline, analysis_id=aid, dataset=info, location_name=location_name, period=period,
            first_observation={"date": first.iso, "quality": first.quality, "valid_fraction": first.valid_fraction, "layer_url": f"{base}/datasets/{ds.id}/observations/{first.iso}/layer.png"},
            last_observation={"date": last.iso, "quality": last.quality, "valid_fraction": last.valid_fraction, "layer_url": f"{base}/datasets/{ds.id}/observations/{last.iso}/layer.png"},
            observations_used={"start_window": label0, "end_window": label1, "start_count": len(s0), "end_count": len(s1), "matched_months": _fmt_months(common), "matched_month_numbers": common, "excluded": (n0 + n1 + notes)[:12]},
            areas={
                "footprint_ha": round(total_ha, 2), "analysed_ha": round(analysed_ha, 2), "uncertain_ha": round(uncertain_ha, 2),
                "water_start_ha": round(water_start_ha, 2), "water_end_ha": round(water_end_ha, 2), "gained_ha": round(gained_ha, 2), "lost_ha": round(lost_ha, 2),
                "net_ha": round(net_ha, 2), "unchanged_water_ha": round(unchanged_water_ha, 2), "unchanged_land_ha": round(unchanged_land_ha, 2),
                "pct_net_change": None if pct_net is None else round(pct_net, 2), "pct_gross_change": None if pct_gross is None else round(pct_gross, 2),
                "seasonal_amplitude_pct": None if seasonal_amp is None else round(seasonal_amp, 1), "year_to_year_scatter_ha": None if sigma is None else round(sigma, 2),
            },
            most_affected=most, hotspots=hotspots, progression=progression, trend=trend,
            quality={"mean_valid_fraction": round(mean_vf, 3), "uncertain_share": round(unc_share, 3), "observations_in_period": sum(1 for o in ds.observations if es <= o.date.year <= ee), "usable_in_period": sum(1 for o in self.datasets.usable(ds, p.min_obs_valid_fraction) if es <= o.date.year <= ee)},
            confidence=confidence, confidence_reasons=reasons, limitations=limits,
            what_was_analysed=(
                f"Same-season composites of {label0} ({len(s0)} observations) and {label1} ({len(s1)} observations), using only {_fmt_months(common)} so seasons match. "
                f"A pixel counts as water if it is water in at least {p.water_frequency:.0%} of its valid observations; {uncertain_ha:.0f} ha ({unc_share:.0%}) were uncertain and excluded."
            ),
            thresholds=p.model_dump(), bbox=ds.bbox, is_synthetic=ds.is_synthetic, simulated_label=ds.meta.get("simulated_label"),
            layers={
                "difference_png": f"{base}/analysis/{aid}/layers/difference.png", "before_png": f"{base}/analysis/{aid}/layers/before.png", "after_png": f"{base}/analysis/{aid}/layers/after.png",
                "difference_tif": f"{base}/analysis/{aid}/layers/difference.tif", "hotspots_geojson": f"{base}/analysis/{aid}/hotspots",
            },
        )
        rec = AnalysisRecord(aid, ds.id, summary, diff, w0, ok0, w1, ok1, fc)
        self._store(rec)
        return rec

    # ------------------------------------------------------------------------------- pieces
    def _hotspots(self, ds: Dataset, loss: np.ndarray, gain: np.ndarray, w0: np.ndarray, valid: np.ndarray, aid: str, min_ha: float) -> tuple[list[Hotspot], dict[str, Any]]:
        rows = ds.row_area_m2
        assert rows is not None
        tr = _lonlat_transformer(ds)
        r0, c0 = np.nonzero(w0 & valid)
        cx, cy = _pix_lonlat(ds, r0, c0, tr) if len(r0) else (0.0, 0.0)
        found: list[tuple[float, str, np.ndarray]] = []
        for kind, mask in (("loss", loss), ("gain", gain)):
            if not mask.any():
                continue
            labels, n = ndi.label(mask, structure=S8)
            for gid in range(1, n + 1):
                pix = labels == gid
                a = area_ha(pix, rows)
                if a >= min_ha:
                    found.append((a, kind, pix))
        found.sort(key=lambda t: -t[0])
        total = sum(a for a, _, _ in found) or 1.0
        geo_crs = None
        feats, out = [], []
        for rank, (a, kind, pix) in enumerate(found, 1):
            polys = [shape(g) for g, v in shapes(pix.astype(np.uint8), mask=pix, transform=ds.transform) if v == 1]
            geom = unary_union(polys).simplify(abs(ds.transform.a) * 0.4)
            gs = gpd.GeoSeries([geom], crs=ds.crs)
            gs4326 = gs.to_crs(4326) if not ds.crs.is_geographic else gs
            geo_crs = geo_crs or gs4326.estimate_utm_crs()
            g_area = float(gs4326.to_crs(geo_crs).area.iloc[0] / 10_000.0)
            g4 = gs4326.iloc[0]
            cen = g4.centroid
            region = compass((cen.x - cx) * math.cos(math.radians(cen.y)), cen.y - cy) if len(r0) else "central"
            desc = f"{region} {'shore' if kind == 'loss' else 'area'}: {a:.1f} ha of water {'lost' if kind == 'loss' else 'gained'}"
            hid = f"{aid}-{kind[0]}{rank}"
            out.append(Hotspot(
                id=hid, rank=rank, kind=kind, area_ha=round(a, 2), geometry_area_ha=round(g_area, 2), share_of_change_pct=round(100 * a / total, 1),
                centroid={"lon": round(cen.x, 6), "lat": round(cen.y, 6)}, bbox=[round(v, 6) for v in g4.bounds], region=region, description=desc,
            ))
            feats.append({"type": "Feature", "id": hid, "geometry": mapping(g4), "properties": {"id": hid, "rank": rank, "kind": kind, "area_ha": round(a, 2), "region": region, "description": desc}})
        return out, {"type": "FeatureCollection", "features": feats}

    def _progression(self, ds: Dataset, arrays: dict[str, np.ndarray], common: list[int], es: int, ee: int, w0: np.ndarray, ok0: np.ndarray, p: ChangeParams) -> list[ProgressionPoint]:
        rows = ds.row_area_m2
        assert rows is not None
        W, U = ds.water_class, ds.uncertain
        need = max(1, math.ceil(len(common) / 2)) if ds.temporal == "monthly" else 1
        pts: list[ProgressionPoint] = []
        for y in range(es, ee + 1):
            ys = [o for o in ds.observations if o.date.year == y and o.date.month in common and ds.usable(o, p.min_obs_valid_fraction)]
            if len(ys) < need:
                continue
            arrs = []
            for o in ys:
                if o.iso not in arrays:
                    try:
                        arrays[o.iso] = self.datasets.read(ds, o)
                    except AppError:
                        continue
                arrs.append(arrays[o.iso])
            if len(arrs) < need:
                continue
            wy, oky = _composite(arrs, W, U, p.water_frequency, p.min_pixel_obs_fraction)
            both = ok0 & oky
            ok_ha = area_ha(oky, rows)
            full = area_ha(np.ones_like(oky), rows)
            water_ha = area_ha(wy & oky, rows) / ok_ha * full if ok_ha > 0 else 0.0
            cl = area_ha(_clean(w0 & ~wy & both, p.min_feature_px), rows)
            cg = area_ha(_clean(~w0 & wy & both, p.min_feature_px), rows)
            pts.append(ProgressionPoint(year=y, water_ha=round(water_ha, 2), cumulative_loss_ha=round(cl, 2), cumulative_gain_ha=round(cg, 2), observations=len(arrs)))
        return pts

    def _trend(self, prog: list[ProgressionPoint]) -> tuple[dict[str, Any] | None, float | None]:
        if len(prog) < 4:
            return None, None
        x = np.array([q.year for q in prog], dtype=float)
        y = np.array([q.water_ha for q in prog], dtype=float)
        slope, intercept, _, _ = stats.theilslopes(y, x)
        tau, pval = stats.kendalltau(x, y)
        resid = y - (intercept + slope * x)
        sigma = float(np.std(resid, ddof=1)) if len(prog) >= 5 else None
        direction = "decreasing" if (pval < 0.05 and slope < 0) else "increasing" if (pval < 0.05 and slope > 0) else "no clear trend"
        return {"method": "Theil-Sen slope with Kendall tau test on yearly same-season water area", "slope_ha_per_year": round(float(slope), 3), "p_value": round(float(pval), 4), "tau": round(float(tau), 3), "direction": direction, "years": len(prog)}, sigma

    def _most_affected(self, hs: list[Hotspot]) -> dict[str, Any] | None:
        if not hs:
            return None
        agg: dict[tuple[str, str], float] = {}
        for h in hs:
            agg[(h.region, h.kind)] = agg.get((h.region, h.kind), 0.0) + h.area_ha
        (region, kind), a = max(agg.items(), key=lambda kv: kv[1])
        top = next(h for h in hs if h.region == region and h.kind == kind)
        return {"region": region, "kind": kind, "area_ha": round(a, 2), "description": f"{region} {'shore' if kind == 'loss' else 'area'}: {a:.1f} ha of water {'lost' if kind == 'loss' else 'gained'}", "hotspot_id": top.id, "centroid": top.centroid}

    def _limitations(self, ds: Dataset, info: DatasetInfo, p: ChangeParams, common: list[int], notes: list[str], period: PeriodCheck, seasonal_amp: float | None, sigma: float | None, trend: dict[str, Any] | None) -> list[str]:
        out = [
            f"Spatial resolution is about {info.resolution_m:.0f} m per pixel; shoreline shifts smaller than ~{p.min_feature_px - 1} pixels are treated as positional noise.",
            f"Only {_fmt_months(common)} were compared so that seasons match; other months were not used for the start/end maps.",
        ]
        if ds.is_synthetic:
            out.insert(0, "This is SIMULATED demonstration data, not satellite observations. Results show the method working on known, built-in changes.")
        out.extend(period.messages)
        if notes:
            out.append("Some observations were excluded: " + "; ".join(notes[:4]) + ("…" if len(notes) > 4 else "."))
        if seasonal_amp is not None:
            out.append(f"Within a single year the water area varies by about {seasonal_amp:.0f}% between seasons; that cycle alone is not treated as lasting change.")
        if sigma is None:
            out.append("Fewer than five yearly composites exist, so the year-to-year scatter test could not be applied.")
        out.append("The data describe where and how much water extent changed. They cannot, by themselves, establish why.")
        return out
