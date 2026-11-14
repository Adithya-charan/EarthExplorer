import Link from "next/link";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, CircleHelp, Minus } from "lucide-react";
import type {
  AnalysisWarning,
  AnalyzeResponse,
  Direction,
  Explanation,
  MannKendallResult,
  PrimaryStatus,
} from "@/lib/types";
import {
  DIRECTION_LABEL,
  PRIMARY_STATUS_HELP,
  primaryStatusHelp,
  PRIMARY_STATUS_LABEL,
  TREND_LABEL,
  fmtDate,
  fmtInt,
  fmtNum,
  fmtP,
  fmtPct,
  fmtSigned,
} from "@/lib/format";
import { Badge, Callout, Card, CardBody, CardHeader, MetricCard } from "@/components/ui/primitives";

export function DirectionBadge({ direction }: { direction: Direction }) {
  const icon =
    direction === "increasing" ? (
      <ArrowUpRight aria-hidden="true" size={14} />
    ) : direction === "decreasing" ? (
      <ArrowDownRight aria-hidden="true" size={14} />
    ) : direction === "flat" ? (
      <Minus aria-hidden="true" size={14} />
    ) : (
      <CircleHelp aria-hidden="true" size={14} />
    );
  return (
    <Badge tone={direction === "unknown" ? "neutral" : "info"}>
      {icon}
      {DIRECTION_LABEL[direction]}
    </Badge>
  );
}

export function StatusBadge({ status, help }: { status: PrimaryStatus; help?: string }) {
  const tone = status === "exploratory_uncorrected" ? "warn" : status === "insufficient_data" ? "neutral" : "accent";
  return (
    <Badge tone={tone} title={help ?? PRIMARY_STATUS_HELP[status]}>
      {PRIMARY_STATUS_LABEL[status]}
    </Badge>
  );
}

export function WarningsList({ warnings, title = "Cautions" }: { warnings: AnalysisWarning[]; title?: string }) {
  if (warnings.length === 0) return null;
  return (
    <Callout tone="warn" role="note" icon={<AlertTriangle size={18} />} title={title}>
      <ul className="list-disc space-y-1 pl-5" data-testid="warnings">
        {warnings.map((w) => (
          <li key={w.code + w.message}>{w.message}</li>
        ))}
      </ul>
    </Callout>
  );
}

/** Headline result: what the primary test says, with the estimate, its uncertainty and its standing. */
export function TrendSummary({ analysis }: { analysis: AnalyzeResponse }) {
  const { primary: p, coverage, sampling } = analysis;
  const unit = analysis.unit;
  const statusHelp = primaryStatusHelp(p.status, analysis);
  const ci =
    p.slope_ci_low !== null && p.slope_ci_high !== null
      ? `${fmtSigned(p.slope_ci_low, 3)} to ${fmtSigned(p.slope_ci_high, 3)}`
      : "n/a";

  return (
    <Card aria-labelledby="summary-title">
      <CardHeader
        id="summary-title"
        title="Trend summary"
        subtitle={`${analysis.request.variable} · ${analysis.request.region} · ${fmtDate(coverage.first_date)} to ${fmtDate(coverage.last_date)}`}
        actions={
          <>
            <StatusBadge status={p.status} help={statusHelp} />
          </>
        }
      />
      <CardBody>
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-lg font-semibold text-ink" data-testid="trend-label">
            {TREND_LABEL[p.trend]}
          </p>
          {p.available ? (
            <span className="flex items-center gap-1.5 text-sm text-muted">
              Estimated direction: <DirectionBadge direction={p.estimated_direction} />
            </span>
          ) : null}
        </div>
        <p className="mt-1 text-sm text-muted" data-testid="status-help">{statusHelp}</p>

        {p.available ? (
          <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard
              label="Slope"
              value={
                <span data-testid="slope-value">
                  {fmtSigned(p.slope_per_year, 3)}
                </span>
              }
              hint={`${p.slope_unit}${p.slope_method ? ` · ${p.slope_method}` : ""}`}
            />
            <MetricCard
              label={`${fmtPct(1 - p.alpha)} interval`}
              value={<span className="text-xl">{ci}</span>}
              hint={p.slope_unit}
            />
            <MetricCard
              label="p-value"
              value={<span data-testid="p-value">{fmtP(p.p_value)}</span>}
              hint={`${p.test_name ?? "test"} · α = ${p.alpha}`}
            />
            <MetricCard
              label="Valid observations"
              value={fmtInt(coverage.n_valid)}
              hint={`${fmtInt(coverage.n_missing_values)} missing of ${fmtInt(coverage.n_rows)} rows`}
            />
          </div>
        ) : (
          <div className="mt-4">
            <Callout tone="info" role="status" title="No trend estimate">
              {p.reason ?? "There are too few valid observations to estimate a trend."}
            </Callout>
          </div>
        )}

        <dl className="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <Fact label="Unit" value={unit || "n/a"} />
          <Fact label="Sampling" value={`${sampling.label}${sampling.regular ? "" : " (irregular)"}`} />
          <Fact
            label="Gaps in regular grid"
            value={
              sampling.grid_missing_fraction === null
                ? "n/a"
                : `${fmtInt(sampling.grid_missing)} periods (${fmtPct(sampling.grid_missing_fraction)})`
            }
          />
          <Fact label="Time span" value={coverage.span_years === null ? "n/a" : `${fmtNum(coverage.span_years, 3)} years`} />
          <Fact
            label="Total change over period"
            value={
              p.total_change_over_period === null
                ? "n/a"
                : `${fmtSigned(p.total_change_over_period, 3)} ${unit} (slope × span)`
            }
          />
          <Fact
            label="Aggregation"
            value={
              analysis.aggregation.method === "none"
                ? "None (native resolution)"
                : `${analysis.aggregation.method} mean${
                    analysis.aggregation.periods_dropped_low_coverage
                      ? `, ${analysis.aggregation.periods_dropped_low_coverage} low-coverage period(s) dropped`
                      : ""
                  }`
            }
          />
        </dl>
      </CardBody>
    </Card>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="tabular font-medium text-ink">{value}</dd>
    </div>
  );
}

function mkRow(m: MannKendallResult | null, alphaLabel: string) {
  if (!m) return null;
  return {
    name: m.test_name,
    estimate: `τ = ${fmtSigned(m.tau, 3)}`,
    ci: "—",
    p: fmtP(m.p_value),
    note: `${m.trend === "no_clear_trend" ? "No clear monotonic trend" : `${m.trend} trend`} at ${alphaLabel}; n = ${m.n}${
      m.notes.length ? `. ${m.notes.join(" ")}` : ""
    }`,
    significant: m.significant,
  };
}

/** Every method that was computed, side by side. The headline result above is one row of this table. */
export function StatisticalResults({ analysis }: { analysis: AnalyzeResponse }) {
  const a = analysis;
  const alphaLabel = `α = ${a.primary.alpha}`;
  const rows: { name: string; estimate: string; ci: string; p: string; note: string; significant: boolean | null }[] = [];

  if (a.linear_regression) {
    const r = a.linear_regression;
    rows.push({
      name: r.test_name,
      estimate: `${fmtSigned(r.slope_per_year, 3)} ${a.primary.slope_unit}`,
      ci: `${fmtSigned(r.ci_low, 3)} to ${fmtSigned(r.ci_high, 3)}`,
      p: fmtP(r.p_value),
      note: `R² = ${fmtNum(r.r_squared, 3)}; df = ${r.df}. Assumes independent residuals.`,
      significant: r.significant,
    });
  }
  if (a.linear_regression_hac) {
    const r = a.linear_regression_hac;
    rows.push({
      name: r.test_name,
      estimate: `${fmtSigned(r.slope_per_year, 3)} ${a.primary.slope_unit}`,
      ci: `${fmtSigned(r.ci_low, 3)} to ${fmtSigned(r.ci_high, 3)}`,
      p: fmtP(r.p_value),
      note: `Newey–West standard errors, ${r.maxlags} lags (robust to autocorrelation).`,
      significant: r.significant,
    });
  }
  for (const m of [a.mann_kendall, a.seasonal_mann_kendall, a.mann_kendall_hamed_rao]) {
    const row = mkRow(m, alphaLabel);
    if (row) rows.push(row);
  }
  if (a.sens_slope) {
    const s = a.sens_slope;
    rows.push({
      name: s.method_name,
      estimate: `${fmtSigned(s.slope_per_year, 3)} ${a.primary.slope_unit}`,
      ci: s.ci_low !== null && s.ci_high !== null ? `${fmtSigned(s.ci_low, 3)} to ${fmtSigned(s.ci_high, 3)}` : "n/a",
      p: "—",
      note: `${fmtInt(s.n_pairs)} pairwise slopes. ${
        s.ci_excludes_zero === null ? "" : s.ci_excludes_zero ? "Interval excludes zero." : "Interval includes zero."
      }`,
      significant: s.ci_excludes_zero,
    });
  }

  const ac = a.autocorrelation;
  const se = a.seasonality;

  return (
    <Card aria-labelledby="stats-title">
      <CardHeader
        id="stats-title"
        title="Statistical results"
        subtitle="All computed methods. The headline result is chosen by the diagnostics below."
      />
      <CardBody className="space-y-5">
        {rows.length === 0 ? (
          <p className="text-sm text-muted">No tests were computed because the series has too few valid observations.</p>
        ) : (
          <div className="overflow-x-auto rounded-md border border-line">
            <table className="w-full min-w-[720px] text-left text-sm" data-testid="stats-table">
              <caption className="sr-only">Trend statistics by method</caption>
              <thead className="bg-surface-muted text-xs text-muted">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Method</th>
                  <th scope="col" className="px-3 py-2 font-medium">Estimate</th>
                  <th scope="col" className="px-3 py-2 font-medium">Interval</th>
                  <th scope="col" className="px-3 py-2 font-medium">p-value</th>
                  <th scope="col" className="px-3 py-2 font-medium">Notes</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.name} className="border-t border-line align-top">
                    <th scope="row" className="px-3 py-2 font-medium text-ink">{r.name}</th>
                    <td className="tabular px-3 py-2">{r.estimate}</td>
                    <td className="tabular px-3 py-2">{r.ci}</td>
                    <td className="tabular px-3 py-2">{r.p}</td>
                    <td className="px-3 py-2 text-muted">{r.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <h3 className="text-sm font-semibold text-ink">Autocorrelation check</h3>
            {ac.evaluated ? (
              <dl className="mt-2 space-y-1 text-sm">
                <Fact label="Lag-1 autocorrelation" value={fmtNum(ac.lag1, 3)} />
                <Fact label="Durbin–Watson" value={fmtNum(ac.durbin_watson, 3)} />
                <Fact
                  label={`Ljung–Box (${ac.ljung_box_lags ?? "?"} lags)`}
                  value={`p ${fmtP(ac.ljung_box_p).startsWith("<") ? fmtP(ac.ljung_box_p) : `= ${fmtP(ac.ljung_box_p)}`}${ac.flagged ? " (flagged)" : ""}`}
                />
                {ac.correction_applied ? <Fact label="Correction" value={ac.correction_method ?? "applied"} /> : null}
              </dl>
            ) : (
              <p className="mt-2 text-sm text-muted">{ac.reason_not_evaluated ?? "Not evaluated."}</p>
            )}
            {ac.note ? <p className="mt-2 text-xs text-muted">{ac.note}</p> : null}
          </div>
          <div>
            <h3 className="text-sm font-semibold text-ink">Seasonality check</h3>
            <p className="mt-2 text-sm text-muted">{se.note}</p>
            {se.assessed ? (
              <dl className="mt-2 space-y-1 text-sm">
                <Fact label="Seasonal pattern detected" value={se.detected ? "Yes" : "No"} />
                <Fact label="Kruskal–Wallis p" value={fmtP(se.kruskal_p)} />
                <Fact label="Trend method used" value={se.method_used === "seasonal_mann_kendall" ? "Seasonal Mann–Kendall" : "Standard"} />
              </dl>
            ) : null}
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

/** Rule-based explanation. Each statement lists the exact statistics it was built from. */
export function ExplanationPanel({ explanation, title = "Plain-language interpretation" }: { explanation: Explanation | null; title?: string }) {
  if (!explanation) return null;
  return (
    <Card aria-labelledby="explain-title">
      <CardHeader
        id="explain-title"
        title={title}
        subtitle="Generated by fixed rules from the computed statistics. No AI service is used and every sentence is traceable."
      />
      <CardBody className="space-y-4" >
        <div data-testid="explanation">
          {explanation.sections.map((s) => (
            <section key={s.heading} className="mb-4 last:mb-0">
              <h3 className="text-sm font-semibold text-ink">{s.heading}</h3>
              <ul className="mt-1.5 space-y-2">
                {s.statements.map((st, i) => (
                  <li key={i} className="text-sm text-ink-soft">
                    <p>{st.text}</p>
                    {st.evidence.length > 0 ? (
                      <details className="mt-0.5">
                        <summary className="cursor-pointer text-xs text-muted hover:text-ink">Show the numbers behind this</summary>
                        <dl className="mt-1 grid gap-x-4 gap-y-0.5 rounded-md bg-surface-muted px-3 py-2 text-xs sm:grid-cols-2">
                          {st.evidence.map((e) => (
                            <div key={e.label} className="flex justify-between gap-3">
                              <dt className="text-muted">{e.label}</dt>
                              <dd className="tabular font-medium text-ink">{e.value}</dd>
                            </div>
                          ))}
                        </dl>
                      </details>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

export function MethodDetails({ assumptions }: { assumptions: string[] }) {
  return (
    <Card aria-labelledby="method-title">
      <CardHeader
        id="method-title"
        title="Methods and assumptions"
        subtitle="What these results rely on, and what they cannot show."
        actions={
          <Link href="/methodology" className="text-sm font-medium text-accent hover:underline">
            Full methodology
          </Link>
        }
      />
      <CardBody>
        <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-soft">
          {assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
          <li>A statistical trend describes the numbers in the selected window; it does not identify causes.</li>
        </ul>
      </CardBody>
    </Card>
  );
}
