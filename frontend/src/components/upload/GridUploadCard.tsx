"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Layers } from "lucide-react";
import { api, toApiError, type ApiError } from "@/lib/api";
import { useDatasets } from "@/context/DatasetContext";
import type { GridUploadResponse } from "@/lib/types";
import { Button, Callout, Card, CardBody, CardHeader } from "@/components/ui/primitives";

export function GridUploadCard() {
  const { refresh } = useDatasets();
  const [file, setFile] = useState<File | null>(null);
  const [variable, setVariable] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState<GridUploadResponse | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const res = await api.uploadGrid(file, { variable: variable.trim() || undefined, name: name.trim() || undefined });
      setDone(res);
      refresh(res.dataset_id);
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Upload a gridded NetCDF file"
        subtitle="A 3-D variable such as precipitation(time, lat, lon). It gives per-place maps, not just region averages."
      />
      <CardBody>
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-3">
          <label className="text-sm sm:col-span-3">
            <span className="mb-1 block font-medium text-ink">NetCDF file (.nc)</span>
            <input
              type="file"
              accept=".nc,.nc4,.cdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm"
            />
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium text-ink">Variable (optional)</span>
            <input value={variable} onChange={(e) => setVariable(e.target.value)} maxLength={200} className="min-h-9 w-full rounded-md border border-line bg-surface px-2" />
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium text-ink">Dataset name (optional)</span>
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} className="min-h-9 w-full rounded-md border border-line bg-surface px-2" />
          </label>
          <div className="flex items-end">
            <Button type="submit" variant="primary" disabled={!file || busy} className="w-full">
              <Layers size={14} aria-hidden="true" /> {busy ? "Reading…" : "Import grid"}
            </Button>
          </div>
        </form>
        <p className="mt-2 text-xs text-muted">
          Missing cells stay missing. The unit comes from the file (shown as “unspecified” if absent). The regional series is an
          area-weighted mean of the valid cells. GeoTIFF is not supported yet.
        </p>
        {error ? (
          <div className="mt-3">
            <Callout tone="danger" role="alert" title="That file could not be imported">
              <span data-testid="grid-error">{error.message}</span>
            </Callout>
          </div>
        ) : null}
        {done ? (
          <div className="mt-3">
            <Callout tone="accent" role="status" title="Grid imported">
              <span data-testid="grid-success">
                {done.message} {done.variable} ({done.unit}), {done.date_start} to {done.date_end}.{" "}
              </span>
              <Link href="/" className="font-medium underline">
                See what happened
              </Link>
            </Callout>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}
