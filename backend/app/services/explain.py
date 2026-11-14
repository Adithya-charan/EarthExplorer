"""Deterministic, evidence-based explanations.

Every sentence is produced by a fixed rule from the numbers in an ``AnalyzeResponse`` or
``CompareResponse``. No language model, no network access, no random choices: identical
inputs always give identical text. Each statement carries the evidence (label/value pairs)
that supports it so the UI can show where the words come from.
"""

from __future__ import annotations

from app.schemas import (
    AnalyzeResponse,
    CompareResponse,
    Explanation,
    ExplanationSection,
    ExplanationStatement,
)

GENERATOR = "deterministic-rules-v1"


def g(x: float | None, digits: int = 4) -> str:
    """Compact, locale-independent number formatting."""
    if x is None:
        return "n/a"
    return f"{x:.{digits}g}"


def sg(x: float | None, digits: int = 4) -> str:
    """Signed number formatting."""
    if x is None:
        return "n/a"
    return f"{x:+.{digits}g}"


def pv(p: float | None) -> str:
    if p is None:
        return "n/a"
    return "< 0.001" if p < 0.001 else f"= {p:.3f}"


def st(text: str, **evidence: str) -> ExplanationStatement:
    return ExplanationStatement(text=text, evidence=[{"label": k.replace("_", " "), "value": v} for k, v in evidence.items()])


DIRECTION_WORD = {"increasing": "increasing", "decreasing": "decreasing", "flat": "flat", "unknown": "undetermined"}


# --------------------------------------------------------------------------
# Single series
# --------------------------------------------------------------------------
def explain_analysis(a: AnalyzeResponse) -> Explanation:
    p = a.primary
    cl = f"{(1 - p.alpha) * 100:g}%"
    result: list[ExplanationStatement] = []
    interp: list[ExplanationStatement] = []
    limits: list[ExplanationStatement] = []

    if a.provenance.is_synthetic:
        result.append(
            st(
                "These results come from synthetic demo data (artificial numbers). They demonstrate the method and are not findings about the real Earth system.",
                dataset=a.provenance.dataset_name,
                is_synthetic="true",
            )
        )

    c = a.coverage
    result.append(
        st(
            f"The analysis used {c.n_valid} valid observations of {a.request.variable} for {a.request.region} "
            f"between {c.first_date} and {c.last_date} ({g(c.span_years, 3)} years), sampled {a.sampling.label}.",
            valid_observations=str(c.n_valid),
            records=str(c.n_rows),
            period=f"{c.first_date} to {c.last_date}",
        )
    )

    if not p.available:
        result.append(st(f"No trend test could be run: {p.reason}", valid_observations=str(c.n_valid), minimum_required="10"))
        interp.append(
            st(
                "With this little data, the analysis cannot say anything reliable about the direction or size of a trend.",
                valid_observations=str(c.n_valid),
            )
        )
    else:
        slope_ev = dict(
            slope=f"{sg(p.slope_per_year)} {p.slope_unit}",
            method=p.slope_method or "n/a",
            confidence_interval=f"{g(p.slope_ci_low)} to {g(p.slope_ci_high)}",
        )
        result.append(
            st(
                f"The estimated rate of change is {sg(p.slope_per_year)} {p.slope_unit} ({p.slope_method}; "
                f"{cl} confidence interval {g(p.slope_ci_low)} to {g(p.slope_ci_high)}).",
                **slope_ev,
            )
        )
        z_note = "below" if p.significant else "not below"
        result.append(
            st(
                f"{p.test_name}: p {pv(p.p_value)}, which is {z_note} the significance threshold of {g(p.alpha)}.",
                test=p.test_name or "n/a",
                p_value=g(p.p_value),
                threshold=g(p.alpha),
            )
        )
        if a.linear_regression:
            o = a.linear_regression
            result.append(
                st(
                    f"As a descriptive straight-line fit, ordinary least squares gives {sg(o.slope_per_year)} {p.slope_unit} "
                    f"({cl} CI {g(o.ci_low)} to {g(o.ci_high)}, p {pv(o.p_value)}, R² = {g(o.r_squared, 3)}).",
                    ols_slope=g(o.slope_per_year),
                    ols_ci=f"{g(o.ci_low)} to {g(o.ci_high)}",
                    ols_p_value=g(o.p_value),
                    r_squared=g(o.r_squared, 3),
                )
            )

        # --- interpretation, strictly rule-based ---
        if p.significant:
            word = DIRECTION_WORD[p.trend if p.trend in ("increasing", "decreasing") else p.estimated_direction]
            interp.append(
                st(
                    f"At the {g(p.alpha)} level the analysis found statistical evidence of a monotonic {word} trend. "
                    f"The fitted rate implies a change of about {sg(p.total_change_over_period)} {p.unit} over the {g(c.span_years, 3)}-year record.",
                    trend=word,
                    p_value=g(p.p_value),
                    implied_total_change=f"{sg(p.total_change_over_period)} {p.unit}",
                )
            )
        else:
            direction = DIRECTION_WORD[p.estimated_direction]
            interp.append(
                st(
                    "The analysis did not find sufficient statistical evidence of a monotonic trend at the "
                    f"{g(p.alpha)} level. This does not show that no trend exists: a real trend can go undetected when "
                    "the record is short, noisy or sparse.",
                    p_value=g(p.p_value),
                    threshold=g(p.alpha),
                    valid_observations=str(c.n_valid),
                )
            )
            if p.estimated_direction in ("increasing", "decreasing"):
                interp.append(
                    st(
                        f"The point estimate of the slope points {direction}, but it is not statistically distinguishable from no change here.",
                        estimated_direction=direction,
                        slope=f"{sg(p.slope_per_year)} {p.slope_unit}",
                    )
                )
        if p.slope_ci_low is not None and p.slope_ci_high is not None and p.slope_ci_low <= 0 <= p.slope_ci_high:
            interp.append(
                st(
                    f"The {cl} confidence interval for the slope ({g(p.slope_ci_low)} to {g(p.slope_ci_high)}) includes zero, "
                    "so the slope estimate is uncertain under the fitted model.",
                    confidence_interval=f"{g(p.slope_ci_low)} to {g(p.slope_ci_high)}",
                )
            )
        if a.linear_regression and p.slope_per_year is not None and p.slope_per_year * a.linear_regression.slope_per_year < 0:
            interp.append(
                st(
                    "Sen's slope and the ordinary-least-squares slope have opposite signs, which suggests the straight-line fit is "
                    "sensitive to a few extreme values or to non-linear behaviour.",
                    sen_or_primary_slope=g(p.slope_per_year),
                    ols_slope=g(a.linear_regression.slope_per_year),
                )
            )
        interp.append(
            st(
                "Statistical significance is not the same as practical or environmental significance. "
                "Whether a change of this size matters cannot be judged from the numbers alone.",
            )
        )

    # --- limitations ---
    ac = a.autocorrelation
    if p.available:
        if p.status == "autocorrelation_corrected":
            limits.append(
                st(
                    "The residuals showed significant autocorrelation, so the Hamed & Rao (1998) corrected Mann-Kendall test is used as the headline result.",
                    ljung_box_p=g(ac.ljung_box_p),
                    lag1_autocorrelation=g(ac.lag1),
                )
            )
        elif p.status == "exploratory_uncorrected":
            if ac.evaluated and ac.flagged:
                limits.append(
                    st(
                        "Autocorrelation was assessed and is significant in the residuals, but it was not corrected "
                        + (
                            "(the Hamed-Rao correction is not available for the seasonal analysis path), "
                            if "seasonal" in (p.test_name or "").lower()
                            else "(no valid correction is available for this series), "
                        )
                        + "so the p-value is probably too small. Treat this as an uncorrected, exploratory result.",
                        ljung_box_p=g(ac.ljung_box_p),
                        lag1_autocorrelation=g(ac.lag1),
                    )
                )
            else:
                limits.append(
                    st(
                        "Autocorrelation could not be assessed for this series, so the p-value is an uncorrected, exploratory value.",
                        reason=ac.reason_not_evaluated or "n/a",
                    )
                )
        else:
            limits.append(
                st(
                    "No significant autocorrelation was detected in the residuals, but this check does not guarantee that the observations are independent.",
                    ljung_box_p=g(ac.ljung_box_p),
                    lag1_autocorrelation=g(ac.lag1),
                )
            )
    if a.seasonality.assessed:
        limits.append(
            st(a.seasonality.note, kruskal_wallis_p=g(a.seasonality.kruskal_p), seasonal_variance_share=g(a.seasonality.eta_squared, 3))
        )
    for w in a.warnings:
        if w.code in ("synthetic_data", "autocorrelation_uncorrected", "autocorrelation_unknown", "seasonality_ignored", "seasonality_unaccounted"):
            continue
        limits.append(st(w.message))
    limits.append(
        st(
            "A trend describes how the numbers change over time; it does not identify why. Confounding factors, changes in "
            "instruments or sampling, and other drivers are not assessed here."
        )
    )

    sections = [
        ExplanationSection(heading="Statistical result", statements=result),
        ExplanationSection(heading="Interpretation", statements=interp),
        ExplanationSection(heading="Limitations", statements=limits),
    ]
    return Explanation(generator=GENERATOR, uses_external_ai=False, sections=[s for s in sections if s.statements])


# --------------------------------------------------------------------------
# Regional comparison
# --------------------------------------------------------------------------
def explain_comparison(c: CompareResponse) -> Explanation:
    alpha = c.request.alpha
    result: list[ExplanationStatement] = []
    interp: list[ExplanationStatement] = []
    limits: list[ExplanationStatement] = []

    if c.provenance.is_synthetic:
        result.append(
            st(
                "These results come from synthetic demo data (artificial numbers). They demonstrate the method and are not findings about the real Earth system.",
                dataset=c.provenance.dataset_name,
                is_synthetic="true",
            )
        )

    for row in c.rows:
        if row.trend == "insufficient_data":
            result.append(st(f"{row.region}: too few valid observations ({row.n_valid}) for a trend test.", valid_observations=str(row.n_valid)))
            continue
        word = DIRECTION_WORD[row.estimated_direction]
        sig = "statistically significant" if row.significant_raw else "not statistically significant"
        adj = (
            f"; Benjamini-Hochberg adjusted p {pv(row.p_value_adjusted_bh)}"
            if row.p_value_adjusted_bh is not None
            else ""
        )
        result.append(
            st(
                f"{row.region}: estimated direction {word}, slope {sg(row.slope_per_year)} {row.unit} per year "
                f"(CI {g(row.slope_ci_low)} to {g(row.slope_ci_high)}), p {pv(row.p_value)} ({sig} at {g(alpha)}){adj}; n = {row.n_valid}.",
                region=row.region,
                slope=sg(row.slope_per_year),
                p_value=g(row.p_value),
                adjusted_p_value=g(row.p_value_adjusted_bh),
                test=row.test_name or "n/a",
                n=str(row.n_valid),
            )
        )

    evaluable = [r for r in c.rows if r.estimated_direction in ("increasing", "decreasing")]
    if not c.comparable:
        interp.append(
            st(
                "The regions use different units, so no comparison of trend direction or size is made. No unit conversion has been applied.",
                units="; ".join(f"{k}: {v}" for k, v in c.units_by_region.items()),
            )
        )
    elif c.direction_summary == "opposite_directions":
        inc = [r.region for r in evaluable if r.estimated_direction == "increasing"]
        dec = [r.region for r in evaluable if r.estimated_direction == "decreasing"]
        interp.append(
            st(
                f"The estimated directions are opposite: increasing in {', '.join(inc)}; decreasing in {', '.join(dec)}.",
                increasing=", ".join(inc),
                decreasing=", ".join(dec),
            )
        )
        sig_adj = [r.region for r in evaluable if r.significant_adjusted]
        interp.append(
            st(
                (
                    f"After Benjamini-Hochberg adjustment, {len(sig_adj)} of {len(evaluable)} regional trends remain statistically significant"
                    + (f" ({', '.join(sig_adj)})." if sig_adj else ".")
                    + " Opposite point estimates are only evidence of genuinely opposite trends where each region's trend is itself significant."
                ),
                significant_after_adjustment=str(len(sig_adj)),
                regions_tested=str(c.n_tests),
            )
        )
    elif c.direction_summary == "same_direction":
        word = DIRECTION_WORD[evaluable[0].estimated_direction]
        sig_adj = [r.region for r in evaluable if r.significant_adjusted]
        interp.append(
            st(
                f"All {len(evaluable)} regions have the same estimated direction ({word}); "
                f"{len(sig_adj)} of {len(evaluable)} are statistically significant after Benjamini-Hochberg adjustment.",
                direction=word,
                significant_after_adjustment=str(len(sig_adj)),
                regions_tested=str(c.n_tests),
            )
        )
    else:
        interp.append(
            st(
                "The regions do not share a clear pattern, or too few regions have enough data to compare directions.",
                regions_with_estimates=str(len(evaluable)),
                regions_requested=str(len(c.rows)),
            )
        )
    interp.append(
        st(
            "Differences between regions in slope size are not tested here; comparing confidence intervals or fitting a joint model "
            "would be needed to claim that one region's trend differs from another's."
        )
    )

    if c.n_tests > 1:
        limits.append(
            st(
                f"{c.n_tests} trend tests were run on the same variable. Testing several regions raises the chance of at least one false positive, "
                "so raw and Benjamini-Hochberg (false discovery rate) adjusted p-values are both shown.",
                tests=str(c.n_tests),
                method=c.multiple_testing_method,
            )
        )
    for w in c.warnings:
        if w.code == "synthetic_data":
            continue
        limits.append(st(w.message))
    statuses = {r.status for r in c.rows if r.status != "insufficient_data"}
    if "exploratory_uncorrected" in statuses:
        limits.append(
            st(
                "At least one regional p-value is an uncorrected, exploratory value because autocorrelation could not be corrected or assessed.",
            )
        )
    limits.append(
        st(
            "Trend direction in each region describes the numbers only; it does not establish a cause, and a region-level series does not "
            "represent every location inside that region."
        )
    )
    sections = [
        ExplanationSection(heading="Statistical result", statements=result),
        ExplanationSection(heading="Interpretation", statements=interp),
        ExplanationSection(heading="Limitations", statements=limits),
    ]
    return Explanation(generator=GENERATOR, uses_external_ai=False, sections=[s for s in sections if s.statements])

