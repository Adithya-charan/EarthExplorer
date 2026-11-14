"""Methodology content served at ``GET /api/methodology`` and mirrored in docs/METHODOLOGY.md."""

from __future__ import annotations

from app.schemas import MethodologyReference, MethodologyResponse, MethodologySection
from app.services.stats import constants as c

SECTIONS = [
    MethodologySection(
        id="trend",
        title="What a trend means here",
        body=[
            "A trend is a tendency for a measured variable to rise or fall over time. EarthTrend Explorer reports the "
            "estimated direction, the size of the change per year (in the variable's own unit), and how certain that estimate is.",
            "Direction, magnitude, statistical significance and practical importance are different things and are reported separately. "
            "A trend in a time series says nothing about its cause.",
        ],
    ),
    MethodologySection(
        id="regression",
        title="Linear regression (descriptive)",
        body=[
            "Ordinary least squares fits a straight line to value against elapsed time. Time is computed from the real timestamps "
            "in years of 365.25 days, so irregular or gappy series are handled correctly.",
            "The slope is reported with a t-based confidence interval and a p-value for the hypothesis that the true slope is zero. "
            "It assumes the trend is linear and that residuals are independent with equal variance - assumptions that environmental "
            "series often violate. It is shown as a descriptive fit, not as the headline test.",
        ],
    ),
    MethodologySection(
        id="ci",
        title="Confidence intervals",
        body=[
            "A 95 % confidence interval is a range built so that, if the same procedure were repeated on many comparable data sets, about "
            "95 % of such intervals would contain the true slope. If the interval includes zero, the slope estimate is uncertain "
            "under the model.",
            "The confidence level is 1 - alpha, where alpha is the significance threshold chosen in the filters.",
        ],
    ),
    MethodologySection(
        id="mann-kendall",
        title="Mann-Kendall test",
        body=[
            "The Mann-Kendall test is rank based: it counts how many later observations are higher than earlier ones minus how many are "
            "lower (statistic S). It needs no assumption about the shape of the data distribution and ignores outliers' magnitude. "
            "Ties are handled with the standard variance correction and a continuity-corrected normal approximation.",
            f"The normal approximation is only used from {c.MIN_N_TREND} valid observations. A non-significant result means the analysis "
            "did not find sufficient evidence of a monotonic trend; it is not proof that no trend exists.",
        ],
    ),
    MethodologySection(
        id="sen",
        title="Sen's slope",
        body=[
            "Sen's slope is the median of the slopes between every pair of observations, using the real time difference of each pair. "
            "It is robust to outliers. Its confidence interval follows Sen (1968), using the Mann-Kendall variance.",
            f"Because it stores every pairwise slope it is limited to {c.MAX_N_PAIRWISE} observations; for longer series, aggregate to quarterly or annual values.",
        ],
    ),
    MethodologySection(
        id="seasonality",
        title="Seasonality and deseasonalization",
        body=[
            "For monthly or quarterly data the app checks for a seasonal cycle by removing the Sen's-slope trend and testing whether the "
            "residuals differ between months (or quarters) with a Kruskal-Wallis test. The share of residual variance explained by the season is also reported.",
            "When seasonality is detected and at least "
            f"{c.MIN_CYCLES} cycles are available, the seasonal Mann-Kendall test (Hirsch et al. 1982) and a seasonal Sen's slope are used. "
            "These compare each month only with the same month in other years. Seasons are treated as independent; the covariance-adjusted "
            "version is not implemented.",
            "The 'deseasonalized' line shown in charts subtracts the month-of-year mean of the detrended data. It is a descriptive aid only and is NOT a validated seasonal test.",
        ],
    ),
    MethodologySection(
        id="autocorrelation",
        title="Autocorrelation",
        body=[
            "Neighbouring observations in environmental series are often similar to one another. This autocorrelation reduces the amount of "
            "independent information, so the plain Mann-Kendall and OLS p-values can be too small and report trends that are not there.",
            "The app tests the detrended residuals (Ljung-Box test, lag-1 autocorrelation, Durbin-Watson). If significant autocorrelation is "
            "found and the series is gap-free, regular and non-seasonal, the Hamed & Rao (1998) corrected test becomes the headline result. "
            "Otherwise the result is labelled 'exploratory - uncorrected'. An OLS slope with Newey-West standard errors is shown for gap-free regular series of "
            f"{c.MIN_N_HAC} or more observations.",
        ],
    ),
    MethodologySection(
        id="missing",
        title="Missing data and irregular sampling",
        body=[
            "Missing values are excluded and counted. They are never replaced by zero and never interpolated. The app reports how many steps of the "
            "regular grid have no valid value and the longest gap.",
            "Aggregation to quarters or years uses the mean of valid values and only for periods with at least "
            f"{int(c.AGG_MIN_COVERAGE * 100)} % of the expected observations.",
        ],
    ),
    MethodologySection(
        id="multiple",
        title="Multiple comparisons",
        body=[
            "Testing several regions at once raises the chance of at least one false positive. In a regional comparison the app shows each "
            "region's raw p-value and a Benjamini-Hochberg false-discovery-rate adjusted p-value.",
        ],
    ),
    MethodologySection(
        id="significance",
        title="Statistical versus practical significance",
        body=[
            "A very small change can be statistically significant in a long record, and a large change can be non-significant in a short, noisy one. "
            "The app reports the implied change over the record so size can be judged, but it cannot say whether a change is environmentally important.",
        ],
    ),
    MethodologySection(
        id="limits",
        title="Limitations and assumptions",
        body=[
            "Results describe the selected series only. A region-level series does not represent every location in the region.",
            "No unit conversion, gap filling or spatial aggregation is performed automatically. No external AI model is used: the explanations are produced by fixed rules from the computed numbers.",
            "Until the NASA dataset is supplied and verified, every result is based on synthetic demo data or on a file you upload yourself.",
        ],
    ),
]

REFERENCES = [
    MethodologyReference(
        citation="Mann, H. B. (1945). Nonparametric tests against trend. Econometrica, 13(3), 245-259.",
        url="https://doi.org/10.2307/1907187",
    ),
    MethodologyReference(citation="Kendall, M. G. (1975). Rank Correlation Methods (4th ed.). Charles Griffin, London."),
    MethodologyReference(
        citation="Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau. Journal of the American Statistical Association, 63(324), 1379-1389.",
        url="https://doi.org/10.1080/01621459.1968.10480934",
    ),
    MethodologyReference(
        citation="Hirsch, R. M., Slack, J. R., & Smith, R. A. (1982). Techniques of trend analysis for monthly water quality data. Water Resources Research, 18(1), 107-121.",
        url="https://doi.org/10.1029/WR018i001p00107",
    ),
    MethodologyReference(
        citation="Hamed, K. H., & Rao, A. R. (1998). A modified Mann-Kendall trend test for autocorrelated data. Journal of Hydrology, 204(1-4), 182-196.",
        url="https://doi.org/10.1016/S0022-1694(97)00125-X",
    ),
    MethodologyReference(
        citation="Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate: a practical and powerful approach to multiple testing. Journal of the Royal Statistical Society: Series B, 57(1), 289-300.",
        url="https://doi.org/10.1111/j.2517-6161.1995.tb02031.x",
    ),
    MethodologyReference(
        citation="Hussain, M., & Mahmud, I. (2019). pyMannKendall: a python package for non parametric Mann Kendall family of trend tests. Journal of Open Source Software, 4(39), 1556.",
        url="https://doi.org/10.21105/joss.01556",
    ),
    MethodologyReference(
        citation="SciPy documentation: scipy.stats.theilslopes (used as the reference implementation for cross-checking Sen's slope).",
        url="https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.theilslopes.html",
    ),
]


def methodology() -> MethodologyResponse:
    return MethodologyResponse(
        sections=SECTIONS,
        references=REFERENCES,
        defaults={
            "alpha": 0.05,
            "min_n_regression": c.MIN_N_REGRESSION,
            "min_n_trend": c.MIN_N_TREND,
            "max_n_pairwise": c.MAX_N_PAIRWISE,
            "min_cycles_for_seasonality": c.MIN_CYCLES,
            "min_per_season": c.MIN_PER_SEASON,
            "aggregation_min_coverage": c.AGG_MIN_COVERAGE,
            "autocorrelation_flag_alpha": c.AUTOCORR_ALPHA,
        },
    )
