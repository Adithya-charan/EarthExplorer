import { API_BASE, request } from "../api";
import type { ChatAnswer } from "./types";

const base = "/api/explorer/deeptime";

export type DeepModel = "earthbyte" | "paleomap";
/** What the globe shows in Deep-Time Earth: the reconstruction, fossil finds, or named geological formations. */
export type DeepView = "reconstruction" | "fossils" | "formations";
export type AppEra = "today" | "historical" | "deep";

export interface DeepAgeInfo {
  age_ma: number;
  key: string;
  label: string;
  era: string;
  period: string;
  epoch: string;
  boundary: string;
  has_paleogeography: boolean;
  paleomap_age_ma: number | null;
  paleomap_exact: boolean | null;
  interpolation: Record<DeepModel, string>;
}

export interface TimescaleInterval {
  name: string;
  t_age: number;
  b_age: number;
  color: string | null;
}

export interface DeepManifest {
  mode_label: string;
  models: Record<DeepModel, string>;
  requested_ages: number[];
  added_ages: number[];
  ages: DeepAgeInfo[];
  timescale: { periods: TimescaleInterval[]; epochs: TimescaleInterval[]; eras: TimescaleInterval[] };
}

export interface DeepLayer {
  name: string;
  label: string;
  kind: string;
  url: string;
  features?: number;
}

export interface DeepEvent {
  event_id: string;
  event_name: string;
  start_age_ma: number;
  end_age_ma: number;
  affected_region: string;
  geological_process: string;
  description: string;
  evidence_source: string;
  confidence: string;
  uncertainty_notes: string;
  kind: string;
}

export interface PlatePosition {
  india: [number, number] | null;
  eurasia: [number, number] | null;
  gap_km: number | null;
  eurasia_plate_id: number | null;
}

export interface DeepFrame {
  age_ma: number;
  requested_age_ma: number;
  label: string;
  key: string;
  model: DeepModel;
  model_label: string;
  mode_label: string;
  era: string;
  period: string;
  epoch: string;
  age_stage: string;
  boundary: string;
  layers: DeepLayer[];
  raster: { url: string; map_age_ma: number; map_name: string; exact: boolean; offset_ma: number; note: string } | null;
  india: Record<DeepModel, PlatePosition>;
  models_disagree_km: number | null;
  interpolation: string;
  has_paleogeography: boolean;
  events: DeepEvent[];
  environment: { kind: string; points: { id: string; name: string; context: string | null }[] };
  fossil_count: number;
  caveat: string;
  resolution: string;
  sources: { id: string; role: string }[];
  confidence: string;
}

export interface DeepPlace {
  id: string;
  name: string;
  modern_position: { latitude: number; longitude: number };
  age_ma: number;
  age_label: string;
  plate: Record<DeepModel, { plate_id: number | null; plate_name: string | null; method: string }>;
  reconstructed_position: Record<DeepModel, [number, number] | null>;
  models_disagree_km: number | null;
  paleogeography_context: string | null;
  explanation: string;
  limitations: string[];
}

export interface Reference {
  id: string;
  citation: string;
  doi: string;
  role: string;
}

export interface HimalayaStage {
  age_ma: number;
  label: string;
  stage: string;
  collision: string;
  process: string;
  mountains: string;
  evidence: string;
  uncertainty: string;
  sources: string;
  india_position: Record<DeepModel, [number, number] | null>;
  india_eurasia_gap_km: Record<DeepModel, number | null>;
  references: Reference[];
}

export interface DinoSlice {
  age_ma: number;
  label: string;
  period: string;
  epoch: string;
  boundary: string;
  fossil_count: number;
  fossil_count_within_5_ma: number;
  has_paleogeography: boolean;
  paleomap: string | null;
}

export interface FossilProps {
  occurrence_id: string;
  taxon_name: string;
  higher_taxonomy: string;
  fossil_type: string;
  geological_period: string;
  minimum_age_ma: number;
  maximum_age_ma: number;
  age_label: string;
  locality: string;
  state: string;
  formation: string;
  reference_id: string;
  reference_text: string;
  source_database: string;
  data_quality: string;
  modern_latitude: number;
  modern_longitude: number;
  is_bird?: boolean;
}

export interface PointCollection<P> {
  type: "FeatureCollection";
  features: { type: "Feature"; properties: P; geometry: { type: "Point"; coordinates: [number, number] } }[];
  properties: { note: string };
}

export const deepApi = {
  manifest: (signal?: AbortSignal) => request<DeepManifest>(`${base}/manifest`, { signal, timeoutMs: 20_000 }),
  frame: (age: number, model: DeepModel, signal?: AbortSignal) => request<DeepFrame>(`${base}/frames/${age}?model=${model}`, { signal, timeoutMs: 20_000 }),
  fossils: (age: number, model: DeepModel, window: number, signal?: AbortSignal) => request<PointCollection<FossilProps>>(`${base}/frames/${age}/fossils?model=${model}&window=${window}`, { signal }),
  formations: (age: number, model: DeepModel, window: number, signal?: AbortSignal) => request<PointCollection<Record<string, unknown>>>(`${base}/frames/${age}/formations?model=${model}&window=${window}`, { signal }),
  place: (id: string, age: number, signal?: AbortSignal) => request<DeepPlace>(`${base}/places/${id}?age=${age}`, { signal }),
  himalaya: (signal?: AbortSignal) => request<{ title: string; note: string; gap_note: string; stages: HimalayaStage[] }>(`${base}/himalaya`, { signal }),
  dinosaurs: (signal?: AbortSignal) => request<{ title: string; note: string; slices: DinoSlice[] }>(`${base}/dinosaur-era`, { signal }),
  references: (signal?: AbortSignal) => request<Reference[]>(`${base}/references`, { signal }),
  chat: (body: { question: string; age: number; location: string | null; history: { role: string; content: string }[] }, signal?: AbortSignal) =>
    request<ChatAnswer>(`/api/explorer/ai/chat`, { json: { question: body.question, analysis_id: null, history: body.history, deep_time: true, deep_time_age: body.age, deep_time_location: body.location }, signal, timeoutMs: 60_000 }),
};

export const deepUrl = (path: string) => (path.startsWith("http") ? path : `${API_BASE}${path}`);

// ------------------------------------------------------------------------------------------- pure helpers
/** "66 million years ago", "10,000 years ago", "present day". Ages are Ma (millions of years before present). */
export function formatAge(ma: number): string {
  if (ma === 0) return "Present day";
  if (ma < 1) return `${Math.round(ma * 1e6).toLocaleString("en-US")} years ago`;
  return `${Number.isInteger(ma) ? ma : ma.toLocaleString("en-US", { maximumFractionDigits: 2 })} million years ago`;
}

export function formatMa(ma: number): string {
  if (ma === 0) return "0 Ma";
  if (ma < 1) return `${(ma * 1000).toLocaleString("en-US", { maximumFractionDigits: 1 })} ka`;
  return `${ma.toLocaleString("en-US", { maximumFractionDigits: 3 })} Ma`;
}

export function nearestAge(ages: number[], value: number): number {
  let best = ages[0] ?? 0;
  for (const a of ages) if (Math.abs(a - value) < Math.abs(best - value)) best = a;
  return best;
}

/** Ages sorted oldest first are stepped towards the present with dir = -1 (younger) or +1 (older). Never wraps. */
export function stepAge(ages: number[], current: number, dir: 1 | -1): number {
  const sorted = [...ages].sort((a, b) => a - b);
  const i = sorted.indexOf(nearestAge(sorted, current));
  return sorted[Math.max(0, Math.min(sorted.length - 1, i + dir))];
}

export const fmtLatLon = (p: [number, number] | null | undefined) => (p ? `${Math.abs(p[0]).toFixed(1)}°${p[0] >= 0 ? "N" : "S"}, ${Math.abs(p[1]).toFixed(1)}°${p[1] >= 0 ? "E" : "W"}` : "not available");

/** Ages that get a printed label under the slider (all remain selectable). */
export const LABELLED_AGES = [0, 0.01, 1, 10, 20, 30, 50, 66, 100, 150, 200, 250];

export const MODE_LABELS: Record<AppEra, string> = { today: "Earth Today", historical: "Historical Earth", deep: "Deep-Time Earth" };

/** The period colour of an age from the ICS-derived timescale shipped with the manifest. */
export function periodColor(manifest: DeepManifest | null, age: number): string {
  const p = manifest?.timescale.periods.find((x) => age >= x.t_age && age < x.b_age) ?? manifest?.timescale.periods[0];
  return p?.color ?? "#4b5563";
}
