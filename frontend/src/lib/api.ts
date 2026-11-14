import type { GeoJSONFeatureCollection } from "./earth/types";
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ColumnMapping,
  CompareRequest,
  ChatRequest,
  ChatResponse,
  CompareResponse,
  DatasetListResponse,
  DiagnosticsResponse,
  GridFrame,
  GridUploadResponse,
  MetadataResponse,
  MethodologyResponse,
  ObservationsResponse,
  RegionsResponse,
  OverviewResponse,
  AtlasResponse,
  SnapshotResponse,
  SourceProfile,
  StoryRequest,
  StoryResponse,
  UploadResponse,
} from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
export const REQUEST_TIMEOUT_MS = 30_000;

/** Error with a stable code and a message that is safe to show to users. */
export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError(0, "unknown_error", err instanceof Error ? err.message : "Something went wrong.");
}

interface RequestOptions {
  method?: "GET" | "POST" | "DELETE";
  json?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  timeoutMs?: number;
  raw?: boolean;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, opts.timeoutMs ?? REQUEST_TIMEOUT_MS);
  const onAbort = () => controller.abort();
  opts.signal?.addEventListener("abort", onAbort);

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? (opts.json || opts.form ? "POST" : "GET"),
      headers: opts.json ? { "Content-Type": "application/json" } : undefined,
      body: opts.form ?? (opts.json ? JSON.stringify(opts.json) : undefined),
      signal: controller.signal,
    });
    if (!res.ok) {
      let code = "http_error";
      let message = `The server responded with status ${res.status}.`;
      let details: unknown;
      try {
        const body = await res.json();
        if (body?.error) {
          code = body.error.code ?? code;
          message = body.error.message ?? message;
          details = body.error.details;
        }
      } catch {
        /* non-JSON error body: keep the generic message */
      }
      throw new ApiError(res.status, code, message, details);
    }
    if (res.status === 204) return undefined as T;
    return (opts.raw ? await res.text() : await res.json()) as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (opts.signal?.aborted) throw err; // caller cancelled: let the hook ignore it
    if (timedOut) {
      throw new ApiError(0, "timeout", "The request took too long and was cancelled. Try a smaller selection.");
    }
    throw new ApiError(
      0,
      "network_error",
      `Cannot reach the EarthTrend API at ${API_BASE}. Check that the backend is running.`,
    );
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onAbort);
  }
}

const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export interface ObservationQuery {
  dataset_id: string;
  variable?: string;
  region?: string;
  start?: string;
  end?: string;
  limit?: number;
  offset?: number;
  include_missing?: boolean;
}

export const api = {
  datasets: (signal?: AbortSignal) => request<DatasetListResponse>("/api/datasets", { signal }),
  metadata: (datasetId: string, signal?: AbortSignal) =>
    request<MetadataResponse>(`/api/metadata${qs({ dataset_id: datasetId })}`, { signal }),
  observations: (q: ObservationQuery, signal?: AbortSignal) =>
    request<ObservationsResponse>(`/api/observations${qs({ ...q })}`, { signal }),
  observationsCsv: (q: Omit<ObservationQuery, "limit" | "offset">, signal?: AbortSignal) =>
    request<string>(`/api/observations${qs({ ...q, format: "csv" })}`, { signal, raw: true }),
  diagnostics: (q: { dataset_id: string; variable: string; region: string }, signal?: AbortSignal) =>
    request<DiagnosticsResponse>(`/api/diagnostics${qs(q)}`, { signal }),
  analyze: (body: AnalyzeRequest, signal?: AbortSignal) =>
    request<AnalyzeResponse>("/api/analyze", { json: body, signal }),
  compare: (body: CompareRequest, signal?: AbortSignal) =>
    request<CompareResponse>("/api/compare", { json: body, signal }),
  regions: (datasetId: string, signal?: AbortSignal) =>
    request<RegionsResponse>(`/api/regions${qs({ dataset_id: datasetId })}`, { signal }),
  overview: (datasetId: string, region: string, signal?: AbortSignal) =>
    request<OverviewResponse>(`/api/overview${qs({ dataset_id: datasetId, region })}`, { signal }),
  snapshot: (datasetId: string, year: number, month: number, signal?: AbortSignal) =>
    request<SnapshotResponse>(`/api/snapshot${qs({ dataset_id: datasetId, year, month })}`, { signal }),
  atlas: (datasetId: string, signal?: AbortSignal) => request<AtlasResponse>(`/api/atlas${qs({ dataset_id: datasetId })}`, { signal }),
  story: (body: StoryRequest, signal?: AbortSignal) => request<StoryResponse>("/api/story", { json: body, signal }),
  uploadGrid: (file: File, opts: { variable?: string; name?: string } = {}, signal?: AbortSignal) => {
    const form = new FormData();
    form.set("file", file);
    if (opts.variable) form.set("variable", opts.variable);
    if (opts.name) form.set("dataset_name", opts.name);
    return request<GridUploadResponse>("/api/upload-grid", { form, signal, timeoutMs: 120_000 });
  },
  gridFrame: (datasetId: string, month: string, signal?: AbortSignal) =>
    request<GridFrame>(`/api/grid${qs({ dataset_id: datasetId, month })}`, { signal }),
  chat: (body: ChatRequest, signal?: AbortSignal) => request<ChatResponse>("/api/chat", { json: body, signal }),
  methodology: (signal?: AbortSignal) => request<MethodologyResponse>("/api/methodology", { signal }),
  profile: (file: File, signal?: AbortSignal) => {
    const form = new FormData();
    form.set("file", file);
    return request<SourceProfile>("/api/profile", { form, signal, timeoutMs: 120_000 });
  },
  upload: (
    file: File,
    mapping: ColumnMapping,
    opts: { dryRun: boolean; confirmed: boolean; datasetName?: string },
    signal?: AbortSignal,
  ) => {
    const form = new FormData();
    form.set("file", file);
    form.set("mapping", JSON.stringify(mapping));
    form.set("dry_run", String(opts.dryRun));
    form.set("confirmed", String(opts.confirmed));
    if (opts.datasetName) form.set("dataset_name", opts.datasetName);
    return request<UploadResponse>("/api/upload", { form, signal, timeoutMs: 120_000 });
  },
  deleteDataset: (id: string) => request<void>(`/api/datasets/${encodeURIComponent(id)}`, { method: "DELETE" }),

  // ---- Map outlines ----
  boundaries: (opts: { simplify?: number } = {}, signal?: AbortSignal) =>
    request<GeoJSONFeatureCollection & { source: { note: string } }>(`/api/geography/boundaries${qs({ simplify: opts.simplify })}`, { signal }),
};
