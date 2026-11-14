"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useDatasets } from "@/context/DatasetContext";
import type { MetadataResponse } from "@/lib/types";
import { DatasetInfoCard } from "@/components/data/DatasetInfoCard";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";

/**
 * Renders children only once a dataset and its metadata are available, otherwise the correct
 * loading, error or empty state. Keeps every page's first-load behaviour identical.
 */
export function DataGate({
  children,
}: {
  children: (ctx: { metadata: MetadataResponse; datasetId: string }) => ReactNode;
}) {
  const { list, listLoading, listError, refresh, selectedId, metadata, metadataLoading, metadataError, reloadMetadata } =
    useDatasets();

  if (listLoading) return <LoadingState label="Loading datasets" variant="cards" />;
  if (listError)
    return <ErrorState title="Could not load datasets" error={listError} onRetry={() => refresh()} />;
  if (!list || list.datasets.length === 0 || !selectedId)
    return (
      <EmptyState
        title="No dataset is loaded"
        description="The API reported no datasets. Check that the backend can read the demo CSV, or upload a CSV file."
        action={
          <Link
            href="/upload"
            className="inline-flex min-h-9 items-center rounded-md border border-accent bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-strong"
          >
            Upload a dataset
          </Link>
        }
      />
    );
  if (metadataLoading || (!metadata && !metadataError)) return <LoadingState label="Loading dataset details" variant="cards" />;
  if (metadataError)
    return <ErrorState title="Could not load dataset details" error={metadataError} onRetry={reloadMetadata} />;
  if (!metadata) return null;
  return (
    <>
      <DatasetInfoCard info={metadata.dataset.info} />
      {children({ metadata, datasetId: selectedId })}
    </>
  );
}
