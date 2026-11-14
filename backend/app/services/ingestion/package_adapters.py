"""Parsers for the two packaged CSV families.

* **NASA Giovanni area-averaged time-series CSV** (observed, global): a block of ``Key:,value`` metadata lines, a
  blank line, then ``time, <variable>`` rows. The unit is *not* stored in the file.
* **Synthetic regional demo CSV**: a flat table whose ``dataset_type`` column must carry the synthetic label.

Both parsers only *read and validate*. They never fill, interpolate, round or rescale a value. A value equal to the
file's declared fill value becomes an explicit missing value (and is counted in the checks); anything else that is
not a finite number is reported as an error rather than turned into zero.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field

import pandas as pd

from app.schemas import PackageCheck

SYNTHETIC_LABEL = "SYNTHETIC_DEMO_NOT_NASA_OBSERVATION"
SYNTHETIC_BANNER = "SYNTHETIC DEMO — NOT NASA OBSERVATIONS"
RATE_UNIT = "mm/hr"

# Units are looked up, never guessed: a column that is not in this table has an unknown unit and is rejected.
GIOVANNI_VARIABLES: dict[str, tuple[str, str]] = {
    # substring of the CSV column -> (canonical variable, unit)
    "precipitation": ("precipitation", RATE_UNIT),
    "randomError": ("random_error", RATE_UNIT),
}
UNIT_SOURCE = (
    "Not written inside the Giovanni CSV. Taken from README_DATA_PROVENANCE.txt (precipitation is a rate in mm/hr) "
    "and the GPM_3IMERGM v07 variable metadata."
)


@dataclass
class ParsedSeries:
    data: pd.DataFrame | None  # columns: date (month start), value (float, NaN = missing)
    checks: list[PackageCheck] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    column: str | None = None
    variable: str | None = None
    unit: str | None = None
    fill_value: float | None = None
    n_fill_values: int = 0
    region: str | None = None

    @property
    def ok(self) -> bool:
        return self.data is not None and not any(c.severity == "error" for c in self.checks)


def _chk(checks: list[PackageCheck], severity: str, code: str, message: str) -> None:
    checks.append(PackageCheck(code=code, severity=severity, message=message))  # type: ignore[arg-type]


def _decode(content: bytes, checks: list[PackageCheck]) -> str | None:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        _chk(checks, "error", "encoding", "The file is not valid UTF-8 text.")
        return None


def month_gaps(dates: pd.Series) -> list[pd.Timestamp]:
    """Month starts missing between the first and last date (no value is invented for them)."""
    if dates.empty:
        return []
    full = pd.date_range(dates.min().to_period("M").to_timestamp(), dates.max().to_period("M").to_timestamp(), freq="MS")
    present = set(dates.dt.to_period("M").dt.to_timestamp())
    return [d for d in full if d not in present]


def _finish_dates(df: pd.DataFrame, checks: list[PackageCheck], date_col: str) -> pd.DataFrame | None:
    """Validate dates: parseable, month-start, unique, ordered. Returns a frame with a normalised ``date`` column."""
    parsed = pd.to_datetime(df[date_col], errors="coerce", utc=False)
    bad = int(parsed.isna().sum())
    if bad:
        _chk(checks, "error", "invalid_date", f"{bad} row(s) have a date that cannot be parsed (first: {df[date_col][parsed.isna()].iloc[0]!r}).")
        return None
    df = df.assign(date=parsed)
    off = df[(df["date"].dt.day != 1) | (df["date"].dt.hour != 0) | (df["date"].dt.minute != 0)]
    if len(off):
        _chk(checks, "warning", "not_month_start", f"{len(off)} date(s) are not the first of a month at 00:00; they were kept as given.")
    dup = df["date"].duplicated(keep=False)
    if dup.any():
        _chk(checks, "error", "duplicate_dates", f"{int(df['date'][dup].nunique())} date(s) appear more than once; duplicates are not averaged automatically.")
        return None
    if not df["date"].is_monotonic_increasing:
        _chk(checks, "warning", "unsorted", "Rows were not in date order; they were sorted by date (values unchanged).")
        df = df.sort_values("date")
    return df.reset_index(drop=True)


def _gap_checks(dates: pd.Series, checks: list[PackageCheck]) -> None:
    gaps = month_gaps(dates)
    if gaps:
        shown = ", ".join(g.strftime("%Y-%m") for g in gaps[:12]) + (" …" if len(gaps) > 12 else "")
        _chk(checks, "warning", "missing_months", f"{len(gaps)} month(s) missing inside the covered period: {shown}. They are left absent, not filled.")
    else:
        _chk(checks, "info", "no_missing_months", f"No missing months between {dates.min():%Y-%m} and {dates.max():%Y-%m}.")


def _number(text: str) -> float | None:
    try:
        x = float(text.strip())
    except ValueError:
        return None
    return x if math.isfinite(x) else None


# --------------------------------------------------------------------------------------------------
# Giovanni
# --------------------------------------------------------------------------------------------------
def parse_giovanni_csv(content: bytes) -> ParsedSeries:
    """Parse a Giovanni area-averaged time-series CSV (one variable)."""
    out = ParsedSeries(data=None)
    checks = out.checks
    text = _decode(content, checks)
    if text is None:
        return out
    lines = text.splitlines()
    try:
        blank = next(i for i, ln in enumerate(lines) if not ln.strip())
    except StopIteration:
        _chk(checks, "error", "no_header_block", "No blank line separates the metadata block from the data; this is not a Giovanni time-series CSV.")
        return out

    for row in csv.reader(lines[:blank]):
        if len(row) >= 2 and row[0].strip().endswith(":"):
            out.metadata[row[0].strip().rstrip(":").strip()] = row[1].strip()
    body = [ln for ln in lines[blank + 1 :] if ln.strip()]
    if not body:
        _chk(checks, "error", "no_data", "The file has no data rows after the header.")
        return out
    header = [h.strip() for h in next(csv.reader([body[0]]))]
    if len(header) != 2 or header[0].lower() != "time":
        _chk(checks, "error", "bad_header", f"Expected a 'time, <variable>' header, found {header!r}.")
        return out
    out.column = header[1]

    match = next(((v, u) for key, (v, u) in GIOVANNI_VARIABLES.items() if key in out.column), None)
    if match is None:
        _chk(checks, "error", "unknown_unit", f"The unit of column {out.column!r} is not known, so the file was not loaded (no unit is guessed).")
        return out
    out.variable, out.unit = match
    declared = next((v for k, v in out.metadata.items() if k.lower() in ("unit", "units")), None)
    if declared and declared.strip().lower().replace(" ", "") not in ("mm/hr", "mmhr-1", "mm/hour", "mmhr^-1"):
        _chk(checks, "error", "invalid_unit", f"The file declares unit {declared!r}, which is not the expected rate in mm/hr; it was not loaded.")
        return out

    fill_key = next((k for k in out.metadata if k.lower().startswith("fill value")), None)
    out.fill_value = _number(out.metadata[fill_key]) if fill_key else None
    if fill_key is None:
        _chk(checks, "warning", "no_fill_value", "The metadata declares no fill value, so no value is treated as missing.")

    times: list[str] = []
    raw: list[str] = []
    for ln in body[1:]:
        cells = next(csv.reader([ln]))
        if len(cells) != 2:
            _chk(checks, "error", "ragged_row", f"A data row does not have exactly two cells: {ln[:60]!r}.")
            return out
        times.append(cells[0].strip())
        raw.append(cells[1])
    df = pd.DataFrame({"time": times, "raw": raw})
    values: list[float] = []
    invalid = 0
    n_fill = 0
    for r in df["raw"]:
        x = _number(r)
        if x is None:
            invalid += 1
            values.append(math.nan)
        elif out.fill_value is not None and x == out.fill_value:
            n_fill += 1
            values.append(math.nan)
        else:
            values.append(x)
    if invalid:
        _chk(checks, "error", "invalid_value", f"{invalid} value(s) are not finite numbers; the file was not loaded.")
        return out
    out.n_fill_values = n_fill
    if n_fill:
        _chk(checks, "warning", "fill_values", f"{n_fill} value(s) equal the declared fill value {out.fill_value} and were treated as missing.")
    df["value"] = values
    df = _finish_dates(df, checks, "time")
    if df is None:
        return out
    if df.empty:
        _chk(checks, "error", "no_data", "The file has no data rows.")
        return out
    _gap_checks(df["date"], checks)

    end = out.metadata.get("User End Date")
    if end:
        try:
            req_end = pd.Timestamp(end).tz_localize(None)
            if req_end - df["date"].max() > pd.Timedelta(days=62):
                _chk(checks, "info", "coverage_shorter_than_requested", f"The export requested data up to {req_end:%Y-%m-%d}, but the last available month is {df['date'].max():%Y-%m}. Nothing was added for the later months.")
        except (ValueError, TypeError):
            _chk(checks, "warning", "bad_end_date", f"'User End Date' could not be parsed: {end!r}.")
    if (df["value"].dropna() < 0).any():
        _chk(checks, "error", "negative_precipitation", "Negative rates found; precipitation rate cannot be negative.")
        return out
    _chk(checks, "info", "unit", f"Unit: {out.unit}. {UNIT_SOURCE}")
    out.data = df[["date", "value"]]
    return out


# --------------------------------------------------------------------------------------------------
# Synthetic regional demo
# --------------------------------------------------------------------------------------------------
REGIONAL_REQUIRED = ("date", "precipitation_mm_per_hour", "uncertainty_random_error_mm_per_hour", "region", "dataset_type")


@dataclass
class ParsedRegional:
    data: pd.DataFrame | None  # date, precipitation, random_error (float)
    region: str | None
    checks: list[PackageCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.data is not None and not any(c.severity == "error" for c in self.checks)


def parse_regional_demo_csv(content: bytes) -> ParsedRegional:
    out = ParsedRegional(data=None, region=None)
    checks = out.checks
    text = _decode(content, checks)
    if text is None:
        return out
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except Exception:  # noqa: BLE001 - any parser failure is a malformed file
        _chk(checks, "error", "unreadable", "The file could not be read as CSV.")
        return out
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in REGIONAL_REQUIRED if c not in df.columns]
    if missing:
        _chk(checks, "error", "missing_columns", f"Required column(s) missing: {', '.join(missing)}.")
        return out
    labels = set(df["dataset_type"].str.strip().unique())
    if labels != {SYNTHETIC_LABEL}:
        _chk(checks, "error", "not_labelled_synthetic", f"dataset_type must be {SYNTHETIC_LABEL!r} on every row (found {sorted(labels)!r}); the file was not loaded.")
        return out
    regions = sorted(set(df["region"].str.strip().unique()) - {""})
    if len(regions) != 1:
        _chk(checks, "error", "region_count", f"Expected exactly one region per file, found {regions!r}.")
        return out
    out.region = regions[0]
    frame = pd.DataFrame({"raw_date": df["date"]})
    for src, dst in (("precipitation_mm_per_hour", "precipitation"), ("uncertainty_random_error_mm_per_hour", "random_error")):
        parsed = [_number(v) for v in df[src]]
        if any(p is None for p in parsed):
            _chk(checks, "error", "invalid_value", f"Column {src} has non-numeric or non-finite values; the file was not loaded.")
            return out
        frame[dst] = parsed
    frame = _finish_dates(frame, checks, "raw_date")  # sorts rows together, so values stay aligned with their dates
    if frame is None:
        return out
    frame = frame[["date", "precipitation", "random_error"]]
    if (frame[["precipitation", "random_error"]] < 0).any().any():
        _chk(checks, "error", "negative_value", "Negative precipitation rate or random error found.")
        return out
    _gap_checks(frame["date"], checks)
    _chk(checks, "info", "unit", f"Unit: {RATE_UNIT}, read from the column names (…_mm_per_hour).")
    _chk(checks, "info", "synthetic", f"Every row is labelled {SYNTHETIC_LABEL}. {SYNTHETIC_BANNER}.")
    out.data = frame
    return out
