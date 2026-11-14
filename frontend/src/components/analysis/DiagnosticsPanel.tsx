"use client";

import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { fmtDate, fmtNum, fmtPct } from "@/lib/format";
import type { AutocorrelationResult } from "@/lib/types";
import { Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Data diagnostics for the selected series: missingness, month-of-year summary, autocorrelation and, when the
 * dataset has one, how the random-error series relates to the values. Everything comes from GET /api/diagnostics.
 */
export function DiagnosticsPanel({ datasetId, variable, region }: { datasetId: string; variable: string; region: string }) {
  const q = { dataset_id: datasetId, variable, region };
  const res = useApi((signal) => api.diagnostics(q, signal), `diag:${datasetId}|${variable}|${region}`);
  if (res.loading) return <LoadingState label="Computing data diagnostics" variant="cards" />;
  if (res.error) return <ErrorState title="Diagnostics unavailable" error={res.error} onRetry={res.reload} />;
  const d = res.data;
  if (!d) return null;
  const unit = d.unit ?? "";
  const m = d.missingness;
  const ac = d.autocorrelation;
  return (
    <Card aria-labelledby="diag-title">
      <CardHeader
        id="diag-title"
        title="Data diagnostics"
        subtitle={`${d.variable} in ${d.region}${unit ? ` (${unit})` : ""} · computed from the loaded rows`}
      />
      <CardBody className="space-y-5">
        <div className="space-y-5" data-testid="diagnostics">
        <section aria-label="Missingness">
          <h3 className="text-sm font-semibold text-ink">Missingness</h3>
          <p className="mt-1 text-sm text-ink-soft" data-testid="diag-missingness">
            {m.valid_values} valid value(s) of {m.expected_months} expected months ({fmtPct(m.coverage_fraction)}), {fmtDate(m.first_month)} to{" "}
            {fmtDate(m.last_month)}. {m.absent_months.length} month(s) absent, {m.missing_values} present but missing; longest gap{" "}
            {m.longest_gap_months} month(s).
          </p>
          <p className="text-xs text-muted">{m.note}</p>
        </section>

        <section aria-label="Month-of-year summary">
          <h3 className="text-sm font-semibold text-ink">Month-of-year summary {unit ? `(${unit})` : ""}</h3>
          <div className="mt-2 overflow-x-auto rounded-md border border-line">
            <table className="w-full min-w-[560px] text-left text-xs" data-testid="diag-moy">
              <caption className="sr-only">Mean, spread and range of each calendar month across years</caption>
              <thead className="bg-surface-muted text-muted">
                <tr>
                  {["Month", "n", "Mean", "Median", "Std dev", "Min", "Max"].map((h) => (
                    <th key={h} scope="col" className="px-2 py-1.5 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.month_of_year.map((r) => (
                  <tr key={r.month} className="tabular border-t border-line">
                    <th scope="row" className="px-2 py-1 font-medium text-ink">
                      {MONTHS[r.month - 1]}
                    </th>
                    <td className="px-2 py-1">{r.n}</td>
                    <td className="px-2 py-1">{fmtNum(r.mean)}</td>
                    <td className="px-2 py-1">{fmtNum(r.median)}</td>
                    <td className="px-2 py-1">{fmtNum(r.std)}</td>
                    <td className="px-2 py-1">{fmtNum(r.minimum)}</td>
                    <td className="px-2 py-1">{fmtNum(r.maximum)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section aria-label="Autocorrelation">
          <h3 className="text-sm font-semibold text-ink">Autocorrelation</h3>
          {ac.evaluated ? (
            <ul className="mt-1 space-y-1 text-sm text-ink-soft" data-testid="diag-autocorr">
              <AcLine r={ac.detrended} />
              <AcLine r={ac.detrended_and_deseasonalized} />
            </ul>
          ) : (
            <p className="mt-1 text-sm text-ink-soft">Not evaluated: {ac.reason_not_evaluated}</p>
          )}
          <p className="text-xs text-muted">{ac.note}</p>
        </section>

        {d.random_error ? (
          <section aria-label="Random error">
            <h3 className="text-sm font-semibold text-ink">Random-error series (uncertainty-related)</h3>
            {d.random_error.available ? (
              <p className="mt-1 text-sm text-ink-soft" data-testid="diag-random-error">
                Dates {d.random_error.dates_aligned ? "match the value series exactly" : "do NOT fully match the value series"} ({d.random_error.n_aligned}{" "}
                months). Mean random error {fmtNum(d.random_error.mean_random_error)} {d.random_error.unit} against a mean value of{" "}
                {fmtNum(d.random_error.mean_precipitation)} {d.random_error.unit}; mean error-to-value ratio {fmtNum(d.random_error.mean_error_to_value_ratio)}.
              </p>
            ) : (
              <p className="mt-1 text-sm text-ink-soft">Unavailable: {d.random_error.reason_unavailable}</p>
            )}
            <p className="text-xs text-muted">{d.random_error.note}</p>
          </section>
        ) : null}

        <details>
          <summary className="cursor-pointer text-xs font-medium text-ink-soft">Assumptions</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-ink-soft">
            {d.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </details>
        </div>
      </CardBody>
    </Card>
  );
}

function AcLine({ r }: { r: AutocorrelationResult | null }) {
  if (!r) return null;
  if (!r.evaluated) return <li>{r.residual_basis}: not evaluated ({r.reason_not_evaluated}).</li>;
  return (
    <li>
      {r.residual_basis}: lag-1 {fmtNum(r.lag1)}, Durbin–Watson {fmtNum(r.durbin_watson)}, Ljung–Box p {fmtNum(r.ljung_box_p)} ({r.ljung_box_lags} lags)
      {r.flagged ? " — significant autocorrelation" : " — none detected"}
      {r.effective_n_ar1 ? `; effective n ≈ ${Math.round(r.effective_n_ar1)}` : ""}.
    </li>
  );
}
