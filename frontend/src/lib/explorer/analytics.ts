import { request } from "../api";
import type { DatasetInfo } from "./types";

const base = "/api/explorer";

// ------------------------------------------------------------------------------------------ API shapes
export interface StatSeriesPoint {
  date: string;
  area_ha: number;
  share_of_valid_pct: number;
}
export interface StatVariable {
  label: string;
  classes: number;
  primary: boolean;
  series: StatSeriesPoint[];
  first_date?: string;
  last_date?: string;
  net_change_ha?: number | null;
  net_change_pct?: number | null;
}
export interface StatObservation {
  date: string;
  quality: "good" | "fair" | "poor";
  valid_fraction: number;
  footprint_ha: number;
  valid_ha: number;
  nodata_pct: number;
  class_area_ha: Record<string, number>;
}
export interface DatasetStats {
  dataset_id: string;
  name: string;
  designation: string;
  public_label: string | null;
  method: string;
  observations: StatObservation[];
  variables: Record<string, StatVariable>;
}
export interface CatalogueRow {
  id: string;
  name: string;
  designation: string;
  public_label: string | null;
  bbox: [number, number, number, number];
  coverage: { start: string; end: string };
  observations: number;
  temporal_resolution: string;
  resolution_m: number | null;
  variables: string[];
  source: string | null;
  format: string | null;
}
export interface SourceEntry {
  id: string;
  variable: string;
  providing_organization: string;
  official_dataset_url: string;
  dataset_identifier: string;
  original_file_name: string;
  acquisition_or_temporal_coverage: string;
  spatial_resolution: string;
  original_file_format: string;
  license_or_terms: string;
  download_url: string;
  used_by_regions: string[];
}

export interface TrackPoint {
  age_ma: number;
  period: string;
  eb_lat: number | null;
  eb_lon: number | null;
  pm_lat: number | null;
  pm_lon: number | null;
  eb_gap_km: number | null;
  pm_gap_km: number | null;
  models_disagree_km: number | null;
}
export interface DeepAnalytics {
  track: TrackPoint[];
  speed: Record<"earthbyte" | "paleomap", { from_ma: number; to_ma: number; cm_per_year: number }[]>;
  kpis: {
    path_km: Record<"earthbyte" | "paleomap", number>;
    peak_speed: Record<"earthbyte" | "paleomap", { cm_per_year: number; from_ma: number; to_ma: number }>;
    ages: number;
    fossil_records: number;
    birds: number;
    formations: number;
    events: number;
    max_models_disagree_km: number;
  };
  fossils: {
    by_period: { period: string; records: number }[];
    by_age: { from_ma: number; to_ma: number; records: number }[];
    by_group: { group: string; records: number }[];
    by_state: { state: string; records: number }[];
    top_taxa: { taxon: string; records: number }[];
  };
  formations: { by_period: { period: string; formations: number }[] };
  places: { id: string; name: string; series: { age_ma: number; class: string | null }[] }[];
  events: { event_id: string; event_name: string; start_age_ma: number; end_age_ma: number; confidence: string; evidence_source: string; kind: string; uncertainty_notes: string; description: string }[];
  note: string;
}
export interface DeepSource {
  dataset_id: string;
  original_filename: string;
  provider: string;
  model_name: string;
  source_url: string;
  original_format: string;
  license: string;
  downloaded_date: string;
  checksum: string;
  processing_method: string;
}

export interface RankingRow {
  id: string;
  place: string;
  kind: string;
  variable: string;
  states: string[];
  first_date: string;
  last_date: string;
  first_ha: number;
  last_ha: number;
  net_ha: number;
  pct: number | null;
  ha_per_year: number;
  lat: number | null;
  lon: number | null;
  source: string | null;
}

export const analyticsApi = {
  rankings: (signal?: AbortSignal) => request<{ rows: RankingRow[]; count: number }>(`${base}/rankings`, { signal, timeoutMs: 30_000 }),
  catalogue: (signal?: AbortSignal) => request<{ datasets: CatalogueRow[]; count: number }>(`${base}/catalogue`, { signal }),
  stats: (id: string, signal?: AbortSignal) => request<DatasetStats>(`${base}/datasets/${id}/statistics`, { signal }),
  registry: (signal?: AbortSignal) => request<{ entries: SourceEntry[] }>(`${base}/source-registry`, { signal }),
  deep: (signal?: AbortSignal) => request<DeepAnalytics>(`${base}/deeptime/analytics`, { signal, timeoutMs: 20_000 }),
  deepSources: (signal?: AbortSignal) => request<DeepSource[]>(`${base}/deeptime/sources`, { signal }),
};

// ------------------------------------------------------------------------------------------ statistics
/** Decimal year of an ISO date (2012-07-01 is about 2012.5). */
export function decimalYear(iso: string): number {
  const y = Number(iso.slice(0, 4));
  const m = Number(iso.slice(5, 7)) || 1;
  return y + (m - 1) / 12;
}

export interface Fit {
  n: number;
  slope: number; // units per year (ordinary least squares)
  intercept: number;
  r2: number;
  theilSen: number | null; // robust slope; needs three or more points
}

/** Ordinary least squares and the Theil-Sen median slope. Fewer than two points give no fit. */
export function fitTrend(points: { x: number; y: number }[]): Fit | null {
  const n = points.length;
  if (n < 2) return null;
  const mx = points.reduce((a, p) => a + p.x, 0) / n;
  const my = points.reduce((a, p) => a + p.y, 0) / n;
  let sxx = 0;
  let sxy = 0;
  let syy = 0;
  for (const p of points) {
    sxx += (p.x - mx) ** 2;
    sxy += (p.x - mx) * (p.y - my);
    syy += (p.y - my) ** 2;
  }
  if (sxx === 0) return null;
  const slope = sxy / sxx;
  const slopes: number[] = [];
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) if (points[j].x !== points[i].x) slopes.push((points[j].y - points[i].y) / (points[j].x - points[i].x));
  slopes.sort((a, b) => a - b);
  const mid = slopes.length >> 1;
  const ts = n >= 3 && slopes.length ? (slopes.length % 2 ? slopes[mid] : (slopes[mid - 1] + slopes[mid]) / 2) : null;
  return { n, slope, intercept: my - slope * mx, r2: syy === 0 ? 1 : (sxy * sxy) / (sxx * syy), theilSen: ts };
}

export interface ChangeMetrics {
  first: StatSeriesPoint;
  last: StatSeriesPoint;
  years: number;
  netHa: number;
  netPct: number | null;
  haPerYear: number | null;
  /** Compound annual growth of the area, in percent per year. Null if the first value is zero or the span is zero. */
  cagrPct: number | null;
  shareChangePts: number;
  fit: Fit | null;
}

/** Headline metrics for one variable's series. Null when there are fewer than two observations (a single snapshot has no change). */
export function changeMetrics(series: StatSeriesPoint[]): ChangeMetrics | null {
  if (series.length < 2) return null;
  const s = [...series].sort((a, b) => a.date.localeCompare(b.date));
  const first = s[0];
  const last = s[s.length - 1];
  const years = decimalYear(last.date) - decimalYear(first.date);
  const netHa = last.area_ha - first.area_ha;
  return {
    first,
    last,
    years,
    netHa,
    netPct: first.area_ha > 0 ? (netHa / first.area_ha) * 100 : null,
    haPerYear: years > 0 ? netHa / years : null,
    cagrPct: first.area_ha > 0 && last.area_ha > 0 && years > 0 ? ((last.area_ha / first.area_ha) ** (1 / years) - 1) * 100 : null,
    shareChangePts: last.share_of_valid_pct - first.share_of_valid_pct,
    fit: fitTrend(s.map((p) => ({ x: decimalYear(p.date), y: p.area_ha }))),
  };
}

/** Each variable scaled so its first observation is 100, to compare variables of different size. */
export function indexSeries(vars: Record<string, StatVariable>): { rows: Record<string, number>[]; keys: string[] } {
  const keys = Object.keys(vars).filter((k) => vars[k].series.length >= 2 && vars[k].series[0].area_ha > 0);
  const dates = [...new Set(keys.flatMap((k) => vars[k].series.map((p) => p.date)))].sort();
  const rows = dates.map((d) => {
    const row: Record<string, number> = { year: Number(decimalYear(d).toFixed(2)) };
    for (const k of keys) {
      const sorted = [...vars[k].series].sort((a, b) => a.date.localeCompare(b.date));
      const p = sorted.find((x) => x.date === d);
      if (p) row[k] = Number(((p.area_ha / sorted[0].area_ha) * 100).toFixed(2));
    }
    return row;
  });
  return { rows, keys };
}

/** The primary variable of a dataset, or its first one. */
export function primaryVariable(stats: DatasetStats): [string, StatVariable] | null {
  const e = Object.entries(stats.variables);
  return e.find(([, v]) => v.primary) ?? e[0] ?? null;
}

export const isOfficial = (d: Pick<DatasetInfo, "designation"> | { designation: string }) => d.designation !== "illustrative";

export function shortClass(name: string): string {
  const n = name.replace(/\s*\(.*\)\s*$/, "").trim();
  return n.length > 28 ? `${n.slice(0, 26)}…` : n;
}

// ------------------------------------------------------------------------------------------ number formats
export const fmtNum = (v: number | null | undefined, d = 0) => (v == null || Number.isNaN(v) ? "n/a" : v.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
export const fmtSigned = (v: number | null | undefined, d = 1, unit = "") => (v == null || Number.isNaN(v) ? "n/a" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d })}${unit}`);
