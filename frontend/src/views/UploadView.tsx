"use client";

import Link from "next/link";
import { useState } from "react";
import { CheckCircle2, FileSpreadsheet, ShieldAlert, Trash2 } from "lucide-react";
import { api, toApiError, type ApiError } from "@/lib/api";
import { useDatasets } from "@/context/DatasetContext";
import { fmtInt } from "@/lib/format";
import { EMPTY_MAPPING, missingRequired } from "@/lib/upload";
import type { ColumnMapping, SourceProfile, UploadResponse } from "@/lib/types";
import { UploadDropzone } from "@/components/upload/UploadDropzone";
import { ColumnMapper } from "@/components/upload/ColumnMapper";
import { GridUploadCard } from "@/components/upload/GridUploadCard";
import { QualityReportView } from "@/components/upload/QualityReportView";
import { DatasetStatus } from "@/components/data/DatasetStatus";
import { Badge, Button, Callout, Card, CardBody, CardHeader, PageHeading } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";

type Phase = "idle" | "profiling" | "validating" | "importing";

export function UploadView() {
  const { list, refresh } = useDatasets();
  const [file, setFile] = useState<File | null>(null);
  const [profile, setProfile] = useState<SourceProfile | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping>(EMPTY_MAPPING);
  const [name, setName] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<ApiError | null>(null);
  const [dryRun, setDryRun] = useState<UploadResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [imported, setImported] = useState<UploadResponse | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<ApiError | null>(null);

  const busy = phase !== "idle";
  const missing = missingRequired(mapping);

  function reset() {
    setFile(null);
    setProfile(null);
    setMapping(EMPTY_MAPPING);
    setName("");
    setDryRun(null);
    setConfirmed(false);
    setImported(null);
    setError(null);
    setPhase("idle");
  }

  async function handleFile(f: File) {
    reset();
    setFile(f);
    setPhase("profiling");
    try {
      const p = await api.profile(f);
      setProfile(p);
      setMapping(p.suggested_mapping);
      setName(f.name.replace(/\.csv$/i, ""));
    } catch (err) {
      setError(toApiError(err));
      setFile(null);
    } finally {
      setPhase("idle");
    }
  }

  function updateMapping(next: ColumnMapping) {
    setMapping(next);
    // Any change to the mapping makes the previous validation stale.
    setDryRun(null);
    setConfirmed(false);
    setImported(null);
  }

  async function run(dry: boolean) {
    if (!file) return;
    setError(null);
    setPhase(dry ? "validating" : "importing");
    try {
      const res = await api.upload(file, mapping, { dryRun: dry, confirmed, datasetName: name.trim() || undefined });
      if (dry) {
        setDryRun(res);
      } else {
        setImported(res);
        refresh(res.dataset?.id);
      }
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setPhase("idle");
    }
  }

  async function remove(id: string) {
    setDeleteError(null);
    try {
      await api.deleteDataset(id);
      refresh();
    } catch (err) {
      setDeleteError(toApiError(err));
    } finally {
      setDeleting(null);
    }
  }

  const needsConfirm = Boolean(dryRun?.quality.requires_confirmation);
  const canImport = Boolean(dryRun?.quality.can_import) && (!needsConfirm || confirmed) && !busy;
  const uploaded = list?.datasets.filter((d) => d.status === "uploaded") ?? [];

  return (
    <div className="space-y-6">
      <PageHeading
        title="Upload Dataset"
        description="Import a CSV with an explicit column mapping. Uploads are kept separate from the demo data, are labelled as unverified, and are never treated as NASA-verified."
      />

      <Callout tone="info" role="note" icon={<ShieldAlert size={18} />} title="What upload does and does not do">
        Tables are imported as CSV with a column mapping; gridded data as NetCDF (below). HDF5 and GeoTIFF are not read. Units and provenance come from you and are never guessed
        or converted. A successful import means the file is well-formed, not that its contents are correct.
      </Callout>

      <GridUploadCard />

      {imported?.dataset ? (
        <Callout tone="accent" role="status" icon={<CheckCircle2 size={18} />} title="Dataset imported">
          <p data-testid="import-success">
            {imported.message} It is now the selected dataset ({fmtInt(imported.dataset.n_valid)} valid observations).
          </p>
          <div className="mt-2 flex flex-wrap gap-3">
            <Link href="/trend" className="font-medium underline">
              Analyse trends
            </Link>
            <Link href="/" className="font-medium underline">
              See what happened
            </Link>
            <button type="button" onClick={reset} className="font-medium underline">
              Upload another file
            </button>
          </div>
        </Callout>
      ) : null}

      {!profile ? (
        <Card aria-labelledby="upload-title">
          <CardHeader id="upload-title" title="1. Choose a file" />
          <CardBody>
            {phase === "profiling" ? (
              <LoadingState label="Reading and profiling the file" variant="block" />
            ) : (
              <UploadDropzone onFile={handleFile} disabled={busy} />
            )}
            {error ? (
              <div className="mt-4">
                <ErrorState title="The file could not be read" error={error} />
              </div>
            ) : null}
          </CardBody>
        </Card>
      ) : (
        <>
          <Card aria-labelledby="profile-title">
            <CardHeader
              id="profile-title"
              title="1. File preview"
              subtitle={`${profile.filename} · ${fmtInt(profile.n_rows)} rows · ${profile.n_columns} columns · ${profile.encoding}, delimiter “${profile.delimiter}”`}
              actions={
                <Button onClick={reset} disabled={busy}>
                  <FileSpreadsheet aria-hidden="true" size={14} /> Choose a different file
                </Button>
              }
            />
            <CardBody className="space-y-3">
              {profile.warnings.length > 0 ? (
                <Callout tone="warn" role="note" title="File warnings">
                  <ul className="list-disc space-y-1 pl-5">
                    {profile.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </Callout>
              ) : null}
              <div className="max-h-72 overflow-auto rounded-md border border-line" tabIndex={0} aria-label="Preview of the first rows">
                <table className="w-full text-left text-sm" data-testid="upload-preview">
                  <caption className="sr-only">First rows of {profile.filename}</caption>
                  <thead className="sticky top-0 bg-surface-muted text-xs text-muted">
                    <tr>
                      {profile.columns.map((c) => (
                        <th key={c} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {profile.preview.map((row, i) => (
                      <tr key={i} className="border-t border-line">
                        {profile.columns.map((c) => (
                          <td key={c} className="whitespace-nowrap px-3 py-1.5 text-ink-soft">
                            {row[c]}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <details>
                <summary className="cursor-pointer text-sm text-muted hover:text-ink">Column profile</summary>
                <div className="mt-2 overflow-x-auto rounded-md border border-line">
                  <table className="w-full text-left text-sm">
                    <caption className="sr-only">Inferred type and completeness of each column</caption>
                    <thead className="bg-surface-muted text-xs text-muted">
                      <tr>
                        <th scope="col" className="px-3 py-2 font-medium">Column</th>
                        <th scope="col" className="px-3 py-2 font-medium">Inferred type</th>
                        <th scope="col" className="px-3 py-2 font-medium">Non-empty</th>
                        <th scope="col" className="px-3 py-2 font-medium">Unique</th>
                        <th scope="col" className="px-3 py-2 font-medium">Examples</th>
                      </tr>
                    </thead>
                    <tbody>
                      {profile.column_profiles.map((c) => (
                        <tr key={c.name} className="border-t border-line">
                          <th scope="row" className="px-3 py-1.5 font-medium text-ink">{c.name}</th>
                          <td className="px-3 py-1.5">{c.inferred_type}</td>
                          <td className="tabular px-3 py-1.5">{fmtInt(c.n_non_empty)}</td>
                          <td className="tabular px-3 py-1.5">{fmtInt(c.n_unique)}</td>
                          <td className="px-3 py-1.5 text-muted">{c.examples.slice(0, 3).join(", ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </CardBody>
          </Card>

          <Card aria-labelledby="mapping-title">
            <CardHeader
              id="mapping-title"
              title="2. Map columns"
              subtitle="Suggestions are a starting point. Check each one; anything not in the file must be declared by you."
            />
            <CardBody className="space-y-4">
              <ColumnMapper columns={profile.columns} mapping={mapping} onChange={updateMapping} notes={profile.mapping_notes} />
              <div className="max-w-md">
                <label htmlFor="dataset-name" className="mb-1 block text-xs font-medium text-ink-soft">
                  Dataset name
                </label>
                <input
                  id="dataset-name"
                  type="text"
                  value={name}
                  maxLength={200}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full rounded-md border border-line-strong bg-surface px-2.5 py-2 text-sm text-ink"
                />
              </div>
              {missing.length > 0 ? (
                <p role="status" className="text-sm text-warn" data-testid="mapping-missing">
                  Still needed before validating: {missing.join(", ")}.
                </p>
              ) : null}
            </CardBody>
          </Card>

          <Card aria-labelledby="validate-title">
            <CardHeader
              id="validate-title"
              title="3. Validate and import"
              subtitle="Validation checks the whole file against your mapping without importing anything."
              actions={
                <Button variant="primary" onClick={() => run(true)} disabled={busy || missing.length > 0}>
                  {phase === "validating" ? "Validating…" : "Validate file"}
                </Button>
              }
            />
            <CardBody className="space-y-4">
              {phase === "validating" || phase === "importing" ? (
                <LoadingState label={phase === "validating" ? "Validating" : "Importing"} variant="block" />
              ) : null}
              {error && profile ? <ErrorState title="Upload failed" error={error} /> : null}
              {dryRun ? <QualityReportView report={dryRun.quality} /> : null}
              {dryRun?.quality.can_import ? (
                <div className="space-y-3 border-t border-line pt-4">
                  {needsConfirm ? (
                    <label className="flex cursor-pointer items-start gap-2 text-sm text-ink">
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 accent-[#0f766e]"
                        checked={confirmed}
                        onChange={(e) => setConfirmed(e.target.checked)}
                      />
                      <span>I have read the ambiguities above and confirm this mapping is correct.</span>
                    </label>
                  ) : null}
                  <Button variant="primary" onClick={() => run(false)} disabled={!canImport || Boolean(imported)}>
                    {phase === "importing" ? "Importing…" : "Import dataset"}
                  </Button>
                </div>
              ) : null}
            </CardBody>
          </Card>
        </>
      )}

      <Card aria-labelledby="uploaded-title">
        <CardHeader id="uploaded-title" title="Uploaded datasets" subtitle="Held by the local API; they survive restarts until you delete them." />
        <CardBody>
          {deleteError ? <ErrorState title="Could not delete dataset" error={deleteError} /> : null}
          {uploaded.length === 0 ? (
            <p className="text-sm text-muted">No uploaded datasets yet.</p>
          ) : (
            <ul className="divide-y divide-line">
              {uploaded.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink">{d.name}</p>
                    <p className="text-xs text-muted">
                      {fmtInt(d.n_valid)} valid observations · {d.n_series} series
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <DatasetStatus status={d.status} isSynthetic={d.is_synthetic} />
                    {deleting === d.id ? (
                      <>
                        <Button onClick={() => remove(d.id)} aria-label={`Confirm delete ${d.name}`}>
                          Confirm delete
                        </Button>
                        <Button variant="ghost" onClick={() => setDeleting(null)}>
                          Cancel
                        </Button>
                      </>
                    ) : (
                      <Button variant="ghost" onClick={() => setDeleting(d.id)} aria-label={`Delete ${d.name}`}>
                        <Trash2 aria-hidden="true" size={14} /> Delete
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-muted">
            <Badge tone="neutral">Unverified</Badge> Uploaded data are never marked as NASA-verified, whatever the file claims.
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
