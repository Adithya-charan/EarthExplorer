import { vi } from "vitest";

type Handler = (url: URL, init?: RequestInit) => { status?: number; body?: unknown } | Promise<{ status?: number; body?: unknown }>;

/**
 * Replace global fetch with route handlers keyed by "METHOD /path". Unmatched routes fail the
 * test loudly rather than silently returning data.
 */
export function mockFetch(routes: Record<string, Handler>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = (init?.method ?? "GET").toUpperCase();
    const handler = routes[`${method} ${url.pathname}`];
    if (!handler) throw new Error(`Unmocked request: ${method} ${url.pathname}${url.search}`);
    const { status = 200, body } = await handler(url, init);
    const text = typeof body === "string" ? body : JSON.stringify(body ?? null);
    return new Response(status === 204 ? null : text, {
      status,
      headers: { "Content-Type": typeof body === "string" ? "text/csv" : "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export function requestBodies(fn: ReturnType<typeof mockFetch>, path: string): unknown[] {
  return fn.mock.calls
    .filter(([input]) => new URL(String(input)).pathname === path)
    .map(([, init]) => (init?.body ? JSON.parse(String(init.body)) : null));
}
