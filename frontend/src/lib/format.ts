import type { Direction, DatasetStatus, PrimaryStatus, TrendLabel } from "./types";

export function fmtNum(x: number | null | undefined, digits = 4): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "n/a";
  if (x === 0) return "0";
  const abs = Math.abs(x);
  if (abs >= 1e6 || abs < 1e-4) return x.toExponential(Math.max(1, digits - 1));
  return Number(x.toPrecision(digits)).toString();
}

export function fmtSigned(x: number | null | undefined, digits = 4): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "n/a";
  const s = fmtNum(x, digits);
  return x > 0 ? `+${s}` : s;
}

export function fmtP(p: number | null | undefined): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "n/a";
  if (p < 0.001) return "< 0.001";
  return p.toFixed(3);
}

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "n/a";
  return n.toLocaleString("en-US");
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  return iso.slice(0, 10);
}

export function fmtPct(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "n/a";
  return `${(x * 100).toFixed(digits)}%`;
}

export function fmtRange(a: string | null | undefined, b: string | null | undefined): string {
  return `${fmtDate(a)} to ${fmtDate(b)}`;
}

export const DIRECTION_LABEL: Record<Direction, string> = {
  increasing: "Increasing",
  decreasing: "Decreasing",
  flat: "Flat",
  unknown: "Undetermined",
};

export const TREND_LABEL: Record<TrendLabel, string> = {
  increasing: "Increasing trend",
  decreasing: "Decreasing trend",
  no_clear_trend: "No clear monotonic trend",
  insufficient_data: "Insufficient data",
};

export const DATASET_STATUS_LABEL: Record<DatasetStatus, string> = {
  synthetic_demo: "Synthetic demo data",
  uploaded: "Uploaded dataset",
  nasa_verified: "NASA dataset (verified)",
  observed_global: "Observed global data",
  synthetic_regional_demo: "SYNTHETIC DEMO — NOT NASA OBSERVATIONS",
};

/** Short label for the data behind a chart or export; synthetic data is never described as anything else. */
export function sourceLabelFor(p: { is_synthetic: boolean; status: DatasetStatus }): string {
  if (p.status === "synthetic_regional_demo") return "SYNTHETIC DEMO — NOT NASA OBSERVATIONS";
  if (p.is_synthetic) return "Synthetic demo data";
  if (p.status === "observed_global") return "Observed global data (area average, not regional)";
  if (p.status === "uploaded") return "Uploaded dataset (unverified)";
  return "NASA dataset";
}

export const PRIMARY_STATUS_LABEL: Record<PrimaryStatus, string> = {
  standard: "Standard test",
  autocorrelation_corrected: "Autocorrelation-corrected",
  exploratory_uncorrected: "Exploratory (uncorrected)",
  insufficient_data: "Insufficient data",
};

export const PRIMARY_STATUS_HELP: Record<PrimaryStatus, string> = {
  standard: "No significant autocorrelation was found in the residuals, so the standard test is used.",
  autocorrelation_corrected:
    "Significant autocorrelation was found; a corrected test (Hamed & Rao 1998) is the headline result.",
  exploratory_uncorrected: "The p-value has not been corrected for autocorrelation, so it may be too small. Treat as exploratory.",
  insufficient_data: "Too few valid observations for a trend test.",
};

export function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/**
 * Help text for the headline status. For "exploratory_uncorrected" it separates two different facts:
 * whether autocorrelation was ASSESSED (diagnostics ran) and whether it could be CORRECTED (Hamed-Rao applied).
 */
export function primaryStatusHelp(
  status: PrimaryStatus,
  ctx?: {
    autocorrelation: { evaluated: boolean; flagged: boolean | null; lag1: number | null; reason_not_evaluated: string | null };
    primary: { test_name: string | null };
  },
): string {
  if (status !== "exploratory_uncorrected" || !ctx) return PRIMARY_STATUS_HELP[status];
  const ac = ctx.autocorrelation;
  if (!ac.evaluated) {
    return `Autocorrelation could not be assessed${ac.reason_not_evaluated ? ` (${ac.reason_not_evaluated})` : ""}, so the p-value is uncorrected and may be too small. Treat as exploratory.`;
  }
  const lag = ac.lag1 === null ? "" : ` (lag-1 ${ac.lag1.toFixed(2)})`;
  if (!ac.flagged) {
    return `Autocorrelation was assessed${lag} and no significant autocorrelation was found, but this result is still labelled exploratory.`;
  }
  const seasonal = (ctx.primary.test_name ?? "").toLowerCase().startsWith("seasonal");
  return seasonal
    ? `Autocorrelation was assessed and is significant${lag}. It was not corrected: the Hamed–Rao correction is not available for the seasonal analysis path, so the p-value is likely too small. Treat as exploratory.`
    : `Autocorrelation was assessed and is significant${lag}. It was not corrected: no valid correction was available for this series, so the p-value is likely too small. Treat as exploratory.`;
}
