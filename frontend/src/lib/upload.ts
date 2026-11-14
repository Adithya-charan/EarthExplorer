import type { ColumnMapping } from "./types";

/** Mirrors the backend default (EARTHTREND_MAX_UPLOAD_MB). The server is still the authority. */
export const MAX_UPLOAD_MB = 25;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

/** Client-side pre-checks so obvious mistakes get instant feedback. Returns a message, or null if acceptable. */
export function validateUploadFile(file: { name: string; size: number }): string | null {
  if (!/\.csv$/i.test(file.name)) {
    const ext = file.name.includes(".") ? `.${file.name.split(".").pop()}` : "no extension";
    return `Only .csv files are supported (this file has ${ext}). NetCDF, HDF and other formats are not supported yet.`;
  }
  if (file.size === 0) return "This file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) {
    return `This file is ${(file.size / 1024 / 1024).toFixed(1)} MB, which is over the ${MAX_UPLOAD_MB} MB limit.`;
  }
  return null;
}

export const EMPTY_MAPPING: ColumnMapping = {
  date: null,
  region: null,
  variable: null,
  value: null,
  unit: null,
  data_source: null,
  is_synthetic: null,
  optional: {},
  defaults: {},
  date_format: null,
  duplicate_policy: "error",
};

/** Required canonical fields that still have neither a source column nor a declared constant. */
export function missingRequired(m: ColumnMapping): string[] {
  const d = m.defaults;
  const missing: string[] = [];
  if (!m.date) missing.push("date");
  if (!m.value) missing.push("value");
  if (!m.region && !d.region) missing.push("region");
  if (!m.variable && !d.variable) missing.push("variable");
  if (!m.unit && !d.unit) missing.push("unit");
  if (!m.data_source && !d.data_source) missing.push("data source");
  // Provenance is never guessed: either a flag column or an explicit yes/no declaration is required.
  if (!m.is_synthetic && (d.is_synthetic === null || d.is_synthetic === undefined)) missing.push("synthetic or real declaration");
  return missing;
}
