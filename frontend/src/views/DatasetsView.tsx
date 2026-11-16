"use client";

import { useEffect, useMemo, useState } from "react";
import { Download, FileText } from "lucide-react";
import { explorerApi } from "@/lib/explorer/api";
import { analyticsApi, isOfficial, type DatasetStats } from "@/lib/explorer/analytics";
import { metadataCsv, metadataRecord, observationsCsv, seriesCsv } from "@/lib/explorer/export";
import type { DatasetInfo } from "@/lib/explorer/types";
import { toApiError } from "@/lib/api";
import { Badge, Card, ErrorBox, Loading, Note, PageTitle } from "@/components/analytics/ui";

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function DatasetsView() {
  const [list, setList] = useState<DatasetInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [stats, setStats] = useState<Record<string, DatasetStats>>({});
  const [q, setQ] = useState("");

  useEffect(() => {
    let live = true;
    explorerApi.datasets().then((d) => live && setList(d)).catch((e) => live && setError(toApiError(e).message));
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    if (!sel || stats[sel]) return;
    let live = true;
    analyticsApi.stats(sel).then((s) => live && setStats((m) => ({ ...m, [sel]: s }))).catch(() => {});
    return () => {
      live = false;
    };
  }, [sel, stats]);

  const shown = useMemo(() => (list ?? []).filter((d) => `${d.name} ${d.source} ${d.id}`.toLowerCase().includes(q.trim().toLowerCase())), [list, q]);
  if (error) return <ErrorBox message={error} />;
  if (!list) return <Loading what="datasets" />;
  const cur = list.find((d) => d.id === sel) ?? null;
  const st = cur ? stats[cur.id] ?? null : null;

  return (
    <>
      <PageTitle title="Datasets">
        Every dataset in the Earth Time Machine as a citable record: description, provenance, coverage and format, with downloadable CSV files for the observations, the time series and the metadata.
      </PageTitle>
      <div className="grid gap-6 lg:grid-cols-[minmax(280px,380px)_1fr]">
        <Card title={`${shown.length} of ${list.length} datasets`} testid="dataset-list">
          <input className="nx-input mb-3 w-full" placeholder="Filter by name or source" aria-label="Filter datasets" value={q} onChange={(e) => setQ(e.target.value)} />
          <ul className="space-y-1.5">
            {shown.map((d) => (
              <li key={d.id}>
                <button type="button" onClick={() => setSel(d.id)} aria-pressed={d.id === sel} className={`w-full rounded-lg border p-2.5 text-left ${d.id === sel ? "border-[color:var(--nx-accent)] bg-sky-50" : "border-[color:var(--nx-line)] hover:bg-slate-50"}`}>
                  <span className="flex items-start justify-between gap-2">
                    <span className="text-[13px] font-semibold">{d.name}</span>
                    <Badge tone={isOfficial(d) ? "official" : "illustrative"}>{(d.public_label ?? "").toUpperCase()}</Badge>
                  </span>
                  <span className="mt-0.5 block text-[11.5px] text-[color:var(--nx-muted)]">
                    {d.coverage.start.slice(0, 4)}–{d.coverage.end.slice(0, 4)} · {d.observation_count} obs. · {d.resolution_m} m · {((d.bbox[1] + d.bbox[3]) / 2).toFixed(2)}°, {((d.bbox[0] + d.bbox[2]) / 2).toFixed(2)}°
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <Card title={cur ? cur.name : "Dataset record"} subtitle={cur ? cur.id : "Select a dataset to see its record"} testid="dataset-record" right={cur ? <Badge tone={isOfficial(cur) ? "official" : "illustrative"}>{(cur.public_label ?? "").toUpperCase()}</Badge> : null}>
          {!cur ? (
            <p className="py-8 text-center text-[13px] text-[color:var(--nx-muted)]">
              <FileText className="mx-auto mb-2 h-6 w-6" aria-hidden />
              Choose a dataset on the left.
            </p>
          ) : (
            <>
              <div className="mb-4 flex flex-wrap gap-2">
                <button type="button" className="nx-btn" disabled={!st} onClick={() => st && download(`${cur.id}_observations.csv`, observationsCsv(st))}><Download className="h-4 w-4" aria-hidden /> Observations CSV</button>
                <button type="button" className="nx-chip" disabled={!st} onClick={() => st && download(`${cur.id}_series.csv`, seriesCsv(st))}><Download className="h-3.5 w-3.5" aria-hidden /> Time series CSV</button>
                <button type="button" className="nx-chip" onClick={() => download(`${cur.id}_metadata.csv`, metadataCsv(cur, st))}><Download className="h-3.5 w-3.5" aria-hidden /> Metadata CSV</button>
              </div>
              <dl className="divide-y divide-[color:var(--nx-line)] text-[13px]">
                {metadataRecord(cur, st).map(([k, v]) => (
                  <div key={k} className="grid grid-cols-[190px_1fr] gap-3 py-1.5">
                    <dt className="text-[color:var(--nx-muted)]">{k}</dt>
                    <dd className="break-words">{v || "n/a"}</dd>
                  </div>
                ))}
              </dl>
              {st ? (
                <div className="mt-5 overflow-x-auto">
                  <h3 className="mb-1.5 text-[13px] font-semibold">Observations ({st.observations.length})</h3>
                  <table className="w-full text-left text-[12.5px]">
                    <thead className="text-[11px] uppercase tracking-wider text-[color:var(--nx-muted)]">
                      <tr><th className="py-1 pr-3">Date</th><th className="px-3">Quality</th><th className="px-3">Valid</th><th className="px-3">Footprint (ha)</th><th className="pl-3">Classes</th></tr>
                    </thead>
                    <tbody>
                      {st.observations.map((o) => (
                        <tr key={o.date} className="border-t border-[color:var(--nx-line)]">
                          <td className="py-1 pr-3 tabular-nums">{o.date}</td>
                          <td className="px-3">{o.quality}</td>
                          <td className="px-3 tabular-nums">{(o.valid_fraction * 100).toFixed(1)}%</td>
                          <td className="px-3 tabular-nums">{o.footprint_ha.toFixed(0)}</td>
                          <td className="pl-3 tabular-nums">{Object.keys(o.class_area_ha).length}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Loading what="observations" />
              )}
              <Note>Files are generated in your browser from the dataset as served by this application. The designation above states how the data was produced and is reproduced unchanged in every export.</Note>
            </>
          )}
        </Card>
      </div>
    </>
  );
}
