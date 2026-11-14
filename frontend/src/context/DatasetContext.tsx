"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { api, type ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { DatasetListResponse, DatasetSummary, MetadataResponse } from "@/lib/types";

interface DatasetContextValue {
  /** All datasets the API knows about (undefined while loading or if the API is unreachable). */
  list: DatasetListResponse | undefined;
  listLoading: boolean;
  listError: ApiError | undefined;
  selectedId: string | null;
  selected: DatasetSummary | undefined;
  select: (id: string) => void;
  metadata: MetadataResponse | undefined;
  metadataLoading: boolean;
  metadataError: ApiError | undefined;
  /** Re-fetch datasets (after an upload or delete) and optionally select a dataset. */
  refresh: (selectId?: string) => void;
  /** Retry the metadata request for the selected dataset. */
  reloadMetadata: () => void;
}

const DatasetContext = createContext<DatasetContextValue | null>(null);

export function DatasetProvider({ children }: { children: ReactNode }) {
  const [chosenId, setChosenId] = useState<string | null>(null);
  const datasets = useApi((signal) => api.datasets(signal), "datasets");
  const list = datasets.data;

  // The effective selection falls back to the API's default if the chosen dataset no longer exists.
  const selectedId =
    chosenId && list?.datasets.some((d) => d.id === chosenId) ? chosenId : (list?.default_dataset_id ?? null);

  const meta = useApi(
    selectedId ? (signal) => api.metadata(selectedId, signal) : null,
    selectedId ? `metadata:${selectedId}` : "",
  );

  const { reload } = datasets;
  const refresh = useCallback(
    (selectId?: string) => {
      if (selectId) setChosenId(selectId);
      reload();
    },
    [reload],
  );

  const value = useMemo<DatasetContextValue>(
    () => ({
      list,
      listLoading: datasets.loading,
      listError: datasets.error,
      selectedId,
      selected: list?.datasets.find((d) => d.id === selectedId),
      select: setChosenId,
      metadata: meta.data,
      metadataLoading: meta.loading,
      metadataError: meta.error,
      refresh,
      reloadMetadata: meta.reload,
    }),
    [list, datasets.loading, datasets.error, selectedId, meta.data, meta.loading, meta.error, meta.reload, refresh],
  );

  return <DatasetContext.Provider value={value}>{children}</DatasetContext.Provider>;
}

export function useDatasets(): DatasetContextValue {
  const ctx = useContext(DatasetContext);
  if (!ctx) throw new Error("useDatasets must be used inside <DatasetProvider>");
  return ctx;
}
