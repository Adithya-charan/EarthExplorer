import { API_BASE, request } from "../api";
import type { BoundaryOut, ChangeSummary, ChatAnswer, DatasetInfo, Explanation, HotspotCollection, LocationOut, ObservationInfo, SessionResponse } from "./types";

const base = "/api/explorer";

export const explorerApi = {
  datasets: (signal?: AbortSignal) => request<DatasetInfo[]>(`${base}/datasets`, { signal }),
  searchLocations: (q: string, signal?: AbortSignal) => request<LocationOut[]>(`${base}/locations/search?q=${encodeURIComponent(q)}`, { signal }),
  suggest: (q: string, signal?: AbortSignal) => request<LocationOut[]>(`${base}/locations/suggest?q=${encodeURIComponent(q)}`, { signal, timeoutMs: 8_000 }),
  boundary: (locationId: string, signal?: AbortSignal) => request<BoundaryOut>(`${base}/locations/${locationId}/boundary`, { signal, timeoutMs: 20_000 }),
  session: (body: { query?: string; location_id?: string; start_year: number; end_year: number; dataset_id?: string }, signal?: AbortSignal) =>
    request<SessionResponse>(`${base}/session`, { json: body, signal, timeoutMs: 40_000 }),
  detect: (body: { dataset_id: string; start_year: number; end_year: number; params?: { variable?: string } }, signal?: AbortSignal) =>
    request<ChangeSummary>(`${base}/analysis/detect-change`, { json: body, signal, timeoutMs: 90_000 }),
  observations: (datasetId: string, signal?: AbortSignal) => request<ObservationInfo[]>(`${base}/datasets/${datasetId}/observations`, { signal }),
  hotspots: (analysisId: string, signal?: AbortSignal) => request<HotspotCollection>(`${base}/analysis/${analysisId}/hotspots`, { signal }),
  explain: (analysisId: string, signal?: AbortSignal) => request<Explanation>(`${base}/analysis/${analysisId}/explain`, { method: "POST", signal, timeoutMs: 60_000 }),
  chat: (body: { question: string; analysis_id: string | null; history: { role: string; content: string }[] }, signal?: AbortSignal) =>
    request<ChatAnswer>(`${base}/ai/chat`, { json: body, signal, timeoutMs: 60_000 }),
};

/** Absolute URL for an image layer path returned by the API. */
export const layerUrl = (path: string) => (path.startsWith("http") ? path : `${API_BASE}${path}`);
export const observationLayerPath = (datasetId: string, date: string) => `${base}/datasets/${datasetId}/observations/${date}/layer.png`;
