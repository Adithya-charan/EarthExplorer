"""Whole-record overview of one region (and an all-regions atlas), computed only from the loaded rows.

Everything is derived from the dataset: monthly values, each calendar month's usual value (mean over the record, needs at
least 3 values per month), the difference from it (anomaly) and its standardised form (z). Years with fewer than 10 valid
months get no yearly number rather than a filled-in one. No cause is asserted.
"""

from __future__ import annotations

import calendar

import numpy as np
import pandas as pd
from scipy import stats as sps

from app.errors import not_found, unprocessable
from app.schemas_story import (
    AtlasRegion,
    AtlasResponse,
    ClimMonth,
    DecadePoint,
    OverviewResponse,
    RecordMonth,
    RecordYear,
    SnapshotPoint,
    SnapshotResponse,
    StorySentence,
    TrendInfo,
    YearPoint,
)
from app.services.places import PLACES_NOTE, region_centre
from app.services.provenance import build_provenance
from app.services.store import DatasetRecord
from app.services.story import MIN_CLIMATOLOGY_YEARS, SYNTHETIC_BANNER, _f, default_variable

MIN_MONTHS_PER_YEAR = 10
MIN_YEARS_FOR_TREND = 20


def _monthly_z(var_rows: pd.DataFrame) -> pd.DataFrame:
    """Per region and month: value, usual value (mean), spread (std), anomaly and z. Duplicates are averaged for this view only."""
    g = (
        var_rows.assign(m=var_rows["date"].dt.to_period("M").dt.to_timestamp())
        .groupby(["region", "m"], as_index=False)["value"]
        .mean()
        .dropna(subset=["value"])
    )
    g["mon"] = g["m"].dt.month
    st = g.groupby(["region", "mon"])["value"].agg(mean_="mean", std_="std", n_="count").reset_index()
    g = g.merge(st, on=["region", "mon"], how="left")
    ok = g["n_"] >= MIN_CLIMATOLOGY_YEARS
    g["anom"] = np.where(ok, g["value"] - g["mean_"], np.nan)
    g["z"] = np.where(ok & (g["std_"] > 0), g["anom"] / g["std_"], np.nan)
    g["year"] = g["m"].dt.year
    return g


def _yearly(g: pd.DataFrame) -> pd.DataFrame:
    """One row per year for a single region; yearly numbers only when >= 10 valid months."""
    rows = []
    for y, d in g.groupby("year"):
        n = int(len(d))
        full = n >= MIN_MONTHS_PER_YEAR
        a, z = d["anom"].dropna(), d["z"].dropna()
        rows.append(
            {
                "year": int(y),
                "n": n,
                "mean_value": float(d["value"].mean()) if full else None,
                "mean_anom": float(a.mean()) if (full and len(a) >= MIN_MONTHS_PER_YEAR) else None,
                "mean_z": float(z.mean()) if (full and len(z) >= MIN_MONTHS_PER_YEAR) else None,
            }
        )
    return pd.DataFrame(rows, columns=["year", "n", "mean_value", "mean_anom", "mean_z"])


def _fmt(x: float, unit: str) -> str:
    """Readable rounding for sentences (the exact numbers stay in the evidence strings)."""
    ax = abs(x)
    s = f"{x:.0f}" if ax >= 100 else f"{x:.1f}" if ax >= 1 else f"{x:.2g}"
    return f"{s} {unit}".strip()


def _is_accumulation(unit: str) -> bool:
    u = unit.lower().replace(" ", "")
    return any(k in u for k in ("/month", "permonth", "/mo", "/yr", "peryear"))


def _var_rows(record: DatasetRecord, variable: str | None) -> tuple[str, pd.DataFrame]:
    variable = variable or default_variable(record)
    if variable is None:
        raise unprocessable("empty_dataset", "This dataset has no variables.")
    rows = record.data[record.data["variable"] == variable]
    if rows.empty:
        raise not_found("variable_not_found", f"Variable '{variable}' does not exist in dataset '{record.name}'.")
    return variable, rows


def build_overview(record: DatasetRecord, region: str, variable: str | None) -> OverviewResponse:
    variable, rows = _var_rows(record, variable)
    series = rows[rows["region"] == region]
    if series.empty:
        raise not_found("series_not_found", f"Region '{region}' has no data for variable '{variable}' in this dataset.")
    unit = ", ".join(sorted(series["unit"].dropna().unique().tolist())) or ""
    prov = build_provenance(record, series)
    banner = SYNTHETIC_BANNER if prov.is_synthetic else None
    g = _monthly_z(series)
    if g.empty:
        raise unprocessable("no_valid_values", f"No valid values for {region}.")
    yearly = _yearly(g)
    y0, y1 = int(g["year"].min()), int(g["year"].max())
    years = list(range(y0, y1 + 1))
    idx = {y: i for i, y in enumerate(years)}
    mv: list[list[float | None]] = [[None] * 12 for _ in years]
    mz: list[list[float | None]] = [[None] * 12 for _ in years]
    for r in g.itertuples():
        mv[idx[r.year]][r.mon - 1] = _f(r.value)
        mz[idx[r.year]][r.mon - 1] = _f(r.z)
    ymap = {int(r.year): r for r in yearly.itertuples()}
    year_points = [
        YearPoint(
            year=y,
            n_months=int(ymap[y].n) if y in ymap else 0,
            mean_value=_f(ymap[y].mean_value) if y in ymap else None,
            mean_anomaly=_f(ymap[y].mean_anom) if y in ymap else None,
            mean_z=_f(ymap[y].mean_z) if y in ymap else None,
        )
        for y in years
    ]
    clim = []
    for m in range(1, 13):
        d = g[g["mon"] == m]
        n = int(len(d))
        ok = n >= MIN_CLIMATOLOGY_YEARS
        clim.append(ClimMonth(month=m, mean=_f(d["value"].mean()) if ok else None, std=_f(d["value"].std(ddof=1)) if ok else None, n=n))
    clim_ok = all(c.mean is not None for c in clim)

    valid_years = yearly.dropna(subset=["mean_anom"])
    decades: list[DecadePoint] = []
    if not valid_years.empty:
        vy = valid_years.assign(dec=(valid_years["year"] // 10) * 10)
        for dec, d in vy.groupby("dec"):
            if len(d) >= 5:
                decades.append(DecadePoint(decade=int(dec), mean_anomaly=float(d["mean_anom"].mean()), n_years=int(len(d))))

    gz = g.dropna(subset=["z"])
    wet_m = gz.nlargest(5, "z")
    dry_m = gz.nsmallest(5, "z")

    def to_rm(df: pd.DataFrame) -> list[RecordMonth]:
        return [RecordMonth(date=r.m.date(), value=float(r.value), anomaly=float(r.anom), z=float(r.z)) for r in df.itertuples()]

    vz = valid_years.dropna(subset=["mean_z"])

    def to_ry(df: pd.DataFrame) -> list[RecordYear]:
        return [RecordYear(year=int(r.year), mean_anomaly=float(r.mean_anom), mean_z=float(r.mean_z)) for r in df.itertuples()]

    wet_y, dry_y = vz.nlargest(5, "mean_z"), vz.nsmallest(5, "mean_z")

    trend = None
    if len(valid_years) >= MIN_YEARS_FOR_TREND:
        lr = sps.linregress(valid_years["year"].to_numpy(dtype=float), valid_years["mean_anom"].to_numpy(dtype=float))
        trend = TrendInfo(
            slope_per_decade=float(lr.slope * 10),
            p_value=float(lr.pvalue),
            n_years=int(len(valid_years)),
            note="Straight-line fit to yearly mean anomalies. Descriptive: it ignores year-to-year dependence and says nothing about cause.",
        )

    caveats: list[str] = []
    if banner:
        caveats.append(f"{banner}. These numbers are invented demo values and do not describe real conditions.")
    n_gap = sum(1 for y in years if (ymap[y].n if y in ymap else 0) < 12)
    if n_gap:
        caveats.append(
            f"{n_gap} of {len(years)} years have fewer than 12 valid months; years with fewer than {MIN_MONTHS_PER_YEAR} get no yearly number and missing months are never filled in."
        )
    if not clim_ok:
        caveats.append("Some calendar months have fewer than 3 values, so month-by-month normals and anomalies are not shown.")

    s: list[StorySentence] = []
    where = region + (" (synthetic demo)" if banner else "")
    s.append(
        StorySentence(
            kind="observation",
            text=f"The record for {where} runs from {y0} to {y1} ({len(g)} valid months).",
            evidence=f"first month {g['m'].min().date()}, last {g['m'].max().date()}, n={len(g)}",
        )
    )
    if clim_ok:
        peak = max(clim, key=lambda c: c.mean if c.mean is not None else -np.inf)
        low = min(clim, key=lambda c: c.mean if c.mean is not None else np.inf)
        s.append(
            StorySentence(
                kind="observation",
                text=f"{calendar.month_name[peak.month]} is the typical peak ({_fmt(peak.mean, unit)} on average) and {calendar.month_name[low.month]} the typical low ({_fmt(low.mean, unit)}).",
                evidence=f"month means: max={peak.mean:.6g} (month {peak.month}), min={low.mean:.6g} (month {low.month})",
            )
        )
        if _is_accumulation(unit):
            tot = sum(c.mean for c in clim if c.mean is not None)
            jjas = sum(c.mean for c in clim if c.mean is not None and c.month in (6, 7, 8, 9))
            base_unit = unit.split("/")[0]
            if tot > 0:
                s.append(
                    StorySentence(
                        kind="observation",
                        text=f"June to September supplies {jjas / tot * 100:.0f}% of an average year's total ({_fmt(jjas, base_unit)} of {_fmt(tot, base_unit)}).",
                        evidence=f"sum of four monthly means / sum of all twelve = {jjas:.6g}/{tot:.6g}",
                    )
                )
    if len(wet_y) and len(dry_y):
        w, d = wet_y.iloc[0], dry_y.iloc[0]
        s.append(
            StorySentence(
                kind="comparison",
                text=f"The most above-normal year was {int(w['year'])} (on average {_fmt(abs(w['mean_anom']), unit)} above the usual month) and the most below-normal was {int(d['year'])} ({_fmt(abs(d['mean_anom']), unit)} below).",
                evidence=f"mean anomaly {w['mean_anom']:.6g} in {int(w['year'])}; {d['mean_anom']:.6g} in {int(d['year'])}",
            )
        )
    if len(wet_m) and len(dry_m):
        w, d = wet_m.iloc[0], dry_m.iloc[0]
        s.append(
            StorySentence(
                kind="comparison",
                text=f"The most extreme single months were {calendar.month_name[int(w['mon'])]} {int(w['year'])} ({_fmt(w['value'], unit)}, {w['z']:+.1f} standard deviations from that month's normal) and {calendar.month_name[int(d['mon'])]} {int(d['year'])} ({_fmt(d['value'], unit)}, {d['z']:+.1f}).",
                evidence=f"z={w['z']:.3f} on {w['m'].date()}; z={d['z']:.3f} on {d['m'].date()}",
            )
        )
    full_years = yearly.dropna(subset=["mean_value"])
    k = min(30, len(full_years) // 3)
    if k >= 10:
        early, late = full_years.iloc[:k], full_years.iloc[-k:]
        em, lm = float(early["mean_value"].mean()), float(late["mean_value"].mean())
        if em:
            pct = (lm - em) / abs(em) * 100
            s.append(
                StorySentence(
                    kind="comparison",
                    text=f"The average month in the latest {k} years ({int(late['year'].min())}–{int(late['year'].max())}) was {_fmt(lm, unit)}, {abs(pct):.1f}% {'higher' if pct > 0 else 'lower'} than in the first {k} years ({int(early['year'].min())}–{int(early['year'].max())}: {_fmt(em, unit)}).",
                    evidence=f"mean of yearly means: early={em:.6g}, late={lm:.6g}, k={k}",
                )
            )
    if trend:
        s.append(
            StorySentence(
                kind="context",
                text=f"A straight line through the yearly anomalies changes by {_fmt(trend.slope_per_decade, unit)} per decade (p = {trend.p_value:.3g}, {trend.n_years} years). Year-to-year swings are large, so a small slope can sit inside that noise.",
                evidence=f"OLS slope per decade={trend.slope_per_decade:.6g}, p={trend.p_value:.4g}",
            )
        )
    if decades:
        hi, lo = max(decades, key=lambda x: x.mean_anomaly), min(decades, key=lambda x: x.mean_anomaly)
        s.append(
            StorySentence(
                kind="comparison",
                text=f"By decade, the {hi.decade}s ran furthest above normal and the {lo.decade}s furthest below.",
                evidence=f"decade mean anomalies: {hi.decade}s={hi.mean_anomaly:.6g}, {lo.decade}s={lo.mean_anomaly:.6g}",
            )
        )
    others = sorted(v for v in record.data["variable"].unique() if v != variable)
    if others:
        s.append(
            StorySentence(
                kind="limitation",
                text=f"The dataset also holds {', '.join(others)}; the period summary shows whether they move together. Co-movement is a lead, not a cause.",
                evidence="other variables present",
            )
        )
    else:
        s.append(
            StorySentence(
                kind="limitation",
                text="This dataset cannot say why: it holds no driver variables (such as temperature, winds or ocean state), so any cause would be a guess. Add a dataset with candidate drivers to investigate.",
                evidence="no other usable variables",
            )
        )

    return OverviewResponse(
        provenance=prov, dataset_id=record.id, region=region, variable=variable, unit=unit, banner=banner,
        first_year=y0, last_year=y1, years=year_points, matrix_values=mv, matrix_z=mz, climatology=clim, decades=decades,
        wettest_months=to_rm(wet_m), driest_months=to_rm(dry_m), wettest_years=to_ry(wet_y), driest_years=to_ry(dry_y),
        trend=trend, sentences=s, caveats=caveats,
    )


def build_atlas(record: DatasetRecord, variable: str | None) -> AtlasResponse:
    variable, rows = _var_rows(record, variable)
    unit = ", ".join(sorted(rows["unit"].dropna().unique().tolist())) or ""
    prov = build_provenance(record, rows)
    g = _monthly_z(rows)
    if g.empty:
        raise unprocessable("no_valid_values", "No valid values.")
    years = list(range(int(g["year"].min()), int(g["year"].max()) + 1))
    out: list[AtlasRegion] = []
    for region, d in g.groupby("region"):
        y = _yearly(d)
        zmap = {int(r.year): _f(r.mean_z) for r in y.itertuples()}
        z = [zmap.get(yy) for yy in years]
        pts = [(yy, v) for yy, v in zip(years, z) if v is not None]
        slope = None
        if len(pts) >= MIN_YEARS_FOR_TREND:
            slope = _f(sps.linregress([p[0] for p in pts], [p[1] for p in pts]).slope * 10)
        out.append(AtlasRegion(region=str(region), mean_value=_f(d["value"].mean()), trend_z_per_decade=slope, z=z))
    return AtlasResponse(
        provenance=prov, dataset_id=record.id, variable=variable, unit=unit,
        banner=SYNTHETIC_BANNER if prov.is_synthetic else None, years=years, regions=out,
        note="Each cell is that year's mean standardised anomaly (difference from the usual value for each calendar month, in units of that month's own spread). Blank = fewer than 10 valid months. Colours are comparable across regions; raw amounts are not.",
    )


def build_snapshot(record: DatasetRecord, variable: str | None, year: int, month: int) -> SnapshotResponse:
    """Every region for one month (or one whole year), with the positions that are known. Nothing is filled in."""
    if not 0 <= month <= 12:
        raise unprocessable("invalid_month", "month must be 0 (whole year) or 1-12.")
    variable, rows = _var_rows(record, variable)
    unit = ", ".join(sorted(rows["unit"].dropna().unique().tolist())) or ""
    prov = build_provenance(record, rows)
    g = _monthly_z(rows)
    if g[g["year"] == year].empty:
        raise unprocessable("year_outside_data", f"No values for {year} in this dataset.")
    label = f"{calendar.month_name[month]} {year}" if month else str(year)
    points: list[SnapshotPoint] = []
    unlocated: list[str] = []
    for region, d in g.groupby("region"):
        dy = d[d["year"] == year]
        if month:
            r = dy[dy["mon"] == month]
            if r.empty:
                continue
            r0 = r.iloc[0]
            v, usual, a, z = _f(r0["value"]), _f(r0["mean_"]), _f(r0["anom"]), _f(r0["z"])
        else:
            if len(dy) < MIN_MONTHS_PER_YEAR:
                continue
            v = _f(dy["value"].mean())
            usual = _f(dy["mean_"].mean())
            a = _f(dy["anom"].mean()) if dy["anom"].notna().sum() >= MIN_MONTHS_PER_YEAR else None
            z = _f(dy["z"].mean()) if dy["z"].notna().sum() >= MIN_MONTHS_PER_YEAR else None
        centre = region_centre(str(region))
        if centre is None:
            unlocated.append(str(region))
            continue
        points.append(SnapshotPoint(region=str(region), lon=centre[0], lat=centre[1], value=v, usual=usual, anomaly=a, z=z))
    banner = SYNTHETIC_BANNER if prov.is_synthetic else None
    s: list[StorySentence] = []
    zs = [p for p in points if p.z is not None]
    if zs:
        above = sum(1 for p in zs if p.z > 0)
        top = max(zs, key=lambda p: p.z)
        bot = min(zs, key=lambda p: p.z)
        s.append(
            StorySentence(
                kind="observation",
                text=f"In {label}, {above} of {len(zs)} regions with a usual value to compare were above it and {len(zs) - above} below.",
                evidence=f"count of regions with z>0 = {above} of {len(zs)}",
            )
        )
        s.append(
            StorySentence(
                kind="comparison",
                text=f"Furthest above usual: {top.region} ({top.z:+.2f} SD). Furthest below: {bot.region} ({bot.z:+.2f} SD).",
                evidence=f"z={top.z:.3f} ({top.region}); z={bot.z:.3f} ({bot.region})",
            )
        )
    elif points:
        s.append(StorySentence(kind="limitation", text=f"No region has enough history to compare {label} against its usual value.", evidence="z missing for all regions"))
    else:
        s.append(StorySentence(kind="limitation", text=f"No region with a known map position has values for {label}.", evidence="no located points"))
    if unlocated:
        s.append(
            StorySentence(
                kind="limitation",
                text=f"{len(unlocated)} region(s) have values but no known map position and are not drawn: {', '.join(sorted(unlocated))}.",
                evidence="not in the reference table",
            )
        )
    if banner:
        s.append(StorySentence(kind="limitation", text=f"{banner}. These are invented demo values.", evidence="dataset is synthetic"))
    return SnapshotResponse(
        provenance=prov, dataset_id=record.id, variable=variable, unit=unit, banner=banner, year=year, month=month, label=label,
        points=points, unlocated=sorted(unlocated), value_max=max([p.value for p in points if p.value is not None], default=0.0),
        sentences=s, note=PLACES_NOTE,
    )
