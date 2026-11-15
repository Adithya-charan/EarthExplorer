"use client";

import { BOUNDARY_NAME, cap, dataLabel, fmtDate, fmtHa, fmtPct, isIllustrative, levelName } from "@/lib/explorer/logic";
import type { BoundaryOut, ChangeSummary, DatasetInfo, LatestObservation, LocationOut } from "@/lib/explorer/types";

export interface DetailsProps {
  location: LocationOut | null;
  boundary: BoundaryOut | null;
  dataset: DatasetInfo | null;
  latest: LatestObservation | null;
  summary: ChangeSummary | null;
}

function Section({ title, rows, testId }: { title: string; rows: [string, string | null | undefined][]; testId: string }) {
  const shown = rows.filter(([, v]) => v != null && v !== "");
  if (shown.length === 0) return null;
  return (
    <section aria-label={title} data-testid={testId}>
      <h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-[color:var(--nx-muted)]">{title}</h3>
      <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 text-[12.5px]">
        {shown.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-[color:var(--nx-muted)]">{k}</dt>
            <dd className="leading-snug">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

const km = (v: number | null | undefined, approx: boolean) => (v == null ? null : `${approx ? "about " : ""}${v >= 100 ? v.toLocaleString("en-US", { maximumFractionDigits: 0 }) : v.toFixed(2)} km²`);

/** Every value here comes from an API response; nothing is computed or invented in the browser. */
export function DetailsPanel({ location: loc, boundary: b, dataset: ds, latest, summary: s }: DetailsProps) {
  const a = s?.areas ?? {};
  const label = s?.variable?.label ?? "water";
  const temporal = ds?.temporal_resolution ?? "monthly";
  const q = s?.quality ?? {};
  const unc = a.uncertain_ha != null && a.footprint_ha ? (100 * (a.uncertain_ha as number)) / (a.footprint_ha as number) : null;
  const measured = s != null && s.outcome !== "insufficient_data";
  const prov = (ds?.provenance ?? {}) as Record<string, unknown>;
  return (
    <div className="space-y-4" data-testid="details-panel">
      <Section
        testId="details-geo"
        title="Geographical information"
        rows={[
          ["Name", loc?.name],
          ["Type", loc ? levelName(loc.level) : null],
          ["Located in", loc && loc.hierarchy.length ? [...loc.hierarchy].reverse().join(", ") : null],
          ["Coordinates", loc ? `${loc.lat.toFixed(4)}°, ${loc.lon.toFixed(4)}°` : null],
          ["Area", b ? km(b.area_km2, b.area_is_approximate) : null],
          ["Boundary", b ? `${BOUNDARY_NAME[b.status] ?? b.status}${b.authoritative ? "" : " · not an authoritative boundary"}` : loc?.boundary_status ? (BOUNDARY_NAME[loc.boundary_status] ?? loc.boundary_status) : null],
          ["Outline source", b?.source],
          ["Note", b?.note],
        ]}
      />
      <Section
        testId="details-observation"
        title="Observation information"
        rows={[
          ["Data", ds ? dataLabel(ds) : "Data Unavailable"],
          ["Dataset", ds?.name],
          ["Provider", ds?.source],
          ["Product", ds?.product],
          ["Latest date", latest ? `${fmtDate(latest.date, latest.temporal_resolution)} (${latest.date})` : null],
          ["Resolution", ds ? `${ds.resolution_m.toFixed(0)} m per pixel · ${temporal}` : null],
          ["Availability", ds ? `${ds.usable_count} usable of ${ds.observation_count} observations, ${ds.coverage.start.slice(0, 4)}–${ds.coverage.end.slice(0, 4)}` : null],
          ["Date meaning", typeof prov.note === "string" ? prov.note : null],
        ]}
      />
      {measured ? (
        <Section
          testId="details-analysis"
          title="Historical analysis"
          rows={[
            ["Measured", cap(label)],
            ["Period", s?.period?.effective ? `${s.period.effective.start_year}–${s.period.effective.end_year}` : null],
            ["Initial", s?.first_observation ? `${fmtHa(a.water_start_ha as number | null)} on ${fmtDate(s.first_observation.date, temporal)}` : null],
            ["Latest", s?.last_observation ? `${fmtHa(a.water_end_ha as number | null)} on ${fmtDate(s.last_observation.date, temporal)}` : null],
            ["Net change", `${fmtHa(a.net_ha as number | null)} (${fmtPct(a.pct_net_change as number | null)})`],
            ["Lost / gained", `${fmtHa(a.lost_ha as number | null)} lost · ${fmtHa(a.gained_ha as number | null)} gained`],
            ["Hotspots", s ? `${s.hotspots.length} identified${s.most_affected ? `; largest: ${s.most_affected.description}` : ""}` : null],
          ]}
        />
      ) : (
        <Section testId="details-analysis" title="Historical analysis" rows={[["Result", s?.insufficient?.reason ?? s?.headline ?? "No historical analysis is available for this place."]]} />
      )}
      <Section
        testId="details-quality"
        title="Data quality"
        rows={[
          ["Quality", latest ? `${latest.quality} · ${(latest.valid_fraction * 100).toFixed(0)}% valid pixels` : null],
          ["Cloud / no data", unc != null ? `${unc.toFixed(1)}% of the area excluded` : q.mean_valid_fraction != null ? `${((1 - q.mean_valid_fraction) * 100).toFixed(1)}% on average` : null],
          ["Confidence", s?.confidence ? cap(s.confidence) : null],
          ["Method", s?.what_was_analysed],
        ]}
      />
      {s?.limitations?.length ? (
        <section aria-label="Limitations" data-testid="details-limitations">
          <h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-[color:var(--nx-muted)]">Limitations</h3>
          <ul className="list-disc space-y-1 pl-5 text-[12px] text-[color:var(--nx-muted)]">
            {s.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {isIllustrative(ds) ? <p className="rounded-md border border-amber-400/40 bg-amber-400/10 px-2 py-1 text-[11.5px] font-semibold text-amber-200">Illustrative Dataset: a generated demonstration layer, not satellite imagery.</p> : null}
    </div>
  );
}
