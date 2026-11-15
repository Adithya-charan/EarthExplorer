"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Loader2, Sparkles } from "lucide-react";
import { explorerApi } from "@/lib/explorer/api";
import { analyticsApi, changeMetrics, decimalYear, fmtNum, fmtSigned, indexSeries, isOfficial, primaryVariable, shortClass, type CatalogueRow, type DatasetStats } from "@/lib/explorer/analytics";
import type { ChangeSummary, Explanation } from "@/lib/explorer/types";
import { toApiError } from "@/lib/api";
import { Badge, C, Card, ErrorBox, Kpi, Loading, Note, PageTitle, axisProps, tooltipStyle } from "@/components/analytics/ui";

const yearOf = (iso: string) => Number(iso.slice(0, 4));

function Designation({ row }: { row: Pick<CatalogueRow, "designation" | "public_label"> }) {
  return <Badge tone={isOfficial(row) ? "official" : "illustrative"}>{(row.public_label ?? (isOfficial(row) ? "Satellite Observations" : "Illustrative Dataset")).toUpperCase()}</Badge>;
}

export function ChangeAnalyticsView() {
  const [rows, setRows] = useState<CatalogueRow[] | null>(null);
  const [stats, setStats] = useState<Record<string, DatasetStats>>({});
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [variable, setVariable] = useState<string | null>(null);

  const [tick, setTick] = useState(0);
  const load = useCallback(() => {
    setError(null);
    setTick((t) => t + 1);
  }, []);
  useEffect(() => {
    let live = true;
    analyticsApi
      .catalogue()
      .then(async (c) => {
        const all = await Promise.all(c.datasets.map((d) => analyticsApi.stats(d.id).catch(() => null)));
        if (!live) return;
        const m: Record<string, DatasetStats> = {};
        all.forEach((s) => s && (m[s.dataset_id] = s));
        setRows(c.datasets);
        setStats(m);
        setSel((cur) => cur ?? c.datasets.find((d) => (m[d.id] ? Object.values(m[d.id].variables).some((v) => v.series.length > 2) : false))?.id ?? c.datasets[0]?.id ?? null);
      })
      .catch((e) => live && setError(toApiError(e).message));
    return () => {
      live = false;
    };
  }, [tick]);

  const current = sel ? stats[sel] : undefined;
  const currentRow = rows?.find((r) => r.id === sel);
  const varKey = useMemo(() => {
    if (!current) return null;
    if (variable && current.variables[variable]) return variable;
    return primaryVariable(current)?.[0] ?? null;
  }, [current, variable]);

  // ---------------------------------------------------------------------------- cross-dataset overview
  const overview = useMemo(() => {
    if (!rows) return [];
    return rows
      .map((r) => {
        const s = stats[r.id];
        const pv = s ? primaryVariable(s) : null;
        const m = pv ? changeMetrics(pv[1].series) : null;
        return { row: r, label: pv?.[1].label ?? "", m, snapshots: pv ? pv[1].series.length : 0 };
      })
      .sort((a, b) => (b.m?.netPct ?? -1e9) - (a.m?.netPct ?? -1e9));
  }, [rows, stats]);
  const bars = overview.filter((o) => o.m?.netPct != null).map((o) => ({ id: o.row.id, name: `${o.row.name.replace(/\s*\(.*\)$/, "")} · ${o.label}${isOfficial(o.row) ? "" : " (sim.)"}`, pct: Number(o.m!.netPct!.toFixed(1)), official: isOfficial(o.row), label: o.label }));

  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (!rows) return <Loading what="datasets" />;

  return (
    <>
      <PageTitle title="Change Analytics">
        How the places in the Earth Time Machine have changed. Every number is computed from the observation rasters of the dataset you pick. Datasets marked Illustrative are simulated for demonstration and are never mixed with Satellite Observations.
      </PageTitle>

      <Card title="Net change across all datasets" subtitle="Primary variable of each dataset, first to last observation. Datasets with one observation have no change to measure." testid="overview" className="mb-6">
        <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
          <div className="h-[320px]" role="img" aria-label="Bar chart of net change in percent for each dataset">
            <ResponsiveContainer>
              <BarChart data={bars} layout="vertical" margin={{ left: 8, right: 24 }}>
                <CartesianGrid stroke={C.grid} horizontal={false} />
                <XAxis type="number" {...axisProps} unit="%" />
                <YAxis type="category" dataKey="name" width={230} {...axisProps} />
                <Tooltip {...tooltipStyle} formatter={(v) => [`${fmtSigned(Number(v), 1, "%")}`, "Net change"]} cursor={{ fill: "rgba(255,255,255,0.05)" }} />
                <ReferenceLine x={0} stroke={C.muted} />
                <Bar dataKey="pct" radius={[0, 4, 4, 0]} onClick={(d) => setSel((d as unknown as { id: string }).id)} cursor="pointer">
                  {bars.map((b) => (
                    <Cell key={b.id} fill={b.pct < 0 ? C.loss : C.gain} fillOpacity={b.official ? 1 : 0.5} stroke={b.id === sel ? "#fff" : "none"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <p className="sr-only">Solid bars are Satellite Observations; faded bars are Illustrative Datasets.</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[12.5px]">
              <thead className="text-[11px] uppercase tracking-wider text-[color:var(--nx-muted)]">
                <tr>
                  <th className="py-1.5 pr-2">Dataset</th>
                  <th className="px-2">Obs.</th>
                  <th className="px-2 text-right">Net</th>
                  <th className="pl-2 text-right">ha / yr</th>
                </tr>
              </thead>
              <tbody>
                {overview.map((o) => (
                  <tr key={o.row.id} className={`cursor-pointer border-t border-[color:var(--nx-line)] hover:bg-white/5 ${o.row.id === sel ? "bg-white/8" : ""}`} onClick={() => setSel(o.row.id)}>
                    <td className="py-1.5 pr-2">
                      <button type="button" className="text-left font-medium hover:underline" onClick={() => setSel(o.row.id)}>
                        {o.row.name.replace(/\s*\(.*\)$/, "")}
                      </button>
                      <div className="mt-0.5">
                        <Designation row={o.row} />
                      </div>
                    </td>
                    <td className="px-2 tabular-nums">{o.snapshots}</td>
                    <td className={`px-2 text-right tabular-nums ${o.m?.netPct == null ? "" : o.m.netPct < 0 ? "text-[color:var(--nx-loss)]" : "text-[color:var(--nx-gain)]"}`}>{o.m ? fmtSigned(o.m.netPct, 1, "%") : "snapshot"}</td>
                    <td className="pl-2 text-right tabular-nums">{o.m ? fmtSigned(o.m.haPerYear, 1) : "n/a"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Card>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-[13px]">
          <span className="text-[color:var(--nx-muted)]">Dataset</span>
          <select className="nx-input max-w-[min(520px,80vw)]" value={sel ?? ""} onChange={(e) => { setSel(e.target.value); setVariable(null); }} aria-label="Dataset">
            <optgroup label="Satellite Observations (official-derived)">
              {rows.filter(isOfficial).map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </optgroup>
            <optgroup label="Illustrative Datasets (simulated)">
              {rows.filter((r) => !isOfficial(r)).map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </optgroup>
          </select>
        </label>
        {currentRow ? <Designation row={currentRow} /> : null}
        {currentRow ? <span className="text-[12.5px] text-[color:var(--nx-muted)]">{currentRow.observations} observation(s) · {currentRow.temporal_resolution} · {currentRow.resolution_m ? `${currentRow.resolution_m} m pixels` : ""}</span> : null}
      </div>

      {!current ? <Loading what="statistics" /> : <DatasetDetail stats={current} varKey={varKey} onVar={setVariable} row={currentRow} />}
    </>
  );
}

// ------------------------------------------------------------------------------------------------ one dataset
function DatasetDetail({ stats, varKey, onVar, row }: { stats: DatasetStats; varKey: string | null; onVar: (k: string) => void; row?: CatalogueRow }) {
  const v = varKey ? stats.variables[varKey] : null;
  const m = useMemo(() => (v ? changeMetrics(v.series) : null), [v]);
  const series = useMemo(() => {
    if (!v) return [];
    const pts = [...v.series].sort((a, b) => a.date.localeCompare(b.date)).map((p) => ({ year: Number(decimalYear(p.date).toFixed(2)), area: p.area_ha, share: p.share_of_valid_pct, trend: undefined as number | undefined }));
    if (m?.fit) for (const p of pts) p.trend = Number((m.fit.intercept + m.fit.slope * p.year).toFixed(2));
    return pts;
  }, [v, m]);
  const idx = useMemo(() => indexSeries(stats.variables), [stats]);
  const comp = useMemo(() => {
    const totals: Record<string, number> = {};
    for (const o of stats.observations) for (const [k, a] of Object.entries(o.class_area_ha)) totals[k] = Math.max(totals[k] ?? 0, a);
    const top = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, 7).map(([k]) => k);
    const keys = [...top.map(shortClass), "Other classes"];
    const rows = stats.observations.map((o) => {
      const r: Record<string, number | string> = { year: String(yearOf(o.date)) };
      let other = 0;
      for (const [k, a] of Object.entries(o.class_area_ha)) {
        if (top.includes(k)) r[shortClass(k)] = Number(a.toFixed(1));
        else other += a;
      }
      r["Other classes"] = Number(other.toFixed(1));
      return r;
    });
    return { keys, rows };
  }, [stats]);
  const quality = stats.observations.map((o) => ({ year: String(yearOf(o.date)), valid: Number((o.valid_fraction * 100).toFixed(1)), nodata: Number(o.nodata_pct.toFixed(1)), q: o.quality }));
  const single = !m;

  return (
    <>
      {stats.designation === "illustrative" ? <p className="mb-4 rounded-lg border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-[12.5px] text-amber-200">Illustrative Dataset: simulated for demonstration. These numbers are not satellite observations and must not be quoted as findings about the real place.</p> : null}

      {Object.keys(stats.variables).length > 1 ? (
        <div className="mb-4 flex flex-wrap gap-2" role="tablist" aria-label="Variable">
          {Object.entries(stats.variables).map(([k, x]) => (
            <button key={k} type="button" role="tab" aria-selected={k === varKey} onClick={() => onVar(k)} className={`nx-chip ${k === varKey ? "!bg-white/20 font-semibold" : ""}`}>
              {x.label}
            </button>
          ))}
        </div>
      ) : null}

      {v ? (
        <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="kpis">
          <Kpi label={`${v.label}, first`} value={`${fmtNum(v.series[0].area_ha, 1)} ha`} hint={`${yearOf(v.series[0].date)} · ${fmtNum(v.series[0].share_of_valid_pct, 1)}% of valid area`} />
          <Kpi label={`${v.label}, last`} value={`${fmtNum(v.series[v.series.length - 1].area_ha, 1)} ha`} hint={`${yearOf(v.series[v.series.length - 1].date)} · ${fmtNum(v.series[v.series.length - 1].share_of_valid_pct, 1)}% of valid area`} />
          <Kpi label="Net change" value={m ? `${fmtSigned(m.netHa, 1)} ha` : "single snapshot"} tone={m ? (m.netHa < 0 ? "loss" : "gain") : undefined} hint={m ? `${fmtSigned(m.netPct, 1, "%")} · ${fmtSigned(m.shareChangePts, 1)} share points` : "Only one observation: change cannot be measured."} />
          <Kpi label="Rate" value={m ? `${fmtSigned(m.haPerYear, 1)} ha/yr` : "n/a"} hint={m ? `${fmtNum(m.years, 1)} years${m.cagrPct != null ? ` · compound ${fmtSigned(m.cagrPct, 2, "%")}/yr` : ""}` : undefined} />
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={v ? `${v.label}: area over time` : "Area over time"} subtitle={m?.fit ? `Dashed line: least-squares trend (${fmtSigned(m.fit.slope, 2)} ha/yr, R² ${m.fit.r2.toFixed(2)}, n = ${m.fit.n}${m.fit.theilSen != null ? `; Theil-Sen ${fmtSigned(m.fit.theilSen, 2)} ha/yr` : ""})` : undefined} testid="chart-area">
          {single ? (
            <p className="py-10 text-center text-[13px] text-[color:var(--nx-muted)]">This dataset holds one observation, so there is no time series. Its composition is shown below.</p>
          ) : (
            <div className="h-[300px]" role="img" aria-label="Area of the selected variable over time">
              <ResponsiveContainer>
                <ComposedChart data={series} margin={{ left: 4, right: 12, top: 8 }}>
                  <CartesianGrid stroke={C.grid} />
                  <XAxis dataKey="year" type="number" domain={["dataMin - 1", "dataMax + 1"]} {...axisProps} tickFormatter={(x) => String(Math.round(x))} />
                  <YAxis {...axisProps} width={64} tickFormatter={(x) => fmtNum(x)} label={{ value: "hectares", angle: -90, position: "insideLeft", fill: C.muted, fontSize: 11 }} />
                  <Tooltip {...tooltipStyle} formatter={(val, name) => [`${fmtNum(Number(val), 1)} ha`, name === "trend" ? "Linear trend" : "Observed"]} labelFormatter={(l) => `Year ${l}`} />
                  <Line dataKey="area" name="area" stroke={C.accent} strokeWidth={2.5} dot={{ r: 4, fill: C.accent }} isAnimationActive={false} />
                  {m?.fit ? <Line dataKey="trend" name="trend" stroke={C.warn} strokeDasharray="6 4" dot={false} isAnimationActive={false} /> : null}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
          {m && m.fit && m.fit.n < 5 ? <Note>Only {m.fit.n} observations: the trend line is a description of these points, not a statistical test.</Note> : null}
        </Card>

        <Card title="Share of the valid area" subtitle="Percent of non-cloud, non-nodata pixels in this class" testid="chart-share">
          {single ? (
            <p className="py-10 text-center text-[13px] text-[color:var(--nx-muted)]">{v ? `${fmtNum(v.series[0].share_of_valid_pct, 1)}% of the valid area in ${yearOf(v.series[0].date)}.` : ""}</p>
          ) : (
            <div className="h-[300px]" role="img" aria-label="Share of valid area over time">
              <ResponsiveContainer>
                <LineChart data={series} margin={{ left: 4, right: 12, top: 8 }}>
                  <CartesianGrid stroke={C.grid} />
                  <XAxis dataKey="year" type="number" domain={["dataMin - 1", "dataMax + 1"]} {...axisProps} tickFormatter={(x) => String(Math.round(x))} />
                  <YAxis {...axisProps} width={52} unit="%" domain={[0, "auto"]} />
                  <Tooltip {...tooltipStyle} formatter={(val) => [`${fmtNum(Number(val), 2)}%`, "Share"]} labelFormatter={(l) => `Year ${l}`} />
                  <Line dataKey="share" stroke={C.gain} strokeWidth={2.5} dot={{ r: 4, fill: C.gain }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card title="Land-cover composition per observation" subtitle="All classes in the footprint, in hectares" testid="chart-composition">
          <div className="h-[320px]" role="img" aria-label="Stacked bars of land-cover composition per observation">
            <ResponsiveContainer>
              <BarChart data={comp.rows} margin={{ left: 4, right: 12, top: 8 }}>
                <CartesianGrid stroke={C.grid} vertical={false} />
                <XAxis dataKey="year" {...axisProps} />
                <YAxis {...axisProps} width={64} tickFormatter={(x) => fmtNum(x)} />
                <Tooltip {...tooltipStyle} formatter={(val, name) => [`${fmtNum(Number(val), 1)} ha`, String(name)]} cursor={{ fill: "rgba(255,255,255,0.05)" }} />
                <Legend wrapperStyle={{ fontSize: 11, color: C.soft }} />
                {comp.keys.map((k, i) => (
                  <Bar key={k} dataKey={k} stackId="a" fill={C.series[i % C.series.length]} isAnimationActive={false} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        {idx.keys.length >= 2 ? (
          <Card title="Variables compared (first observation = 100)" subtitle="Scales every variable to its own start so large and small classes can be compared" testid="chart-index">
            <div className="h-[320px]" role="img" aria-label="Indexed change of every variable">
              <ResponsiveContainer>
                <LineChart data={idx.rows} margin={{ left: 4, right: 12, top: 8 }}>
                  <CartesianGrid stroke={C.grid} />
                  <XAxis dataKey="year" type="number" domain={["dataMin - 1", "dataMax + 1"]} {...axisProps} tickFormatter={(x) => String(Math.round(x))} />
                  <YAxis {...axisProps} width={48} />
                  <Tooltip {...tooltipStyle} />
                  <Legend wrapperStyle={{ fontSize: 11, color: C.soft }} />
                  <ReferenceLine y={100} stroke={C.muted} strokeDasharray="3 3" />
                  {idx.keys.map((k, i) => (
                    <Line key={k} dataKey={k} name={stats.variables[k].label} stroke={C.series[i % C.series.length]} strokeWidth={2.2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
        ) : (
          <Card title="Observation quality" subtitle="Valid and no-data share of every observation" testid="chart-quality">
            <QualityChart data={quality} />
          </Card>
        )}
      </div>

      {idx.keys.length >= 2 ? (
        <Card title="Observation quality" subtitle="Valid and no-data share of every observation" className="mt-6" testid="chart-quality">
          <QualityChart data={quality} />
        </Card>
      ) : null}

      {row ? <DetectionPanel key={`${row.id}:${varKey}`} row={row}stats={stats} varKey={varKey} /> : null}
      <Note>Method: {stats.method}</Note>
    </>
  );
}

function QualityChart({ data }: { data: { year: string; valid: number; nodata: number; q: string }[] }) {
  return (
    <div className="h-[200px]" role="img" aria-label="Valid and no-data percentage per observation">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ left: 4, right: 12, top: 8 }}>
          <CartesianGrid stroke={C.grid} vertical={false} />
          <XAxis dataKey="year" {...axisProps} />
          <YAxis {...axisProps} width={44} unit="%" domain={[0, 100]} />
          <Tooltip {...tooltipStyle} formatter={(val, name) => [`${val}%`, name === "valid" ? "Valid pixels" : "No data / cloud"]} cursor={{ fill: "rgba(255,255,255,0.05)" }} />
          <Bar dataKey="valid" stackId="q" fill={C.gain} isAnimationActive={false} />
          <Bar dataKey="nodata" stackId="q" fill={C.loss} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ change detection
function DetectionPanel({ row, stats, varKey }: { row: CatalogueRow; stats: DatasetStats; varKey: string | null }) {
  const years = useMemo(() => [...new Set(stats.observations.map((o) => yearOf(o.date)))].sort((a, b) => a - b), [stats]);
  const [start, setStart] = useState(years[0]);
  const [end, setEnd] = useState(years[years.length - 1]);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<ChangeSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [expl, setExpl] = useState<Explanation | null>(null);
  const [explBusy, setExplBusy] = useState(false);

  if (years.length < 2) {
    return (
      <Card title="Change detection" className="mt-6">
        <p className="text-[13px] text-[color:var(--nx-muted)]">A period needs at least two observations. This dataset has one, so no before/after comparison is offered.</p>
      </Card>
    );
  }

  const run = async () => {
    setBusy(true);
    setErr(null);
    setExpl(null);
    try {
      setRes(await explorerApi.detect({ dataset_id: row.id, start_year: start, end_year: end, params: varKey ? { variable: varKey } : undefined }));
    } catch (e) {
      setRes(null);
      setErr(toApiError(e).message);
    } finally {
      setBusy(false);
    }
  };
  const explain = async () => {
    if (!res?.analysis_id) return;
    setExplBusy(true);
    try {
      setExpl(await explorerApi.explain(res.analysis_id));
    } catch (e) {
      setErr(toApiError(e).message);
    } finally {
      setExplBusy(false);
    }
  };
  const a = res?.areas ?? {};
  const tone = res?.outcome === "change_detected" ? "text-emerald-200" : "text-[color:var(--nx-soft)]";

  return (
    <Card title="Change detection between two years" subtitle="Compares the first and last observation in the chosen period and finds where the change happened" className="mt-6" testid="detection">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-[12.5px]">
          <span className="mb-1 block text-[color:var(--nx-muted)]">From</span>
          <select className="nx-input" value={start} onChange={(e) => setStart(Number(e.target.value))} aria-label="From year">
            {years.map((y) => <option key={y}>{y}</option>)}
          </select>
        </label>
        <label className="text-[12.5px]">
          <span className="mb-1 block text-[color:var(--nx-muted)]">To</span>
          <select className="nx-input" value={end} onChange={(e) => setEnd(Number(e.target.value))} aria-label="To year">
            {years.map((y) => <option key={y}>{y}</option>)}
          </select>
        </label>
        <button type="button" className="nx-btn" onClick={run} disabled={busy || start >= end} data-testid="run-detect">
          {busy ? <Loader2 className="nx-spin h-4 w-4" aria-hidden /> : null} Analyse change
        </button>
        {start >= end ? <span className="text-[12px] text-amber-200">Pick a start year before the end year.</span> : null}
      </div>
      {err ? <div className="mt-4"><ErrorBox message={err} /></div> : null}
      {res ? (
        <div className="mt-5" data-testid="detect-result">
          <p className={`text-[15px] font-semibold ${tone}`}>{res.headline}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge tone={res.outcome === "change_detected" ? "official" : "info"}>{res.outcome.replace(/_/g, " ").toUpperCase()}</Badge>
            {res.confidence ? <Badge tone={res.confidence === "high" ? "official" : res.confidence === "medium" ? "warn" : "illustrative"}>{res.confidence.toUpperCase()} CONFIDENCE</Badge> : null}
          </div>
          {res.outcome !== "insufficient_data" ? (
            <>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <Kpi label="Lost" value={`${fmtNum(a.lost_ha as number, 1)} ha`} tone="loss" />
                <Kpi label="Gained" value={`${fmtNum(a.gained_ha as number, 1)} ha`} tone="gain" />
                <Kpi label="Net" value={`${fmtSigned(a.net_ha as number, 1)} ha`} tone={(a.net_ha as number) < 0 ? "loss" : "gain"} hint={a.pct_net_change != null ? fmtSigned(a.pct_net_change as number, 1, "%") : undefined} />
                <Kpi label="Gross change" value={a.pct_gross_change != null ? `${fmtNum(a.pct_gross_change as number, 1)}%` : "n/a"} hint="lost + gained, as a share of the start" />
                <Kpi label="Unchanged" value={`${fmtNum(((a.unchanged_water_ha as number) ?? 0) + ((a.unchanged_land_ha as number) ?? 0), 0)} ha`} hint={a.uncertain_ha ? `${fmtNum(a.uncertain_ha as number, 1)} ha uncertain` : "no uncertain area"} />
              </div>
              <div className="mt-5 grid gap-6 lg:grid-cols-2">
                {res.hotspots.length ? (
                  <div data-testid="chart-hotspots">
                    <h3 className="mb-2 text-[13.5px] font-semibold">Where the change happened (hotspots by area)</h3>
                    <div className="h-[240px]" role="img" aria-label="Bar chart of change hotspots by area">
                      <ResponsiveContainer>
                        <BarChart data={[...res.hotspots].sort((a, b) => b.area_ha - a.area_ha).slice(0, 8).map((h, i) => ({ name: `${i + 1}. ${h.region}`, ha: h.area_ha, kind: h.kind, share: h.share_of_change_pct }))} layout="vertical" margin={{ left: 8, right: 16 }}>
                          <CartesianGrid stroke={C.grid} horizontal={false} />
                          <XAxis type="number" {...axisProps} />
                          <YAxis type="category" dataKey="name" width={130} {...axisProps} />
                          <Tooltip {...tooltipStyle} formatter={(val, _n, p) => [`${fmtNum(Number(val), 1)} ha (${p.payload.share}% of all change)`, p.payload.kind === "loss" ? "Loss" : "Gain"]} cursor={{ fill: "rgba(255,255,255,0.05)" }} />
                          <Bar dataKey="ha" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                            {res.hotspots.map((h) => <Cell key={h.id} fill={h.kind === "loss" ? C.loss : C.gain} />)}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    <ul className="mt-2 space-y-1 text-[12px] text-[color:var(--nx-soft)]">
                      {res.hotspots.slice(0, 3).map((h) => <li key={h.id}>{h.description}</li>)}
                    </ul>
                  </div>
                ) : null}
                {res.progression.length > 1 ? (
                  <div data-testid="chart-progression">
                    <h3 className="mb-2 text-[13.5px] font-semibold">Progression through the period</h3>
                    <div className="h-[240px]" role="img" aria-label="Area and cumulative loss and gain over the period">
                      <ResponsiveContainer>
                        <ComposedChart data={res.progression} margin={{ left: 4, right: 12 }}>
                          <CartesianGrid stroke={C.grid} />
                          <XAxis dataKey="year" {...axisProps} />
                          <YAxis {...axisProps} width={56} />
                          <Tooltip {...tooltipStyle} />
                          <Legend wrapperStyle={{ fontSize: 11, color: C.soft }} />
                          <Line dataKey="water_ha" name={`${res.variable?.label ?? "Area"} (ha)`} stroke={C.accent} strokeWidth={2.5} dot={{ r: 4 }} isAnimationActive={false} />
                          <Line dataKey="cumulative_loss_ha" name="Cumulative loss (ha)" stroke={C.loss} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
                          <Line dataKey="cumulative_gain_ha" name="Cumulative gain (ha)" stroke={C.gain} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
                        </ComposedChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                ) : null}
              </div>
              {res.trend ? (
                <p className="mt-4 rounded-lg border border-[color:var(--nx-line)] px-3 py-2 text-[12.5px] text-[color:var(--nx-soft)]" data-testid="trend-line">
                  Trend ({res.trend.method}): <b>{res.trend.direction}</b>, {fmtSigned(res.trend.slope_ha_per_year, 2)} ha per year over {res.trend.years} yearly values, p = {res.trend.p_value.toFixed(3)}. With so few values, treat p as a guide, not proof.
                </p>
              ) : null}
              <div className="mt-4 flex flex-wrap items-start gap-3">
                <button type="button" className="nx-chip" onClick={explain} disabled={explBusy || !res.analysis_id}>
                  {explBusy ? <Loader2 className="nx-spin h-3.5 w-3.5" aria-hidden /> : <Sparkles className="h-3.5 w-3.5" aria-hidden />} Explain in plain language
                </button>
                {expl ? (
                  <div className="min-w-[260px] flex-1 text-[13px] leading-relaxed text-[color:var(--nx-soft)]" data-testid="explanation">
                    <p className="whitespace-pre-wrap">{expl.text}</p>
                    <p className="mt-1 text-[11px] text-[color:var(--nx-muted)]">{expl.source === "groq" ? "AI wording over computed results" : "Rule-based wording of the computed results"}{expl.notice ? ` · ${expl.notice}` : ""}</p>
                  </div>
                ) : null}
              </div>
            </>
          ) : res.insufficient ? (
            <p className="mt-3 text-[13px] text-[color:var(--nx-soft)]">{res.insufficient.reason}</p>
          ) : null}
          {res.limitations.length ? (
            <details className="mt-4 text-[12.5px] text-[color:var(--nx-soft)]">
              <summary className="cursor-pointer font-medium">Limitations ({res.limitations.length})</summary>
              <ul className="mt-2 list-disc space-y-1 pl-5">{res.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
            </details>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
