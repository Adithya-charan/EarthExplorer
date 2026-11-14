"use client";

import type { ColumnMapping, DuplicatePolicy, MappingDefaults } from "@/lib/types";
import { SelectField, type Option } from "@/components/filters/Fields";

const NONE = "";

const TEXT_INPUT =
  "w-full rounded-md border border-line-strong bg-surface px-2.5 py-2 text-sm text-ink disabled:bg-surface-muted";

type SourceKey = "date" | "region" | "variable" | "value" | "unit" | "data_source";
type DefaultKey = "region" | "variable" | "unit" | "data_source";

export function ColumnMapper({
  columns,
  mapping,
  onChange,
  notes,
}: {
  columns: string[];
  mapping: ColumnMapping;
  onChange: (next: ColumnMapping) => void;
  notes?: string[];
}) {
  const options: Option[] = [{ value: NONE, label: "Not mapped" }, ...columns.map((c) => ({ value: c, label: c }))];
  const setCol = (key: SourceKey | "is_synthetic", v: string) => onChange({ ...mapping, [key]: v === NONE ? null : v });
  const setDefault = <K extends keyof MappingDefaults>(key: K, v: MappingDefaults[K]) =>
    onChange({ ...mapping, defaults: { ...mapping.defaults, [key]: v } });

  const field = (key: SourceKey, label: string, opts?: { defaultKey?: DefaultKey; required?: boolean; hint?: string }) => {
    const mapped = Boolean(mapping[key]);
    return (
      <div key={key} className="space-y-2 rounded-md border border-line p-3">
        <SelectField
          id={`map-${key}`}
          label={`${label}${opts?.required ? " (required)" : ""}`}
          value={mapping[key] ?? NONE}
          options={options}
          onChange={(v) => setCol(key, v)}
          hint={opts?.hint}
        />
        {opts?.defaultKey && !mapped ? (
          <div>
            <label htmlFor={`default-${key}`} className="mb-1 block text-xs font-medium text-ink-soft">
              Or declare one {label.toLowerCase()} for the whole file
            </label>
            <input
              id={`default-${key}`}
              type="text"
              className={TEXT_INPUT}
              value={mapping.defaults[opts.defaultKey] ?? ""}
              maxLength={opts.defaultKey === "unit" ? 100 : 200}
              onChange={(e) => setDefault(opts.defaultKey!, e.target.value || null)}
              placeholder={opts.defaultKey === "unit" ? "e.g. the unit stated by the data provider" : undefined}
            />
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {notes && notes.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted" aria-label="Notes on the suggested mapping">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}

      <div className="grid gap-3 md:grid-cols-2">
        {field("date", "Date", { required: true, hint: "A column of dates or timestamps." })}
        {field("value", "Value", { required: true, hint: "The numeric measurement." })}
        {field("variable", "Variable", { defaultKey: "variable", required: true })}
        {field("region", "Region", { defaultKey: "region", required: true })}
        {field("unit", "Unit", {
          defaultKey: "unit",
          required: true,
          hint: "Units are never guessed. Map a column or type the unit you know to be correct.",
        })}
        {field("data_source", "Data source", { defaultKey: "data_source", required: true })}

        <div className="space-y-2 rounded-md border border-line p-3">
          <SelectField
            id="map-is_synthetic"
            label="Synthetic flag column"
            value={mapping.is_synthetic ?? NONE}
            options={options}
            onChange={(v) => setCol("is_synthetic", v)}
            hint="Optional. A true/false column marking synthetic rows."
          />
          {!mapping.is_synthetic ? (
            <fieldset className="space-y-1.5">
              <legend className="text-xs font-medium text-ink-soft">
                Are these data synthetic or test data? (required)
              </legend>
              <label className="flex cursor-pointer items-start gap-2 text-sm text-ink-soft">
                <input
                  type="radio"
                  name="synthetic-declaration"
                  className="mt-0.5 h-4 w-4 accent-[#0f766e]"
                  checked={mapping.defaults.is_synthetic === true}
                  onChange={() => setDefault("is_synthetic", true)}
                />
                <span>Yes, synthetic or test data (labelled as such everywhere)</span>
              </label>
              <label className="flex cursor-pointer items-start gap-2 text-sm text-ink-soft">
                <input
                  type="radio"
                  name="synthetic-declaration"
                  className="mt-0.5 h-4 w-4 accent-[#0f766e]"
                  checked={mapping.defaults.is_synthetic === false}
                  onChange={() => setDefault("is_synthetic", false)}
                />
                <span>No, measured or externally sourced data (provenance is not verified here)</span>
              </label>
            </fieldset>
          ) : null}
        </div>

        <div className="space-y-3 rounded-md border border-line p-3">
          <div>
            <label htmlFor="date-format" className="mb-1 block text-xs font-medium text-ink-soft">
              Date format (optional)
            </label>
            <input
              id="date-format"
              type="text"
              className={TEXT_INPUT}
              value={mapping.date_format ?? ""}
              maxLength={60}
              onChange={(e) => onChange({ ...mapping, date_format: e.target.value || null })}
              placeholder="e.g. %d/%m/%Y"
              aria-describedby="date-format-hint"
            />
            <p id="date-format-hint" className="mt-1 text-xs text-muted">
              Leave blank for ISO dates (YYYY-MM-DD). Set this if day/month order is ambiguous.
            </p>
          </div>
          <SelectField
            id="dup-policy"
            label="Duplicate rows (same date, region, variable)"
            value={mapping.duplicate_policy}
            options={[
              { value: "error", label: "Report conflicting duplicates as an error" },
              { value: "mean", label: "Average them" },
              { value: "first", label: "Keep the first" },
              { value: "last", label: "Keep the last" },
            ]}
            onChange={(v) => onChange({ ...mapping, duplicate_policy: v as DuplicatePolicy })}
          />
        </div>
      </div>
    </div>
  );
}
