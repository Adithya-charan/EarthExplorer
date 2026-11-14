import type { GeoInfo, GridFrame, MonthPoint } from "./types";

export const WET = "#0072B2"; // above the usual (blue)
export const DRY = "#D55E00"; // below the usual (vermillion)
export const NEUTRAL = "#8a97a6";
const MAX_HEIGHT_M = 700_000;

function hex(h: string): [number, number, number] {
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}

/** Diverging colour for an anomaly, scaled by the largest absolute anomaly in view. Falls back to neutral grey. */
export function anomalyColor(anomaly: number | null, maxAbs: number): string {
  if (anomaly === null || !Number.isFinite(anomaly) || !(maxAbs > 0)) return NEUTRAL;
  const t = Math.min(1, Math.abs(anomaly) / maxAbs);
  const [r, g, b] = hex(anomaly >= 0 ? WET : DRY);
  const [nr, ng, nb] = hex("#d9dee5");
  const mix = (a: number, c: number) => Math.round(a + (c - a) * t);
  return `rgb(${mix(nr, r)},${mix(ng, g)},${mix(nb, b)})`;
}

/** Column height (metres) proportional to the value against the period's largest value. Missing → flat. */
export function heightFor(value: number | null, maxVal: number): number {
  if (value === null || !(maxVal > 0)) return 0;
  return Math.max(0, Math.min(1, value / maxVal)) * MAX_HEIGHT_M;
}

export function maxAbsAnomaly(months: MonthPoint[]): number {
  return months.reduce((m, p) => (p.anomaly === null ? m : Math.max(m, Math.abs(p.anomaly))), 0);
}

export function maxValue(months: MonthPoint[]): number {
  return months.reduce((m, p) => (p.value === null ? m : Math.max(m, p.value)), 0);
}

export function bboxPolygon(b: [number, number, number, number]) {
  const [w, s, e, n] = b;
  return { type: "Polygon" as const, coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function monthLabel(iso: string): string {
  const [y, m] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}

export function canLocate(geo: GeoInfo): boolean {
  return geo.kind !== "none" && geo.bbox !== null;
}

function edges(c: number[]): number[] {
  if (c.length === 1) return [c[0] - 0.5, c[0] + 0.5];
  const mid = c.slice(1).map((v, i) => (v + c[i]) / 2);
  return [c[0] - (mid[0] - c[0]), ...mid, c[c.length - 1] + (c[c.length - 1] - mid[mid.length - 1])];
}

/** One polygon per valid grid cell, coloured by anomaly (or by value when no anomaly exists) and raised by value. Missing cells are omitted. */
export function gridFeatures(f: GridFrame) {
  const ly = edges(f.lat);
  const lx = edges(f.lon);
  const useAnom = f.anomaly !== null && (f.anomaly_abs_max ?? 0) > 0;
  const vmax = f.value_max ?? 0;
  const out: { type: "Feature"; properties: { color: string; height: number }; geometry: ReturnType<typeof bboxPolygon> }[] = [];
  for (let i = 0; i < f.lat.length; i++) {
    for (let j = 0; j < f.lon.length; j++) {
      const v = f.values[i][j];
      if (v === null) continue;
      const a = useAnom ? f.anomaly![i][j] : null;
      const t = vmax > 0 ? v / vmax : 0;
      const color = useAnom ? anomalyColor(a, f.anomaly_abs_max ?? 0) : anomalyColor(t, 1);
      out.push({
        type: "Feature",
        properties: { color, height: heightFor(v, vmax) },
        geometry: bboxPolygon([lx[j], ly[i], lx[j + 1], ly[i + 1]]),
      });
    }
  }
  return { type: "FeatureCollection" as const, features: out };
}
