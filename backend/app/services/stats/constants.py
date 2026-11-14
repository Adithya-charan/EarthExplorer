"""Thresholds used by the statistics services. Each one is documented in docs/METHODOLOGY.md."""

MIN_N_REGRESSION = 5  # OLS needs at least 3 residual degrees of freedom for a meaningful t-based interval
MIN_N_TREND = 10  # Mann-Kendall / Sen: normal approximation is only defensible from ~10 observations
MIN_N_AUTOCORR = 10  # Ljung-Box / lag-1 diagnostics
MIN_N_HAC = 20  # Newey-West needs a reasonably long, gap-free series
MAX_N_PAIRWISE = 4000  # exact Sen's slope stores all n(n-1)/2 pairwise slopes; above this ask for aggregation
MAX_N_MK = 20000  # Mann-Kendall S is O(n^2); above this ask for aggregation
MIN_PER_SEASON = 3  # observations a season needs before it enters the seasonal test
MIN_SEASONS_FRACTION = 0.5  # fraction of seasons that must be usable
MIN_CYCLES = 3  # full seasonal cycles needed to assess seasonality
AUTOCORR_ALPHA = 0.05  # fixed level for the "autocorrelation present" flag (independent of the user's alpha)
AGG_MIN_COVERAGE = 0.75  # share of expected observations a period needs to receive an aggregated value
GAP_WARN_FRACTION = 0.10  # warn when more than 10 % of the regular grid is missing
DAYS_PER_YEAR = 365.25
