import type { AnalyzeResponse, CompareResponse } from "./types";

/** Neutralise spreadsheet formula injection in text cells, then quote when needed. */
export function csvCell(value: string | number | boolean | null | undefined, isText = false): string {
  if (value === null || value === undefined) return "";
  let s = String(value);
  if (isText && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

const row = (cells: (string | number | boolean | null | undefined)[], textCols: number[] = []) =>
  cells.map((c, i) => csvCell(c, textCols.includes(i))).join(",");

function header(prov: AnalyzeResponse["provenance"], title: string): string[] {
  const lines = [
    `# EarthTrend Explorer export: ${title}`,
    `# dataset: ${csvCell(prov.dataset_name, true)} | status: ${prov.status} | is_synthetic: ${prov.is_synthetic}${prov.dataset_checksum ? ` | dataset_sha256: ${prov.dataset_checksum}` : ""}${prov.generated_at ? ` | generated_at: ${prov.generated_at}` : ""}`,
    `# data_source: ${prov.data_sources.map((s) => csvCell(s, true)).join("; ")}`,
  ];
  if (prov.notice) lines.push(`# ${prov.notice}`);
  return lines;
}

/** Export one analysis: provenance header, headline statistics, then the series with fitted values. */
export function analysisToCsv(a: AnalyzeResponse): string {
  const p = a.primary;
  const lines = [
    ...header(a.provenance, `trend analysis of ${a.request.variable} in ${a.request.region}`),
    `# primary_test: ${csvCell(p.test_name ?? "n/a", true)} | status: ${p.status}`,
    `# trend: ${p.trend} | slope_per_year: ${p.slope_per_year ?? ""} ${csvCell(p.slope_unit, true)} | ci: ${p.slope_ci_low ?? ""} to ${p.slope_ci_high ?? ""} | p_value: ${p.p_value ?? ""} | alpha: ${p.alpha} | n_valid: ${a.coverage.n_valid}`,
    `# aggregation: ${a.aggregation.method} | seasonality_method: ${a.seasonality.method_used}`,
    row(["date", "region", "variable", "value", "unit", "fitted_ols", "fitted_sen", "deseasonalized_descriptive", "data_source", "is_synthetic"]),
  ];
  const source = a.provenance.data_sources.join("; ");
  for (const pt of a.points) {
    lines.push(
      row(
        [pt.date, a.request.region, a.request.variable, pt.value, a.unit, pt.fitted_ols, pt.fitted_sen, pt.deseasonalized, source, a.provenance.is_synthetic],
        [1, 2, 4, 8],
      ),
    );
  }
  return lines.join("\n") + "\n";
}

export function comparisonToCsv(c: CompareResponse): string {
  const lines = [
    ...header(c.provenance, `regional comparison of ${c.request.variable}`),
    `# comparable: ${c.comparable} | multiple_testing: ${csvCell(c.multiple_testing_method, true)} | tests: ${c.n_tests}`,
    row([
      "region",
      "unit",
      "estimated_direction",
      "trend",
      "slope_per_year",
      "ci_low",
      "ci_high",
      "test",
      "status",
      "p_value",
      "p_value_bh_adjusted",
      "n_valid",
      "first_date",
      "last_date",
      "sampling",
      "data_source",
      "is_synthetic",
    ]),
  ];
  const source = c.provenance.data_sources.join("; ");
  for (const r of c.rows) {
    lines.push(
      row(
        [
          r.region,
          r.unit,
          r.estimated_direction,
          r.trend,
          r.slope_per_year,
          r.slope_ci_low,
          r.slope_ci_high,
          r.test_name,
          r.status,
          r.p_value,
          r.p_value_adjusted_bh,
          r.n_valid,
          r.first_date,
          r.last_date,
          r.sampling,
          source,
          c.provenance.is_synthetic,
        ],
        [0, 1, 7, 15],
      ),
    );
  }
  return lines.join("\n") + "\n";
}

export function downloadText(filename: string, text: string, mime = "text/csv;charset=utf-8"): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function safeFilePart(s: string): string {
  // Strip leading/trailing dots and separators so a name can never start with ".." or become a hidden file.
  return s.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[._-]+|[._-]+$/g, "").slice(0, 60) || "export";
}
