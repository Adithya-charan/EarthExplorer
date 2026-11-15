import { layerUrl, observationLayerPath } from "./api";
import type { BBox, ChangeSummary, MapMode, ObservationInfo, Outcome } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function yearOptions(from = 1980, to = 2026): number[] {
  const out: number[] = [];
  for (let y = to; y >= from; y--) out.push(y);
  return out;
}

/** "Sep 2012" for monthly data, "2012" for yearly data. */
export function fmtDate(iso: string, temporal: string = "monthly"): string {
  const y = iso.slice(0, 4);
  if (temporal === "yearly") return y;
  const m = Number(iso.slice(5, 7));
  return `${MONTHS[m - 1] ?? "?"} ${y}`;
}

export const fmtHa = (v: number | null | undefined, digits = 1) => (v == null ? "n/a" : `${v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits })} ha`);
export const fmtPct = (v: number | null | undefined, digits = 1) => (v == null ? "n/a" : `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`);

export function dayNumber(iso: string): number {
  return Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)) || 1) / 86_400_000;
}

/** Observations falling inside [startYear, endYear]. Only dates that exist in the dataset are ever returned. */
export function observationsInPeriod(obs: ObservationInfo[], startYear: number, endYear: number): ObservationInfo[] {
  return obs.filter((o) => {
    const y = Number(o.date.slice(0, 4));
    return y >= startYear && y <= endYear;
  });
}

/** 0..1 position of every observation along the time axis, so gaps in the record are visible as gaps. */
export function timelinePositions(dates: string[]): number[] {
  if (dates.length === 0) return [];
  if (dates.length === 1) return [0.5];
  const d = dates.map(dayNumber);
  const lo = d[0];
  const span = d[d.length - 1] - lo || 1;
  return d.map((v) => (v - lo) / span);
}

export function nearestIndex(positions: number[], x: number): number {
  let best = 0;
  let bestD = Infinity;
  positions.forEach((p, i) => {
    const dist = Math.abs(p - x);
    if (dist < bestD) {
      bestD = dist;
      best = i;
    }
  });
  return best;
}

export function stepIndex(i: number, n: number, dir: 1 | -1, wrap = false): number {
  if (n <= 0) return 0;
  const next = i + dir;
  if (next < 0) return wrap ? n - 1 : 0;
  if (next >= n) return wrap ? 0 : n - 1;
  return next;
}

export const PLAY_SPEEDS = [0.5, 1, 2, 4] as const;
export const playDelayMs = (speed: number) => Math.round(1400 / speed);

export const OUTCOME_COPY: Record<Outcome, { badge: string; tone: "change" | "calm" | "warn" }> = {
  change_detected: { badge: "Change detected", tone: "change" },
  no_clear_change: { badge: "No clear change", tone: "calm" },
  insufficient_data: { badge: "Insufficient data", tone: "warn" },
};

export interface LayerSpec {
  key: string;
  url: string;
  bbox: BBox;
  alpha: number;
  side: "none" | "left" | "right";
}

export interface MapPlan {
  primary: LayerSpec | null;
  secondary: LayerSpec | null;
  split: boolean;
  hotspots: boolean;
  legend: "diff" | "classes";
  caption: string;
}

export interface PlanInput {
  mode: MapMode;
  summary: ChangeSummary | null;
  datasetId: string | null;
  bbox: BBox | null;
  latestDate: string | null;
  cursorDate: string | null;
  baShowAfter: boolean;
  temporal: string;
}

/** Decide which raster layers the globe shows for a map mode. Every layer URL points at a real observation or analysis product. */
export function planLayers(i: PlanInput): MapPlan {
  const none: MapPlan = { primary: null, secondary: null, split: false, hotspots: false, legend: "classes", caption: "" };
  if (!i.datasetId || !i.bbox) return none;
  const bbox = i.bbox;
  const obs = (date: string, side: LayerSpec["side"] = "none"): LayerSpec => ({ key: `obs:${date}`, url: layerUrl(observationLayerPath(i.datasetId!, date)), bbox, alpha: 0.92, side });
  const s = i.summary;
  const hasAnalysis = s != null && s.analysis_id != null && s.outcome !== "insufficient_data";
  const fmt = (d: string) => fmtDate(d, i.temporal);
  switch (i.mode) {
    case "latest":
      return i.latestDate ? { ...none, primary: obs(i.latestDate), caption: `Latest available observation · ${fmt(i.latestDate)}` } : none;
    case "history":
      return i.cursorDate ? { ...none, primary: obs(i.cursorDate), caption: `Historical observation · ${fmt(i.cursorDate)}` } : none;
    case "beforeafter": {
      const d = i.baShowAfter ? s?.last_observation : s?.first_observation;
      return d ? { ...none, primary: obs(d.date), caption: `${i.baShowAfter ? "After" : "Before"} · ${fmt(d.date)}` } : none;
    }
    case "swipe": {
      if (!s?.first_observation || !s.last_observation) return none;
      return { ...none, primary: obs(s.first_observation.date, "left"), secondary: obs(s.last_observation.date, "right"), split: true, caption: `Swipe: ${fmt(s.first_observation.date)} (left) · ${fmt(s.last_observation.date)} (right)` };
    }
    case "difference":
    case "hotspots": {
      if (!hasAnalysis || !s) return none;
      const diff: LayerSpec = { key: `diff:${s.analysis_id}`, url: layerUrl(s.layers.difference_png), bbox, alpha: i.mode === "hotspots" ? 0.55 : 0.95, side: "none" };
      return { ...none, primary: diff, hotspots: i.mode === "hotspots", legend: "diff", caption: i.mode === "hotspots" ? "Change hotspots" : "Difference layer: water gained and lost" };
    }
  }
}

/** Largest bounding box containing all the given boxes (for framing a set of hotspots). */
export function unionBBox(boxes: BBox[]): BBox | null {
  if (boxes.length === 0) return null;
  return boxes.reduce<BBox>((a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])], [...boxes[0]] as BBox);
}

/** Approximate ground radius (m) of a lon/lat box, used to frame a hotspot. */
export function bboxRadiusM(b: BBox): number {
  const midLat = (b[1] + b[3]) / 2;
  const w = (b[2] - b[0]) * 111_320 * Math.cos((midLat * Math.PI) / 180);
  const h = (b[3] - b[1]) * 110_574;
  return Math.max(120, Math.hypot(w, h) / 2);
}
