"use client";

import { useEffect, useState } from "react";
import { analyticsApi, isOfficial, type CatalogueRow, type DeepSource, type SourceEntry } from "@/lib/explorer/analytics";
import { deepApi } from "@/lib/explorer/deeptime";
import { toApiError } from "@/lib/api";
import { Badge, Card, ErrorBox, Loading, PageTitle } from "@/components/analytics/ui";

interface Ref {
  [k: string]: unknown;
}

const Link = ({ href, children }: { href: string; children: React.ReactNode }) =>
  /^https?:\/\//.test(href) ? (
    <a href={href} target="_blank" rel="noreferrer noopener" className="text-sky-800 underline-offset-2 hover:underline">
      {children}
    </a>
  ) : (
    <>{children}</>
  );

export function DataMethodsView() {
  const [cat, setCat] = useState<CatalogueRow[] | null>(null);
  const [reg, setReg] = useState<SourceEntry[] | null>(null);
  const [deep, setDeep] = useState<DeepSource[] | null>(null);
  const [refs, setRefs] = useState<Ref[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    Promise.all([
      analyticsApi.catalogue(ac.signal).then((c) => setCat(c.datasets)),
      analyticsApi.registry(ac.signal).then((r) => setReg(r.entries)),
      analyticsApi.deepSources(ac.signal).then(setDeep).catch(() => setDeep([])),
      deepApi.references(ac.signal).then((r) => setRefs(r as unknown as Ref[])).catch(() => setRefs([])),
    ]).catch((e) => {
      if (!ac.signal.aborted) setError(toApiError(e).message);
    });
    return () => ac.abort();
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!cat || !reg) return <Loading what="data catalogue" />;

  return (
    <>
      <PageTitle title="Data & Methods">
        Every dataset, where it came from, how it is labelled and how the numbers are computed.
      </PageTitle>

      <Card title="How data is labelled" className="mb-6" testid="labels">
        <div className="grid gap-3 md:grid-cols-2 text-[13px] leading-relaxed text-[color:var(--nx-soft)]">
          <div><Badge tone="official">SATELLITE OBSERVATIONS</Badge><p className="mt-2">Derived from public satellite products (GHSL, JRC Global Surface Water, ESA WorldCover). Values come from the original rasters, clipped to the study area.</p></div>
          <div><Badge tone="model">GEOLOGICAL RECONSTRUCTION</Badge><p className="mt-2">Plate-motion model output (EarthByte, PALEOMAP) with stated uncertainty. Positions are interpretations, and the two models can disagree by thousands of kilometres.</p></div>
        </div>
      </Card>

      <Card title="Dataset catalogue" subtitle={`${cat.length} datasets in the Earth Time Machine`} className="mb-6" testid="catalogue">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[12.5px]">
            <thead className="text-[11px] uppercase tracking-wider text-[color:var(--nx-muted)]">
              <tr><th className="py-1.5 pr-3">Dataset</th><th className="px-3">Label</th><th className="px-3">Coverage</th><th className="px-3">Obs.</th><th className="px-3">Pixel</th><th className="pl-3">Variables</th></tr>
            </thead>
            <tbody>
              {cat.map((d) => (
                <tr key={d.id} className="border-t border-[color:var(--nx-line)] align-top">
                  <td className="py-2 pr-3 font-medium">{d.name}<span className="block text-[11px] font-normal text-[color:var(--nx-muted)]">{d.source ?? ""}</span></td>
                  <td className="px-3"><Badge tone={isOfficial(d) ? "official" : "illustrative"}>{(d.public_label ?? (isOfficial(d) ? "Satellite Observations" : "Illustrative Dataset")).toUpperCase()}</Badge></td>
                  <td className="px-3 whitespace-nowrap tabular-nums">{d.coverage.start.slice(0, 4)}–{d.coverage.end.slice(0, 4)}</td>
                  <td className="px-3 tabular-nums">{d.observations}</td>
                  <td className="px-3 tabular-nums">{d.resolution_m ? `${d.resolution_m} m` : "n/a"}</td>
                  <td className="pl-3 text-[color:var(--nx-soft)]">{d.variables.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Source registry" subtitle={`${reg.length} source files with provider, licence and download location`} className="mb-6" testid="registry">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[12.5px]">
            <thead className="text-[11px] uppercase tracking-wider text-[color:var(--nx-muted)]">
              <tr><th className="py-1.5 pr-3">Variable</th><th className="px-3">Provider</th><th className="px-3">Identifier / coverage</th><th className="px-3">Licence</th><th className="pl-3">Used by</th></tr>
            </thead>
            <tbody>
              {reg.map((s) => (
                <tr key={s.id} className="border-t border-[color:var(--nx-line)] align-top">
                  <td className="py-2 pr-3 font-medium">{s.variable}<span className="block text-[11px] font-normal text-[color:var(--nx-muted)]">{s.original_file_format} · {s.spatial_resolution}</span></td>
                  <td className="px-3"><Link href={s.official_dataset_url}>{s.providing_organization}</Link></td>
                  <td className="px-3 text-[color:var(--nx-soft)]">{s.dataset_identifier}<span className="block text-[11px] text-[color:var(--nx-muted)]">{s.acquisition_or_temporal_coverage}</span></td>
                  <td className="px-3 text-[color:var(--nx-soft)]">{s.license_or_terms}</td>
                  <td className="pl-3 text-[color:var(--nx-soft)]">{(s.used_by_regions ?? []).join(", ") || "n/a"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {deep && deep.length ? (
        <Card title="Deep-time sources" subtitle="Plate-motion and paleogeography files, with checksums for verification" className="mb-6" testid="deep-sources">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[12.5px]">
              <thead className="text-[11px] uppercase tracking-wider text-[color:var(--nx-muted)]">
                <tr><th className="py-1.5 pr-3">File</th><th className="px-3">Provider / model</th><th className="px-3">Licence</th><th className="px-3">Downloaded</th><th className="pl-3">SHA-256</th></tr>
              </thead>
              <tbody>
                {deep.map((s) => (
                  <tr key={s.dataset_id} className="border-t border-[color:var(--nx-line)] align-top">
                    <td className="py-2 pr-3 font-medium"><Link href={s.source_url}>{s.original_filename}</Link><span className="block text-[11px] font-normal text-[color:var(--nx-muted)]">{s.processing_method}</span></td>
                    <td className="px-3 text-[color:var(--nx-soft)]">{s.provider}<span className="block text-[11px] text-[color:var(--nx-muted)]">{s.model_name}</span></td>
                    <td className="px-3 text-[color:var(--nx-soft)]">{s.license}</td>
                    <td className="px-3 whitespace-nowrap">{s.downloaded_date}</td>
                    <td className="pl-3 font-mono text-[11px] break-all text-[color:var(--nx-muted)]">{s.checksum ? `${s.checksum.slice(0, 16)}…` : "n/a"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {refs && refs.length ? (
        <Card title="References" className="mb-6" testid="references">
          <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-[color:var(--nx-soft)]">
            {refs.map((r, i) => (
              <li key={i}>{String(r.citation ?? r.title ?? r.name ?? JSON.stringify(r))}{typeof r.url === "string" ? <> · <Link href={r.url}>link</Link></> : null}</li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Card title="Methods and limits" testid="methods">
        <ul className="list-disc space-y-1.5 pl-5 text-[13px] leading-relaxed text-[color:var(--nx-soft)]">
          <li><b>Area:</b> pixel counts multiplied by pixel area for the dataset&apos;s projection, reported in hectares. Cloud and no-data pixels are excluded and the valid share is shown.</li>
          <li><b>Net change and rate:</b> last minus first observation, divided by the years between them. Compound rate assumes steady proportional change.</li>
          <li><b>Trend line:</b> ordinary least squares over the observation years with R². With three or more points a robust Theil-Sen slope is also shown. With few points these describe the data; they do not prove a trend.</li>
          <li><b>Change detection:</b> compares the first and last usable observation pixel by pixel, separates loss from gain, ignores uncertain pixels, and ranks connected patches as hotspots.</li>
          <li><b>Confidence:</b> from observation quality, valid fraction and period length. Low confidence is shown instead of hidden.</li>
          <li><b>Causes:</b> the app describes what changed and where. It does not establish why.</li>
          <li><b>Deep time:</b> two plate models are shown side by side so their disagreement stays visible. Fossil counts reflect what has been recorded and published, not how many animals lived.</li>
        </ul>
      </Card>
    </>
  );
}
