"use client";

import { FlaskConical, Globe2 } from "lucide-react";
import type { DatasetInfo } from "@/lib/types";
import { cx } from "@/components/ui/primitives";

/**
 * Source, spatial scope, temporal coverage, unit, data class and limitations of a packaged dataset.
 * Shown wherever such a dataset is selected, so none of it can be missed or removed by a view.
 */
export function DatasetInfoCard({ info }: { info: DatasetInfo | null | undefined }) {
  if (!info) return null;
  const synthetic = info.data_class === "synthetic_regional_demo";
  const warnings = info.checks.filter((c) => c.severity !== "info");
  return (
    <section
      aria-label="About the selected dataset"
      data-testid="dataset-info"
      data-data-class={info.data_class}
      className={cx(
        "rounded-lg border p-4 text-sm",
        synthetic ? "border-warn-line bg-warn-soft" : "border-line bg-surface-muted",
      )}
    >
      <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
        {synthetic ? <FlaskConical aria-hidden="true" size={16} /> : <Globe2 aria-hidden="true" size={16} />}
        {synthetic ? "Synthetic regional demo data" : "Observed global data"}
        <span className="rounded border border-current px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide">
          {synthetic ? info.label : "Observed · global"}
        </span>
      </h2>
      <dl className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
        <Item label="Data source" value={info.data_source} />
        <Item label="Spatial scope" value={info.spatial_scope} />
        <Item label="Temporal coverage" value={info.temporal_coverage} />
        <Item label="Unit" value={info.unit} hint={info.unit_note} />
        <Item label="Data class" value={synthetic ? "Synthetic demo (not observations)" : "Observed (NASA GPM IMERG V07, global average)"} />
        <Item label="Source files" value={info.source_files.join(", ")} />
      </dl>
      <details className="mt-3">
        <summary className="cursor-pointer text-xs font-medium text-ink-soft">Limitations ({info.limitations.length})</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-ink-soft">
          {info.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </details>
      {warnings.length ? (
        <ul className="mt-3 space-y-1 text-xs text-ink-soft" aria-label="Validation notes">
          {warnings.map((c) => (
            <li key={`${c.code}-${c.message}`}>
              <strong>{c.severity === "error" ? "Problem" : "Note"}:</strong> {c.message}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function Item({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-muted">{label}</dt>
      <dd className="break-words text-ink">
        {value}
        {hint ? <span className="mt-0.5 block text-xs text-muted">{hint}</span> : null}
      </dd>
    </div>
  );
}
