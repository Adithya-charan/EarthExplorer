import { AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import type { QualityReport } from "@/lib/types";
import { fmtDate, fmtInt } from "@/lib/format";
import { Badge, Callout } from "@/components/ui/primitives";

const SEVERITY = {
  error: { label: "Error", tone: "danger" as const, icon: <AlertCircle aria-hidden="true" size={15} /> },
  warning: { label: "Warning", tone: "warn" as const, icon: <AlertTriangle aria-hidden="true" size={15} /> },
  info: { label: "Note", tone: "info" as const, icon: <Info aria-hidden="true" size={15} /> },
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="tabular text-lg font-semibold text-ink">{value}</dd>
    </div>
  );
}

/** Data quality report from a dry run or import. Severity is shown with text and icon, never colour alone. */
export function QualityReportView({ report }: { report: QualityReport }) {
  return (
    <div className="space-y-4" data-testid="quality-report">
      {report.can_import ? (
        <Callout tone="accent" role="status" icon={<CheckCircle2 size={18} />} title="This file can be imported">
          {report.requires_confirmation
            ? "Some mapping choices are ambiguous. Read them below and confirm before importing."
            : "No blocking problems were found with this mapping."}
        </Callout>
      ) : (
        <Callout tone="danger" role="alert" icon={<AlertCircle size={18} />} title="This file cannot be imported yet">
          Fix the errors below (usually by changing the column mapping) and validate again.
        </Callout>
      )}

      <dl className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label="Source rows" value={fmtInt(report.n_source_rows)} />
        <Stat label="Rows kept" value={fmtInt(report.n_rows_retained)} />
        <Stat label="Rows dropped" value={fmtInt(report.n_rows_dropped)} />
        <Stat label="Missing values" value={fmtInt(report.n_missing_values)} />
        <Stat label="Invalid dates" value={fmtInt(report.n_invalid_dates)} />
        <Stat label="Invalid values" value={fmtInt(report.n_invalid_values)} />
        <Stat label="Conflicting duplicates" value={fmtInt(report.n_duplicate_conflicting)} />
        <Stat label="Series found" value={fmtInt(report.n_series)} />
      </dl>

      <div className="grid gap-3 text-sm md:grid-cols-3">
        <div>
          <p className="text-xs font-medium text-muted">Variables ({report.variables.length})</p>
          <p className="text-ink-soft">{report.variables.join(", ") || "none"}</p>
        </div>
        <div>
          <p className="text-xs font-medium text-muted">Regions ({report.regions.length})</p>
          <p className="text-ink-soft">{report.regions.join(", ") || "none"}</p>
        </div>
        <div>
          <p className="text-xs font-medium text-muted">Date range</p>
          <p className="tabular text-ink-soft">
            {fmtDate(report.date_min)} to {fmtDate(report.date_max)}
          </p>
        </div>
      </div>

      {Object.keys(report.units_by_variable).length > 0 ? (
        <div className="text-sm">
          <p className="text-xs font-medium text-muted">Units by variable (as supplied, never converted)</p>
          <ul className="mt-1 space-y-0.5 text-ink-soft">
            {Object.entries(report.units_by_variable).map(([v, units]) => (
              <li key={v}>
                {v}: {units.length ? units.join(", ") : "no unit"}
                {units.length > 1 ? (
                  <Badge tone="warn" className="ml-2">
                    mixed units
                  </Badge>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.ambiguities.length > 0 ? (
        <Callout tone="warn" role="note" icon={<AlertTriangle size={18} />} title="Ambiguities to confirm">
          <ul className="list-disc space-y-1 pl-5">
            {report.ambiguities.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </Callout>
      ) : null}

      {report.issues.length > 0 ? (
        <div>
          <h3 className="text-sm font-semibold text-ink">Issues ({report.issues.length})</h3>
          <ul className="mt-2 space-y-2">
            {report.issues.map((issue) => {
              const s = SEVERITY[issue.severity];
              return (
                <li key={issue.code + issue.message} className="rounded-md border border-line bg-surface px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={s.tone}>
                      {s.icon}
                      {s.label}
                    </Badge>
                    <span className="text-ink">{issue.message}</span>
                    {issue.count !== null ? <span className="tabular text-xs text-muted">({fmtInt(issue.count)})</span> : null}
                  </div>
                  {issue.examples.length > 0 ? (
                    <p className="mt-1 text-xs text-muted">Examples: {issue.examples.slice(0, 5).join("; ")}</p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
