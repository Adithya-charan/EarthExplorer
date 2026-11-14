"""Builds the two packaged datasets from ``datasets/`` as separate, strictly labelled records.

* ``observed_global``   - the two NASA Giovanni global area-average series (precipitation, random error).
* ``synthetic_regional_demo`` - the three synthetic regional series; every row has ``is_synthetic = True``.

The two classes never share a record, so no endpoint can rank or compare across them. If a file is absent or fails
validation the record is not created and the reason is returned as an issue; the other class is unaffected and no
substitute data is ever supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.schemas import DataClass, DatasetInfo, PackageCheck
from app.services.ingestion.package_adapters import (
    RATE_UNIT,
    SYNTHETIC_BANNER,
    UNIT_SOURCE,
    ParsedSeries,
    parse_giovanni_csv,
    parse_regional_demo_csv,
)

OBSERVED_ID = "gpm-imerg-global-observed"
OBSERVED_NAME = "Observed global data — GPM IMERG V07 global monthly precipitation"
OBSERVED_REGION = "Global (area-average)"
OBSERVED_SOURCE = "NASA GES DISC GPM IMERG V07 (GPM_3IMERGM_07) via Giovanni area-averaged time series (user-supplied CSV export)"
OBSERVED_PRECIP_FILE = "observed_global/GPM_IMERG_V07_Global_Monthly_Precipitation_1998-2025.csv"
OBSERVED_ERROR_FILE = "observed_global/GPM_IMERG_V07_Global_Monthly_Precipitation_RandomError_1998-2025.csv"

DEMO_ID = "gpm-imerg-regional-synthetic-demo"
DEMO_NAME = "Synthetic regional demo data — NOT NASA OBSERVATIONS"
DEMO_SOURCE = SYNTHETIC_BANNER
DEMO_FILES = {
    "India": "synthetic_regional_demo/GPM_IMERG_V07_SYNTHETIC_DEMO_India_Monthly_1998-2025.csv",
    "Amazon": "synthetic_regional_demo/GPM_IMERG_V07_SYNTHETIC_DEMO_Amazon_Monthly_1998-2025.csv",
    "Central Africa": "synthetic_regional_demo/GPM_IMERG_V07_SYNTHETIC_DEMO_Central_Africa_Monthly_1998-2025.csv",
}

OBSERVED_NOTICE = (
    "Observed global data: NASA GPM IMERG V07 global area-averaged series. It describes the whole Earth, not any "
    "region, and cannot support regional claims."
)
DEMO_NOTICE_REGIONAL = (
    f"{SYNTHETIC_BANNER}. Regional-shaped series made for software testing; not satellite data and not a scientific finding."
)

OBSERVED_LIMITATIONS = [
    "Global area average of the whole data bounding box (-179.95, -89.95, 179.95, 89.95); not a regional extract.",
    "No India, Amazon or Central Africa conclusion, map pin or comparison can be drawn from it.",
    f"Precipitation is a rate in {RATE_UNIT}, not a monthly accumulation; it is not converted.",
    "The random-error series is Giovanni's area average of per-cell random error. It is uncertainty-related, not a confidence interval, and not the uncertainty of the area mean.",
    "Monthly values only: no sub-monthly information, no spatial structure.",
    "Early years come from the TRMM era of the IMERG record; the sensor mix changes over time, so a long-term trend may partly reflect that.",
]
DEMO_LIMITATIONS = [
    "Synthetic: artificial values, not NASA observations. Trends computed from them are not scientific findings.",
    "Useful only for testing the software (charts, comparisons, exports).",
    f"Unit label {RATE_UNIT} copies the observed product's unit; the values do not measure real rainfall.",
    "Must not be mixed with, ranked against or presented as observed data.",
]


@dataclass
class PackageDataset:
    id: str
    name: str
    status: str
    data: pd.DataFrame
    info: DatasetInfo
    source_file: str


@dataclass
class PackageLoad:
    datasets: list[PackageDataset] = field(default_factory=list)
    issues: list[PackageCheck] = field(default_factory=list)


def _canonical(
    dates: pd.Series,
    values: pd.Series,
    *,
    region: str,
    variable: str,
    unit: str,
    data_source: str,
    synthetic: bool,
    source_file: str,
    original_variable: str,
    original_unit: str,
    product: str,
    spatial_resolution: str,
) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates).reset_index(drop=True),
            "region": region,
            "variable": variable,
            "value": values.astype("float64").reset_index(drop=True),
            "unit": unit,
            "data_source": data_source,
            "is_synthetic": [synthetic] * n,
            "product": product,
            "original_variable": original_variable,
            "original_unit": original_unit,
            "temporal_resolution": "monthly",
            "spatial_resolution": spatial_resolution,
            "source_file": source_file,
            "original_value": values.astype("float64").reset_index(drop=True),
            "transformation_note": None,
        }
    )


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _prefixed(checks: list[PackageCheck], prefix: str) -> list[PackageCheck]:
    return [PackageCheck(code=c.code, severity=c.severity, message=f"{prefix}: {c.message}") for c in checks]


def load_observed_global(root: Path) -> tuple[PackageDataset | None, list[PackageCheck]]:
    checks: list[PackageCheck] = []
    parsed: dict[str, ParsedSeries] = {}
    for key, rel in (("precipitation", OBSERVED_PRECIP_FILE), ("random_error", OBSERVED_ERROR_FILE)):
        content = _read(root / rel)
        if content is None:
            checks.append(PackageCheck(code="file_missing", severity="error", message=f"{Path(rel).name}: file not found in {root}."))
            continue
        p = parse_giovanni_csv(content)
        parsed[key] = p
        checks.extend(_prefixed(p.checks, Path(rel).name))
    if "precipitation" not in parsed or not parsed["precipitation"].ok:
        checks.append(PackageCheck(code="observed_unavailable", severity="error", message="The observed global precipitation series could not be loaded; nothing was substituted."))
        return None, checks

    pr = parsed["precipitation"]
    assert pr.data is not None and pr.variable and pr.unit
    frames = [
        _canonical(
            pr.data["date"], pr.data["value"], region=OBSERVED_REGION, variable=pr.variable, unit=pr.unit, data_source=OBSERVED_SOURCE,
            synthetic=False, source_file=Path(OBSERVED_PRECIP_FILE).name, original_variable=pr.column or "", original_unit=f"{pr.unit} (not stated in file)",
            product="GPM_3IMERGM_07 precipitation (merged satellite-gauge, Final Run)", spatial_resolution="global area average",
        )
    ]
    er = parsed.get("random_error")
    files = [Path(OBSERVED_PRECIP_FILE).name]
    if er is not None and er.ok:
        assert er.data is not None and er.variable and er.unit
        same = set(er.data["date"]) == set(pr.data["date"])
        if same:
            checks.append(PackageCheck(code="dates_aligned", severity="info", message=f"Random-error dates match the precipitation dates exactly ({len(pr.data)} months)."))
            frames.append(
                _canonical(
                    er.data["date"], er.data["value"], region=OBSERVED_REGION, variable=er.variable, unit=er.unit, data_source=OBSERVED_SOURCE,
                    synthetic=False, source_file=Path(OBSERVED_ERROR_FILE).name, original_variable=er.column or "", original_unit=f"{er.unit} (not stated in file)",
                    product="GPM_3IMERGM_07 randomError (area average of per-cell random error)", spatial_resolution="global area average",
                )
            )
            files.append(Path(OBSERVED_ERROR_FILE).name)
        else:
            only_e = len(set(er.data["date"]) - set(pr.data["date"]))
            only_p = len(set(pr.data["date"]) - set(er.data["date"]))
            checks.append(PackageCheck(code="dates_misaligned", severity="error", message=f"Random-error dates do not match precipitation dates ({only_e} only in error file, {only_p} only in precipitation file); the random-error series was not loaded."))
    else:
        checks.append(PackageCheck(code="random_error_unavailable", severity="warning", message="The random-error series is not available; precipitation is shown without uncertainty diagnostics."))

    df = pd.concat(frames, ignore_index=True)
    start, end = pr.data["date"].min(), pr.data["date"].max()
    info = DatasetInfo(
        data_class="observed_global",
        label="Observed global data",
        data_source=OBSERVED_SOURCE,
        spatial_scope="Global area average (data bounding box -179.95, -89.95, 179.95, 89.95). Not regional.",
        temporal_coverage=f"{start:%Y-%m} to {end:%Y-%m}, monthly, {len(pr.data)} months",
        unit=RATE_UNIT,
        unit_note=UNIT_SOURCE,
        limitations=OBSERVED_LIMITATIONS,
        source_files=files,
        regional_analysis_allowed=False,
        checks=checks,
    )
    return PackageDataset(OBSERVED_ID, OBSERVED_NAME, "observed_global", df, info, ", ".join(files)), checks


def load_synthetic_regional(root: Path) -> tuple[PackageDataset | None, list[PackageCheck]]:
    checks: list[PackageCheck] = []
    frames: list[pd.DataFrame] = []
    files: list[str] = []
    for region, rel in DEMO_FILES.items():
        content = _read(root / rel)
        name = Path(rel).name
        if content is None:
            checks.append(PackageCheck(code="file_missing", severity="warning", message=f"{name}: file not found; region {region} is not available."))
            continue
        p = parse_regional_demo_csv(content)
        checks.extend(_prefixed(p.checks, name))
        if not p.ok or p.data is None or p.region is None:
            checks.append(PackageCheck(code="region_skipped", severity="error", message=f"{name}: region {region} was not loaded."))
            continue
        for variable, col in (("precipitation", "precipitation"), ("random_error", "random_error")):
            frames.append(
                _canonical(
                    p.data["date"], p.data[col], region=p.region, variable=variable, unit=RATE_UNIT, data_source=DEMO_SOURCE, synthetic=True,
                    source_file=name, original_variable=("precipitation_mm_per_hour" if col == "precipitation" else "uncertainty_random_error_mm_per_hour"),
                    original_unit="mm_per_hour", product="SYNTHETIC DEMO (not a NASA product)", spatial_resolution="synthetic region label only",
                )
            )
        files.append(name)
    if not frames:
        return None, checks
    df = pd.concat(frames, ignore_index=True)
    start, end = df["date"].min(), df["date"].max()
    info = DatasetInfo(
        data_class="synthetic_regional_demo",
        label=SYNTHETIC_BANNER,
        data_source=DEMO_SOURCE,
        spatial_scope="Named demo regions (" + ", ".join(sorted(df["region"].unique())) + "); synthetic labels, no real geography.",
        temporal_coverage=f"{start:%Y-%m} to {end:%Y-%m}, monthly",
        unit=RATE_UNIT,
        unit_note="Copied from the column names (…_mm_per_hour); the values themselves are artificial.",
        limitations=DEMO_LIMITATIONS,
        source_files=files,
        regional_analysis_allowed=True,
        checks=checks,
    )
    return PackageDataset(DEMO_ID, DEMO_NAME, "synthetic_regional_demo", df, info, ", ".join(files)), checks


def load_package(root: Path) -> PackageLoad:
    out = PackageLoad()
    if not root.is_dir():
        out.issues.append(PackageCheck(code="package_missing", severity="warning", message=f"Dataset package folder {root} not found; no packaged datasets were loaded."))
        return out
    for loader in (load_observed_global, load_synthetic_regional):
        ds, checks = loader(root)
        if ds is not None:
            out.datasets.append(ds)
        out.issues.extend(c for c in checks if c.severity in ("error", "warning"))
    return out
