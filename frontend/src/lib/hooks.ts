"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ApiError, toApiError } from "./api";

export interface ApiState<T> {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  reload: () => void;
}

/**
 * Run an API call whenever `key` changes. An empty key means "idle" (nothing is fetched).
 * Results from an older key are never shown for a newer key: while a request is in flight
 * `data` is undefined, so the UI can never display results that do not match the filters.
 */
export function useApi<T>(call: ((signal: AbortSignal) => Promise<T>) | null, key: string): ApiState<T> {
  const [nonce, setNonce] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: T; error?: ApiError }>({ key: "" });
  const callRef = useRef(call);
  const fullKey = key ? `${key}#${nonce}` : "";

  useEffect(() => {
    callRef.current = call;
  });

  useEffect(() => {
    if (!fullKey || !callRef.current) return;
    const controller = new AbortController();
    callRef
      .current(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setResult({ key: fullKey, data });
      })
      .catch((err) => {
        if (!controller.signal.aborted) setResult({ key: fullKey, error: toApiError(err) });
      });
    return () => controller.abort();
  }, [fullKey]);

  const current = result.key === fullKey ? result : undefined;
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return {
    data: current?.data,
    error: current?.error,
    loading: fullKey !== "" && current === undefined,
    reload,
  };
}

/** Debounce rapidly changing values (e.g. typed dates) so analysis is not re-run on every keystroke. */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";
function subscribeReducedMotion(cb: () => void) {
  const mq = window.matchMedia(REDUCED_QUERY);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}

export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia(REDUCED_QUERY).matches,
    () => false,
  );
}
