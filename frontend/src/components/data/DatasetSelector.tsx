"use client";

import { Database } from "lucide-react";
import { useDatasets } from "@/context/DatasetContext";
import { DATASET_STATUS_LABEL } from "@/lib/format";
import type { DatasetSummary } from "@/lib/types";

// Observed data, synthetic data and uploads are separate groups so they can never be mistaken for one another.
const GROUPS: { label: string; statuses: DatasetSummary["status"][] }[] = [
  { label: "Observed global data", statuses: ["observed_global", "nasa_verified"] },
  { label: "Synthetic regional demo data — NOT NASA OBSERVATIONS", statuses: ["synthetic_regional_demo"] },
  { label: "Bundled synthetic demo data", statuses: ["synthetic_demo"] },
  { label: "Uploaded datasets (unverified)", statuses: ["uploaded"] },
];

export function DatasetSelector({ id = "dataset-select" }: { id?: string }) {
  const { list, selectedId, select } = useDatasets();
  const datasets = list?.datasets ?? [];
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="flex items-center gap-1.5 text-xs font-medium text-muted">
        <Database aria-hidden="true" size={14} />
        <span className="sr-only sm:not-sr-only">Dataset</span>
      </label>
      <select
        id={id}
        value={selectedId ?? ""}
        onChange={(e) => select(e.target.value)}
        disabled={datasets.length === 0}
        className="max-w-[16rem] truncate rounded-md border border-line-strong bg-surface px-2 py-1.5 text-sm text-ink disabled:text-muted"
      >
        {datasets.length === 0 ? <option value="">No dataset available</option> : null}
        {GROUPS.map((g) => {
          const items = datasets.filter((d) => g.statuses.includes(d.status));
          if (items.length === 0) return null;
          return (
            <optgroup key={g.label} label={g.label}>
              {items.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.status === "observed_global" || d.status === "synthetic_regional_demo"
                    ? d.name // the name already states the data class
                    : `${d.name} (${DATASET_STATUS_LABEL[d.status]})`}
                </option>
              ))}
            </optgroup>
          );
        })}
      </select>
    </div>
  );
}
