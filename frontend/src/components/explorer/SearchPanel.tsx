"use client";

import { Search } from "lucide-react";
import { useId } from "react";
import { yearOptions } from "@/lib/explorer/logic";
import type { DatasetInfo } from "@/lib/explorer/types";

// A fixed upper bound: reading the clock during render would make the prerendered page stale.
const MAX_YEAR = 2026;

export const EXAMPLES = ["Bellandur Lake, Bengaluru", "Hussain Sagar, Hyderabad", "Chilika Lake, Odisha", "Amazon Rainforest", "Mumbai"];

interface Props {
  query: string;
  onQuery: (q: string) => void;
  startYear: number;
  endYear: number;
  onStart: (y: number) => void;
  onEnd: (y: number) => void;
  onSubmit: () => void;
  onExample: (q: string) => void;
  busy: boolean;
  compact: boolean;
  datasets: DatasetInfo[] | null;
  datasetsError: boolean;
}

export function SearchPanel(p: Props) {
  const id = useId();
  const years = yearOptions(1980, MAX_YEAR);
  const invalid = p.startYear >= p.endYear;
  return (
    <div className="flex w-[760px] max-w-[94vw] flex-col items-stretch gap-2">
      <form
        className="nx-glass flex flex-wrap items-center gap-2 p-2.5"
        role="search"
        aria-label="Search a place"
        onSubmit={(e) => {
          e.preventDefault();
          if (!invalid && p.query.trim()) p.onSubmit();
        }}
      >
        <label htmlFor={`${id}-q`} className="sr-only">
          Place name
        </label>
        <div className="relative min-w-[200px] flex-[1_1_260px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--nx-muted)]" aria-hidden />
          <input
            id={`${id}-q`}
            className="nx-input w-full pl-9"
            placeholder="Search a lake, city or region…"
            value={p.query}
            maxLength={200}
            autoComplete="off"
            onChange={(e) => p.onQuery(e.target.value)}
          />
        </div>
        <label className="flex items-center gap-1.5 text-[12px] text-[color:var(--nx-muted)]" htmlFor={`${id}-s`}>
          From
          <select id={`${id}-s`} className="nx-input py-2" value={p.startYear} onChange={(e) => p.onStart(Number(e.target.value))}>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-[12px] text-[color:var(--nx-muted)]" htmlFor={`${id}-e`}>
          To
          <select id={`${id}-e`} className="nx-input py-2" value={p.endYear} onChange={(e) => p.onEnd(Number(e.target.value))}>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="nx-btn" disabled={p.busy || invalid || !p.query.trim()}>
          {p.busy ? "Working…" : "Explore"}
        </button>
        {invalid ? (
          <p role="alert" className="basis-full px-1 text-[12px] text-amber-200">
            The start year must be earlier than the end year.
          </p>
        ) : null}
      </form>

      {!p.compact ? (
        <div className="nx-rise flex flex-col items-center gap-2 text-center">
          <p className="text-[12.5px] text-[color:var(--nx-muted)]">Search a place, choose a period, then Explore. Drag to turn the globe, scroll to zoom.</p>
          <div className="flex flex-wrap justify-center gap-2" aria-label="Example locations">
            {EXAMPLES.map((e) => (
              <button key={e} type="button" className="nx-chip" onClick={() => p.onExample(e)} disabled={p.busy}>
                {e}
              </button>
            ))}
          </div>
          <DatasetAvailability datasets={p.datasets} error={p.datasetsError} />
        </div>
      ) : null}
    </div>
  );
}

export function DatasetAvailability({ datasets, error }: { datasets: DatasetInfo[] | null; error: boolean }) {
  if (error) return <p className="text-[12px] text-amber-200" data-testid="availability">Dataset availability could not be loaded. Is the backend running?</p>;
  if (!datasets) return <p className="text-[12px] text-[color:var(--nx-muted)]" data-testid="availability">Checking which datasets are available…</p>;
  if (datasets.length === 0) return <p className="text-[12px] text-amber-200" data-testid="availability">No datasets are loaded, so no location has observations.</p>;
  return (
    <p className="max-w-[720px] text-[12px] leading-relaxed text-[color:var(--nx-muted)]" data-testid="availability">
      <span className="font-semibold text-[color:var(--nx-soft)]">Data available for: </span>
      {datasets.map((d, i) => (
        <span key={d.id}>
          {i > 0 ? " · " : ""}
          {d.name.replace(/ \(.*\)$/, "")} {d.coverage.start.slice(0, 4)}–{d.coverage.end.slice(0, 4)} ({d.temporal_resolution}
          {d.is_synthetic ? ", simulated" : ""})
        </span>
      ))}
      . Other places can be shown on the globe, but have no observations to compare.
    </p>
  );
}
