# Methodology

This document describes what EarthTrend Explorer computes, how it chooses the headline result, and what the
numbers cannot tell you. The same content is served by `GET /api/methodology` and shown on the
**Methodology / About** page. Thresholds quoted here are defined in
`backend/app/services/stats/constants.py`.

> **Status.** These methods have been implemented and unit-tested, and the trend tests are cross-checked against
> `pymannkendall` and `scipy.stats.theilslopes`. They have **not** been validated on any real Earth-science product,
> because the NASA dataset has not been supplied. The bundled demo data are synthetic. Treat all output as a
> demonstration of the method until the real dataset is integrated and reviewed by a domain expert.

## 1. What a "trend" means here

A trend is a tendency for a measured variable to rise or fall over time. For each series the app reports:

1. **Direction** - the sign of the estimated slope.
2. **Magnitude** - the slope in the variable's own unit **per year**, and the implied total change over the record
   (slope x time span).
3. **Uncertainty** - a confidence interval for the slope.
4. **Statistical evidence** - a p-value from a trend test, at the significance level chosen in the filters
   (default 0.05; the confidence level is 1 - alpha).

These are reported separately on purpose. Direction, size, significance and practical importance are different
things. **A trend says nothing about cause.**

Time is measured from the real timestamps, in years of 365.25 days. Rows are never assumed to be evenly spaced.

## 2. Data preparation

- Missing values are excluded and counted. They are **never** replaced by zero and **never** interpolated.
- The app measures the sampling of each series from the data: the median step decides `daily`, `weekly`, `monthly`,
  `quarterly`, `annual` or `irregular`, and the share of that regular grid with no valid value (and the longest gap)
  is reported.
- **Aggregation** to quarterly or annual values is optional. It uses the mean of valid values and only for periods with
  at least **75 %** of the expected observations (`AGG_MIN_COVERAGE`); other periods are dropped and counted, not filled.
- A date window can restrict the analysis. The unit is whatever the data declares; nothing is converted.

## 3. Methods

### 3.1 Linear regression (descriptive)

Ordinary least squares of value against elapsed years. Reported: slope per year, intercept, standard error, a
t-based confidence interval, a p-value for "true slope = 0", R-squared and the degrees of freedom. Needs at least 5
valid points. It assumes a linear trend and independent, equal-variance residuals, which environmental series often
violate, so it is shown as a **descriptive fit**, not as the headline test.

### 3.2 Mann-Kendall trend test

A rank-based test (Mann 1945; Kendall 1975). Statistic S counts later observations that are higher minus those that are
lower. The variance includes the **tie correction**, and the z-score uses a **continuity correction**; the p-value is
two-sided from the normal approximation. Kendall's tau is reported. It makes no assumption about the distribution of
the data. The normal approximation is used from **10** valid observations (`MIN_N_TREND`); fewer gives
"insufficient data" rather than a weak result. Series over 20,000 points ask for aggregation (S is O(n squared)).

The implementation is the app's own and is cross-checked against `pymannkendall` in the tests.

A non-significant Mann-Kendall result means the analysis **did not find sufficient evidence** of a monotonic trend. The
app never says that "no trend exists".

### 3.3 Sen's slope

The median of the slopes between every pair of observations, using each pair's real time difference (Sen 1968).
Robust to outliers. Its confidence interval follows Sen (1968) using the Mann-Kendall variance, and matches
`scipy.stats.theilslopes` in the tests. Because it stores all n(n-1)/2 pairwise slopes it is limited to **4,000**
observations per series (`MAX_N_PAIRWISE`); longer series should be aggregated.

### 3.4 Seasonality

For monthly or quarterly data the app removes the Sen's-slope line and tests whether the residuals differ between
months (or quarters) with a **Kruskal-Wallis** test. It also reports eta-squared, the share of residual variance
explained by the season. Seasonality is assessed only with at least **3** full cycles (`MIN_CYCLES`) and 3
observations per season.

If a seasonal pattern is detected (and the user has not turned seasonality off), the **seasonal Mann-Kendall test**
(Hirsch, Slack & Smith 1982) and a **seasonal Sen's slope** are used. They compare each month only with the same month
in other years and sum the per-season statistics. **Seasons are treated as independent**; the covariance-adjusted
variant is not implemented.

The optional "deseasonalized" line in charts subtracts the month-of-year mean of the detrended data. It is a
descriptive aid and **not** a validated seasonal test.

### 3.5 Autocorrelation

Neighbouring observations in environmental series are often alike. That autocorrelation reduces the amount of
independent information, so plain Mann-Kendall and OLS p-values can be **too small** and report trends that are not
there. The app tests the residuals of the fitted trend line (after removing season means when seasonality is in use)
with the **Ljung-Box test** (up to 10 lags, at most one lag per 5 observations), the lag-1 autocorrelation and the
**Durbin-Watson** statistic. "Autocorrelation present" is flagged at a fixed level of 0.05, independent of the
user's alpha. These diagnostics need at least 10 observations and **regular sampling**; if gaps exist they are shown as
approximate. An effective sample size under an AR(1) approximation is reported.

If the series is gap-free, regular and non-seasonal, the **Hamed & Rao (1998)** modified Mann-Kendall test (via
`pymannkendall`) can correct for autocorrelation. For gap-free regular series of at least 20 points the app also
shows an OLS slope with **Newey-West (HAC)** standard errors.

### 3.6 Multiple comparisons

In a regional comparison each region is tested separately. Testing several regions raises the chance of at least one
false positive, so the app shows each region's raw p-value and a **Benjamini-Hochberg** false-discovery-rate adjusted
p-value (Benjamini & Hochberg 1995), computed across the regions that produced a p-value.

## 4. How the headline result is chosen

The result shown first is chosen from the diagnostics, not by the user and not by which test gives the smaller p-value:

| Situation | Headline test | Status label |
| --- | --- | --- |
| Fewer than 10 valid observations | none | **Insufficient data** (with the reason) |
| No significant autocorrelation | Mann-Kendall (seasonal MK if seasonality is in use) | **Standard test** |
| Significant autocorrelation, series gap-free, regular and non-seasonal | Hamed-Rao corrected MK | **Autocorrelation-corrected** |
| Significant autocorrelation but no valid correction (gaps, seasonal use, ...) | Mann-Kendall (or seasonal MK) | **Exploratory (uncorrected)** - the p-value is probably too small |
| Autocorrelation could not be assessed | Mann-Kendall (or seasonal MK) | **Exploratory (uncorrected)** |
| Seasonal MK used | seasonal MK | Standard if no autocorrelation flagged, otherwise **Exploratory (uncorrected)** |

The reported slope is the Sen's slope (seasonal Sen's slope when the seasonal test is used); if that is unavailable
the OLS slope is used and labelled as such. All other methods remain visible in the *Statistical results* table.

Practical consequence: a strongly seasonal monthly series with autocorrelation will usually be labelled
*exploratory*. Aggregating to annual values removes the seasonal cycle and enables the corrected test; the app
suggests this when it applies.

## 5. Regional comparison

For one variable and several regions the app also checks **comparability** and warns, in this order of seriousness:

- `incompatible_units` - regions report different units. No conversion is applied, so the regions are **not** drawn
  on a common axis and are not compared (the per-region results are still listed in their own units).
- `sampling_mismatch` - different temporal resolutions.
- `no_overlap` / `coverage_mismatch` - observation periods do not overlap, or overlap by less than 90 % of their union.
- `sample_size_mismatch` - the smallest valid count is under 80 % of the largest (different statistical power).
- `missing_data` - more than 10 % of a region's regular grid is missing.
- `insufficient_data` - a region has too few observations for a test.

The comparison text states whether the estimated directions are the same or opposite. It also states that opposite
point estimates are evidence of genuinely opposite trends **only** where each region's trend is itself significant,
and that **differences in slope size are not tested**: that would need a joint model or interval comparison.

## 6. The explanations

Interpretation text (`backend/app/services/explain.py`) is produced by **fixed rules** from the computed numbers.
No LLM or other external AI service is called or required. Each statement lists the numbers it was built from
(*Show the numbers behind this*). The rules:

- never state or imply a cause, and always say that a trend does not identify why;
- never say "no trend exists" - only that the analysis did or did not find sufficient evidence;
- give p-values in the form `p < 0.001` or `p = 0.043`, never `p = 0`;
- distinguish statistical from practical significance;
- label synthetic data as such, and label uncorrected results as exploratory;
- state limitations that apply to the series (autocorrelation, gaps, short record, mixed sampling).

## 7. Limitations

- Results describe the **selected series only**. A region-level series does not represent every location in the region.
- Monotonic-trend tests describe one direction of change across the whole window; they do not detect step changes,
  reversals or non-linear behaviour. Instrument or sampling changes are not assessed.
- Seasonal Mann-Kendall treats seasons as independent; Hamed-Rao is applied only to gap-free regular non-seasonal series.
- Lag-based diagnostics on series with gaps are approximate (gaps are treated as adjacent).
- Sen's slope is capped at 4,000 observations and Mann-Kendall at 20,000.
- A very small change can be significant in a long record, and a large change non-significant in a short, noisy one.
  The app reports the implied change so size can be judged, but it cannot say whether a change matters environmentally.
- No unit conversion, gap filling, spatial aggregation or area-weighting is ever performed automatically.

## References

1. Mann, H. B. (1945). Nonparametric tests against trend. *Econometrica*, 13(3), 245-259. https://doi.org/10.2307/1907187
2. Kendall, M. G. (1975). *Rank Correlation Methods* (4th ed.). Charles Griffin, London.
3. Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau. *Journal of the American Statistical Association*, 63(324), 1379-1389. https://doi.org/10.1080/01621459.1968.10480934
4. Hirsch, R. M., Slack, J. R., & Smith, R. A. (1982). Techniques of trend analysis for monthly water quality data. *Water Resources Research*, 18(1), 107-121. https://doi.org/10.1029/WR018i001p00107
5. Hamed, K. H., & Rao, A. R. (1998). A modified Mann-Kendall trend test for autocorrelated data. *Journal of Hydrology*, 204(1-4), 182-196. https://doi.org/10.1016/S0022-1694(97)00125-X
6. Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate: a practical and powerful approach to multiple testing. *Journal of the Royal Statistical Society: Series B*, 57(1), 289-300. https://doi.org/10.1111/j.2517-6161.1995.tb02031.x
7. Hussain, M., & Mahmud, I. (2019). pyMannKendall: a python package for non parametric Mann Kendall family of trend tests. *Journal of Open Source Software*, 4(39), 1556. https://doi.org/10.21105/joss.01556
8. SciPy documentation: `scipy.stats.theilslopes` (reference implementation used to cross-check Sen's slope).

The DOIs above were checked to resolve through doi.org; the publisher landing pages for items 3, 4 and 6 refused
automated requests, so the article contents were not retrieved by the check.
