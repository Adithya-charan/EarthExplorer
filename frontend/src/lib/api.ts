/** Shared HTTP helper for the NASAX API. */

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

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
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
      `Cannot reach the NASAX API at ${API_BASE}. Check that the backend is running.`,
    );
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onAbort);
  }
}
