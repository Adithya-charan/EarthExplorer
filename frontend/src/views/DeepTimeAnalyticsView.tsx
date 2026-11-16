"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { analyticsApi, fmtNum, type DeepAnalytics } from "@/lib/explorer/analytics";
import { toApiError } from "@/lib/api";
import { Badge, C, Card, ErrorBox, Kpi, Loading, Note, PageTitle, axisProps, tooltipStyle } from "@/components/analytics/ui";

const CLASS_COLOURS: Record<string, string> = { ocean: "#1d4ed8", shallow: "#38bdf8", marine: "#38bdf8", land: "#84cc16", mountain: "#a8a29e", ice: "#e0f2fe", coast: "#fbbf24" };
const classColour = (c: string | null) => {
  if (!c) return "#334155";
  const k = Object.keys(CLASS_COLOURS).find((x) => c.toLowerCase().includes(x));
  return k ? CLASS_COLOURS[k] : "#94a3b8";
};

export function DeepTimeAnalyticsView() {
  const [d, setD] = useState<DeepAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const load = useCallback(() => {
    setError(null);
    setTick((t) => t + 1);
  }, []);
  useEffect(() => {
    let live = true;
    analyticsApi.deep().then((x) => live && setD(x)).catch((e) => live && setError(toApiError(e).message));
    return () => {
      live = false;
    };
  }, [tick]);

  const track = useMemo(() => (d ? [...d.track].sort((a, b) => a.age_ma - b.age_ma) : []), [d]);
  const speed = useMemo(() => {
    if (!d) return [];
    const eb = d.speed.earthbyte ?? [];
    const pm = d.speed.paleomap ?? [];
    const keys = [...new Set([...eb, ...pm].map((s) => `${s.from_ma}-${s.to_ma}`))];
    return keys
      .map((k) => {
        const [from, to] = k.split("-").map(Number);
        return { seg: `${from}→${to}`, from, earthbyte: eb.find((s) => s.from_ma === from && s.to_ma === to)?.cm_per_year, paleomap: pm.find((s) => s.from_ma === from && s.to_ma === to)?.cm_per_year };
      })
      .sort((a, b) => b.from - a.from);
  }, [d]);

  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (!d) return <Loading what="deep-time analytics" />;
  const k = d.kpis;

  return (
    <>
      <PageTitle title="Deep-Time Analytics">
        Measurements derived from the Geological Reconstruction datasets: how far and how fast India moved, where two plate-motion models disagree, and what the fossil and formation records cover. These are model reconstructions with uncertainty, not observations.
      </PageTitle>

      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="deep-kpis">
        <Kpi label="India path length (EarthByte)" value={`${fmtNum(k.path_km.earthbyte)} km`} hint={`PALEOMAP: ${fmtNum(k.path_km.paleomap)} km`} />
        <Kpi label="Peak plate speed" value={`${fmtNum(k.peak_speed.earthbyte.cm_per_year, 1)} cm/yr`} hint={`EarthByte, ${k.peak_speed.earthbyte.from_ma}→${k.peak_speed.earthbyte.to_ma} Ma · PALEOMAP ${fmtNum(k.peak_speed.paleomap.cm_per_year, 1)}`} tone="warn" />
        <Kpi label="Largest model disagreement" value={`${fmtNum(k.max_models_disagree_km)} km`} hint="Between the two reconstructions' positions of India" tone="warn" />
        <Kpi label="Fossil records" value={fmtNum(k.fossil_records)} hint={`${k.birds} birds · ${k.formations} formations · ${k.events} events`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="India's latitude through time" subtitle="Centre of India under two plate-motion models. Shaded: the debated window for the India–Eurasia collision (about 65–35 Ma)" testid="chart-latitude">
          <div className="h-[320px]" role="img" aria-label="Latitude of India against age for two models">
            <ResponsiveContainer>
              <LineChart data={track} margin={{ left: 4, right: 12, top: 8 }}>
                <CartesianGrid stroke={C.grid} />
                <XAxis dataKey="age_ma" type="number" reversed domain={[0, "dataMax"]} {...axisProps} label={{ value: "Age (Ma)", position: "insideBottom", offset: -2, fill: C.muted, fontSize: 11 }} />
                <YAxis {...axisProps} width={48} unit="°" />
                <Tooltip {...tooltipStyle} formatter={(v, n) => [`${Number(v).toFixed(1)}°`, n === "eb_lat" ? "EarthByte" : "PALEOMAP"]} labelFormatter={(l) => `${l} Ma`} />
                <ReferenceArea x1={65} x2={35} fill={C.warn} fillOpacity={0.1} />
                <Legend formatter={(v) => (v === "eb_lat" ? "EarthByte" : "PALEOMAP")} wrapperStyle={{ fontSize: 11, color: C.soft }} />
                <Line dataKey="eb_lat" stroke={C.earthbyte} strokeWidth={2.4} dot={{ r: 2.5 }} connectNulls isAnimationActive={false} />
                <Line dataKey="pm_lat" stroke={C.paleomap} strokeWidth={2.4} dot={{ r: 2.5 }} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Distance from the Eurasian margin" subtitle="Gap between India and Eurasia in kilometres (smaller = closer to collision)" testid="chart-gap">
          <div className="h-[320px]" role="img" aria-label="Gap to Eurasia against age">
            <ResponsiveContainer>
              <LineChart data={track} margin={{ left: 4, right: 12, top: 8 }}>
                <CartesianGrid stroke={C.grid} />
                <XAxis dataKey="age_ma" type="number" reversed domain={[0, "dataMax"]} {...axisProps} />
                <YAxis {...axisProps} width={64} tickFormatter={(x) => fmtNum(x)} />
                <Tooltip {...tooltipStyle} formatter={(v, n) => [`${fmtNum(Number(v))} km`, n === "eb_gap_km" ? "EarthByte" : "PALEOMAP"]} labelFormatter={(l) => `${l} Ma`} />
                <ReferenceArea x1={65} x2={35} fill={C.warn} fillOpacity={0.1} />
                <Line dataKey="eb_gap_km" stroke={C.earthbyte} strokeWidth={2.4} dot={false} connectNulls isAnimationActive={false} />
                <Line dataKey="pm_gap_km" stroke={C.paleomap} strokeWidth={2.4} dot={false} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Plate speed by interval" subtitle="Speed of India between reconstruction ages (cm per year)" testid="chart-speed">
          <div className="h-[300px]" role="img" aria-label="Speed of India per age interval for two models">
            <ResponsiveContainer>
              <BarChart data={speed} margin={{ left: 4, right: 12, top: 8 }}>
                <CartesianGrid stroke={C.grid} vertical={false} />
                <XAxis dataKey="seg" {...axisProps} interval={0} angle={-35} textAnchor="end" height={54} />
                <YAxis {...axisProps} width={44} />
                <Tooltip {...tooltipStyle} formatter={(v, n) => [`${Number(v).toFixed(1)} cm/yr`, n === "earthbyte" ? "EarthByte" : "PALEOMAP"]} cursor={{ fill: "rgba(15,27,45,0.06)" }} />
                <Legend formatter={(v) => (v === "earthbyte" ? "EarthByte" : "PALEOMAP")} wrapperStyle={{ fontSize: 11, color: C.soft }} />
                <Bar dataKey="earthbyte" fill={C.earthbyte} isAnimationActive={false} />
                <Bar dataKey="paleomap" fill={C.paleomap} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Where the two models disagree" subtitle="Distance between the two reconstructions' positions of India at each age" testid="chart-disagree">
          <div className="h-[300px]" role="img" aria-label="Disagreement between models per age">
            <ResponsiveContainer>
              <BarChart data={track} margin={{ left: 4, right: 12, top: 8 }}>
                <CartesianGrid stroke={C.grid} vertical={false} />
                <XAxis dataKey="age_ma" {...axisProps} />
                <YAxis {...axisProps} width={56} tickFormatter={(x) => fmtNum(x)} />
                <Tooltip {...tooltipStyle} formatter={(v) => [`${fmtNum(Number(v))} km`, "Disagreement"]} labelFormatter={(l) => `${l} Ma`} cursor={{ fill: "rgba(15,27,45,0.06)" }} />
                <Bar dataKey="models_disagree_km" fill={C.violet} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <Note>Large bars mean the position of India at that age is uncertain; read the geography there as a range, not a point.</Note>
        </Card>

        <Card title="Fossil records by geological period" subtitle={`${d.fossils.by_period.reduce((a, b) => a + b.records, 0)} records in the dataset`} testid="chart-fossil-period">
          <HBar data={d.fossils.by_period.map((x) => ({ name: x.period, v: x.records }))} colour={C.orange} unit="records" />
        </Card>

        <Card title="Fossil records through time" subtitle="Records whose age range overlaps each 10-million-year bin. A record spanning several bins counts in each, so bars add up to more than the total." testid="chart-fossil-age">
          <div className="h-[260px]" role="img" aria-label="Fossil records per age bin">
            <ResponsiveContainer>
              <BarChart data={[...d.fossils.by_age].sort((a, b) => b.from_ma - a.from_ma).map((x) => ({ bin: `${x.to_ma}–${x.from_ma}`, records: x.records }))} margin={{ left: 4, right: 12, top: 8 }}>
                <CartesianGrid stroke={C.grid} vertical={false} />
                <XAxis dataKey="bin" {...axisProps} interval={0} angle={-35} textAnchor="end" height={50} />
                <YAxis {...axisProps} width={40} />
                <Tooltip {...tooltipStyle} formatter={(v) => [v, "Records"]} labelFormatter={(l) => `${l} Ma`} cursor={{ fill: "rgba(15,27,45,0.06)" }} />
                <Bar dataKey="records" fill={C.accent} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Fossil groups" subtitle="Reptilia is recorded at class level only; Aves are birds" testid="chart-fossil-group">
          <HBar data={d.fossils.by_group.map((x) => ({ name: x.group, v: x.records }))} colour={C.gain} unit="records" />
        </Card>

        <Card title="Where fossils were found (Indian states)" testid="chart-fossil-state">
          <HBar data={d.fossils.by_state.map((x) => ({ name: x.state, v: x.records }))} colour={C.violet} unit="records" />
        </Card>

        <Card title="Most recorded taxa" testid="chart-fossil-taxa">
          <HBar data={d.fossils.top_taxa.map((x) => ({ name: x.taxon, v: x.records }))} colour={C.warn} unit="records" />
        </Card>

        <Card title="Geological formations by period" testid="chart-formations">
          <HBar data={d.formations.by_period.map((x) => ({ name: x.period, v: x.formations }))} colour="#a8a29e" unit="formations" />
        </Card>
      </div>

      <Card title="What was here? Paleogeography of Indian cities" subtitle="Reconstructed setting of each city's present location (EarthByte-based context, one cell per age)" className="mt-6" testid="places-strip">
        <div className="space-y-3 overflow-x-auto">
          {d.places.map((p) => (
            <div key={p.id} className="flex items-center gap-3">
              <span className="w-24 shrink-0 text-[12.5px] font-medium">{p.name}</span>
              <div className="flex gap-[2px]" role="img" aria-label={`${p.name} setting through time`}>
                {[...p.series].sort((a, b) => b.age_ma - a.age_ma).map((s) => (
                  <div key={s.age_ma} title={`${s.age_ma} Ma: ${s.class ?? "no data"}`} className="h-6 w-5 rounded-[3px]" style={{ background: classColour(s.class) }} />
                ))}
              </div>
            </div>
          ))}
          <p className="pl-[108px] text-[11px] text-[color:var(--nx-muted)]">Oldest on the left, present day on the right. Hover a cell for its age and class.</p>
        </div>
      </Card>

      <Card title="Reconstructed events" subtitle="Each carries a confidence level and the evidence behind it" className="mt-6" testid="events">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[12.5px]">
            <thead className="text-[11px] uppercase tracking-wider text-[color:var(--nx-muted)]">
              <tr>
                <th className="py-1.5 pr-3">Event</th>
                <th className="px-3">Age (Ma)</th>
                <th className="px-3">Confidence</th>
                <th className="pl-3">Evidence and uncertainty</th>
              </tr>
            </thead>
            <tbody>
              {d.events.map((e) => (
                <tr key={e.event_id} className="border-t border-[color:var(--nx-line)] align-top">
                  <td className="py-2 pr-3 font-medium">{e.event_name}</td>
                  <td className="px-3 tabular-nums whitespace-nowrap">{e.start_age_ma === e.end_age_ma ? e.start_age_ma : `${e.start_age_ma}–${e.end_age_ma}`}</td>
                  <td className="px-3"><Badge tone={/high/i.test(e.confidence) ? "official" : /low/i.test(e.confidence) ? "illustrative" : "warn"}>{e.confidence.toUpperCase()}</Badge></td>
                  <td className="pl-3 text-[color:var(--nx-soft)]">{e.evidence_source}{e.uncertainty_notes ? <span className="block text-[color:var(--nx-muted)]">{e.uncertainty_notes}</span> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Note>{d.note}</Note>
    </>
  );
}

function HBar({ data, colour, unit }: { data: { name: string; v: number }[]; colour: string; unit: string }) {
  const rows = data.slice(0, 12);
  return (
    <div style={{ height: Math.max(180, rows.length * 28 + 30) }} role="img" aria-label={`Bar chart of ${unit}`}>
      <ResponsiveContainer>
        <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 24 }}>
          <CartesianGrid stroke={C.grid} horizontal={false} />
          <XAxis type="number" {...axisProps} allowDecimals={false} />
          <YAxis type="category" dataKey="name" width={130} {...axisProps} interval={0} />
          <Tooltip {...tooltipStyle} formatter={(v) => [v, unit]} cursor={{ fill: "rgba(15,27,45,0.06)" }} />
          <Bar dataKey="v" radius={[0, 4, 4, 0]} isAnimationActive={false}>
            {rows.map((r) => <Cell key={r.name} fill={colour} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
