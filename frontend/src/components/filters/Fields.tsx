"use client";

import type { Aggregation, SeasonalityMode } from "@/lib/types";

const CONTROL =
  "w-full rounded-md border border-line-strong bg-surface px-2.5 py-2 text-sm text-ink disabled:bg-surface-muted disabled:text-muted";

export interface Option {
  value: string;
  label: string;
}

export function SelectField({
  id,
  label,
  value,
  options,
  onChange,
  disabled,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  options: Option[];
  onChange: (v: string) => void;
  disabled?: boolean;
  hint?: string;
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-ink-soft">
        {label}
      </label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={CONTROL}
        aria-describedby={hint ? `${id}-hint` : undefined}
      >
        {options.length === 0 ? <option value="">None available</option> : null}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {hint ? (
        <p id={`${id}-hint`} className="mt-1 text-xs text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function DateRangeFilter({
  start,
  end,
  min,
  max,
  onChange,
}: {
  start: string;
  end: string;
  min?: string | null;
  max?: string | null;
  onChange: (next: { start: string; end: string }) => void;
}) {
  const invalid = Boolean(start && end && start > end);
  return (
    <fieldset className="min-w-0">
      <legend className="mb-1 text-xs font-medium text-ink-soft">Date range</legend>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label htmlFor="date-start" className="sr-only">
            Start date
          </label>
          <input
            id="date-start"
            type="date"
            value={start}
            min={min?.slice(0, 10)}
            max={max?.slice(0, 10)}
            onChange={(e) => onChange({ start: e.target.value, end })}
            className={CONTROL}
            aria-invalid={invalid}
            aria-describedby={invalid ? "date-error" : undefined}
          />
        </div>
        <div>
          <label htmlFor="date-end" className="sr-only">
            End date
          </label>
          <input
            id="date-end"
            type="date"
            value={end}
            min={min?.slice(0, 10)}
            max={max?.slice(0, 10)}
            onChange={(e) => onChange({ start, end: e.target.value })}
            className={CONTROL}
            aria-invalid={invalid}
            aria-describedby={invalid ? "date-error" : undefined}
          />
        </div>
      </div>
      {invalid ? (
        <p id="date-error" role="alert" className="mt-1 text-xs text-danger">
          The start date must be on or before the end date.
        </p>
      ) : (
        <p className="mt-1 text-xs text-muted">Leave blank to use the full record.</p>
      )}
    </fieldset>
  );
}

export const AGGREGATION_OPTIONS: Option[] = [
  { value: "none", label: "None (native resolution)" },
  { value: "quarterly", label: "Quarterly mean" },
  { value: "annual", label: "Annual mean" },
];

export const SEASONALITY_OPTIONS: Option[] = [
  { value: "auto", label: "Automatic (detect)" },
  { value: "seasonal", label: "Treat as seasonal" },
  { value: "none", label: "Ignore seasonality" },
];

export const ALPHA_OPTIONS: Option[] = [
  { value: "0.01", label: "0.01 (99% confidence)" },
  { value: "0.05", label: "0.05 (95% confidence)" },
  { value: "0.1", label: "0.10 (90% confidence)" },
];

export interface AnalysisOptionsValue {
  aggregation: Aggregation;
  seasonality: SeasonalityMode;
  alpha: number;
}

export function AnalysisOptions({
  value,
  onChange,
  idPrefix = "opt",
}: {
  value: AnalysisOptionsValue;
  onChange: (next: AnalysisOptionsValue) => void;
  idPrefix?: string;
}) {
  return (
    <>
      <SelectField
        id={`${idPrefix}-aggregation`}
        label="Aggregation"
        value={value.aggregation}
        options={AGGREGATION_OPTIONS}
        onChange={(v) => onChange({ ...value, aggregation: v as Aggregation })}
        hint="Periods with under 75% coverage are dropped, never filled."
      />
      <SelectField
        id={`${idPrefix}-seasonality`}
        label="Seasonality"
        value={value.seasonality}
        options={SEASONALITY_OPTIONS}
        onChange={(v) => onChange({ ...value, seasonality: v as SeasonalityMode })}
      />
      <SelectField
        id={`${idPrefix}-alpha`}
        label="Significance level (α)"
        value={String(value.alpha)}
        options={ALPHA_OPTIONS}
        onChange={(v) => onChange({ ...value, alpha: Number(v) })}
      />
    </>
  );
}

export function RegionChecklist({
  regions,
  selected,
  onChange,
  max = 8,
}: {
  regions: string[];
  selected: string[];
  onChange: (next: string[]) => void;
  max?: number;
}) {
  return (
    <fieldset className="min-w-0">
      <legend className="mb-1 text-xs font-medium text-ink-soft">
        Regions <span className="font-normal text-muted">(select 2 to {max})</span>
      </legend>
      <div className="flex flex-wrap gap-2">
        {regions.map((r) => {
          const checked = selected.includes(r);
          const atMax = !checked && selected.length >= max;
          return (
            <label
              key={r}
              className={`inline-flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm ${
                checked ? "border-accent bg-accent-soft text-accent-strong" : "border-line-strong bg-surface text-ink-soft"
              } ${atMax ? "cursor-not-allowed opacity-50" : ""}`}
            >
              <input
                type="checkbox"
                className="h-4 w-4 accent-[#0f766e]"
                checked={checked}
                disabled={atMax}
                onChange={() => onChange(checked ? selected.filter((s) => s !== r) : [...selected, r])}
              />
              {r}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
