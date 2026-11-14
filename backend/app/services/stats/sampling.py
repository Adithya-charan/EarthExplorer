"""Sampling-interval detection, grid-gap accounting and temporal aggregation.

Time is always taken from the actual timestamps. Nothing here assumes that one
row equals one month or one year.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.errors import unprocessable

from .constants import AGG_MIN_COVERAGE, DAYS_PER_YEAR

NOMINAL_STEP_DAYS = {"daily": 1.0, "weekly": 7.0, "monthly": DAYS_PER_YEAR / 12, "quarterly": DAYS_PER_YEAR / 4, "annual": DAYS_PER_YEAR}
SEASONAL_PERIOD = {"monthly": 12, "quarterly": 4}


@dataclass
class Sampling:
    label: str  # daily|weekly|monthly|quarterly|annual|irregular|insufficient
    median_step_days: float | None
    regular: bool
    period: int | None


def to_years(dates: pd.Series, origin: pd.Timestamp | None = None) -> np.ndarray:
    """Elapsed time in (Julian) years from real timestamps."""
    d = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
    origin = origin if origin is not None else d.iloc[0]
    return ((d - origin).dt.total_seconds() / (86400.0 * DAYS_PER_YEAR)).to_numpy(dtype="float64")


def grid_index(label: str, dates: pd.Series, origin: pd.Timestamp | None = None) -> np.ndarray:
    """Integer position of each timestamp on the regular grid implied by ``label``."""
    d = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
    if label == "monthly":
        return (d.dt.year * 12 + d.dt.month - 1).to_numpy(dtype="int64")
    if label == "quarterly":
        return (d.dt.year * 4 + (d.dt.month - 1) // 3).to_numpy(dtype="int64")
    if label == "annual":
        return d.dt.year.to_numpy(dtype="int64")
    origin = origin if origin is not None else d.min()
    days = (d - origin).dt.days.to_numpy(dtype="int64")
    if label == "weekly":
        return days // 7
    return days  # daily


def detect_sampling(dates: pd.Series) -> Sampling:
    d = pd.to_datetime(pd.Series(dates)).drop_duplicates().sort_values().reset_index(drop=True)
    if len(d) < 3:
        return Sampling("insufficient", None, False, None)
    diffs = d.diff().dropna().dt.total_seconds().to_numpy() / 86400.0
    med = float(np.median(diffs))
    if 0.9 <= med <= 1.5:
        label = "daily"
    elif 6 <= med <= 8:
        label = "weekly"
    elif 27 <= med <= 32:
        label = "monthly"
    elif 88 <= med <= 93:
        label = "quarterly"
    elif 360 <= med <= 370:
        label = "annual"
    else:
        return Sampling("irregular", med, False, None)
    steps = np.diff(grid_index(label, d))
    if (steps < 1).any() or (steps == 1).mean() < 0.8:
        return Sampling("irregular", med, False, None)
    return Sampling(label, med, True, SEASONAL_PERIOD.get(label))


@dataclass
class GridStats:
    expected_n: int | None
    grid_missing: int | None
    grid_missing_fraction: float | None
    longest_gap_steps: int | None


def grid_stats(sampling: Sampling, valid_dates: pd.Series) -> GridStats:
    """How many grid steps between the first and last *valid* observation have no valid value."""
    if not sampling.regular or len(valid_dates) == 0:
        return GridStats(None, None, None, None)
    idx = np.unique(grid_index(sampling.label, valid_dates))
    expected = int(idx[-1] - idx[0] + 1)
    missing = expected - len(idx)
    longest = int(np.max(np.diff(idx)) - 1) if len(idx) > 1 else 0
    return GridStats(expected, missing, missing / expected if expected else 0.0, longest)


def season_ids(sampling: Sampling, dates: pd.Series) -> np.ndarray | None:
    """Season label (month-of-year or quarter-of-year) per observation, or ``None`` if undefined."""
    d = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
    if sampling.label == "monthly":
        return d.dt.month.to_numpy(dtype="int64")
    if sampling.label == "quarterly":
        return ((d.dt.month - 1) // 3 + 1).to_numpy(dtype="int64")
    return None


@dataclass
class AggregationOutcome:
    frame: pd.DataFrame
    expected_per_period: int
    periods_total: int
    periods_dropped: int
    note: str


def aggregate(df: pd.DataFrame, target: str, sampling: Sampling, min_coverage: float = AGG_MIN_COVERAGE) -> AggregationOutcome:
    """Aggregate to calendar quarters or years using the mean of valid values.

    A period receives a value only if at least ``min_coverage`` of its expected
    observations are valid; otherwise it is left missing (never interpolated).
    The period start date is used as the timestamp of the aggregated value.
    """
    if sampling.label not in ("daily", "weekly", "monthly", "quarterly"):
        raise unprocessable(
            "aggregation_not_supported",
            f"Temporal aggregation to {target} needs regularly sampled daily, weekly, monthly or quarterly data; "
            f"this series is '{sampling.label}'.",
        )
    step = NOMINAL_STEP_DAYS[sampling.label]
    period_days = NOMINAL_STEP_DAYS["quarterly" if target == "quarterly" else "annual"]
    if step * 1.5 > period_days:
        raise unprocessable(
            "aggregation_not_supported",
            f"The data are already {sampling.label}; aggregating to {target} is not meaningful.",
        )
    expected = max(1, int(round(period_days / step)))
    needed = math.ceil(min_coverage * expected)
    freq = "Q" if target == "quarterly" else "Y"
    period = df["date"].dt.to_period(freq)
    grouped = df.groupby(period, sort=True)["value"]
    counts = grouped.count()
    means = grouped.mean()
    low = (counts > 0) & (counts < needed)
    means = means.mask(counts < needed)
    frame = pd.DataFrame(
        {"date": counts.index.start_time, "value": means.to_numpy(dtype="float64"), "n_in_period": counts.to_numpy()}
    )
    return AggregationOutcome(
        frame=frame,
        expected_per_period=expected,
        periods_total=len(counts),
        periods_dropped=int(low.sum()),
        note=(
            f"Mean of valid {sampling.label} values per calendar {'quarter' if target == 'quarterly' else 'year'}; "
            f"a period needs at least {needed} of {expected} expected values ({int(min_coverage * 100)} %) or it is left missing. "
            "The period start date is used as its timestamp."
        ),
    )
