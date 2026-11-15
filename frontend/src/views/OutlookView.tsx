"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { analyticsApi, fmtNum, type CatalogueRow, type Projection } from "@/lib/explorer/analytics";
import { API_BASE, toApiError } from "@/lib/api";
import { axisProps, Badge, C, Card, ErrorBox, Loading, Note, tooltipStyle } from "@/components/analytics/ui";

const AHEAD = [10, 20, 30];
const QUICK = ["ghsl-built-up-chennai", "ghsl-built-up-delhi-ncr", "ghsl-built-up-pune", "ghsl-built-up-kolkata", "ghsl-built-up-hyderabad", "jrc-water-chilika-lake"];

/** Eases a number toward its target so the headline figures roll instead of jumping. */
function useCountUp(target: number, ms = 700): number {
  const [v, setV] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const start = from.current;
    const t0 = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / ms);
      const e = 1 - Math.pow(1 - k, 3);
      const cur = start + (target - start) * e;
      from.current = cur;
      setV(cur);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

export function OutlookView() {
  const [rows, setRows] = useState<CatalogueRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [id, setId] = useState("ghsl-built-up-chennai");
  const [ahead, setAhead] = useState(20);
  const [pick, setPick] = useState<number | null>(null);
  const [split, setSplit] = useState(50);
  const [playing, setPlaying] = useState(false);
  const [res, setRes] = useState<{ key: string; p: Projection } | null>(null);

  useEffect(() => {
    let live = true;
    analyticsApi.catalogue().then((r) => live && setRows(r.datasets.filter((d) => d.observations >= 2))).catch((e) => live && setError(toApiError(e).message));
    return () => {
      live = false;
    };
  }, []);
  const endDate = (rows?.find((r) => r.id === id)?.coverage.end ?? "2020-01-01").slice(0, 10);
  const lastYear = Number(endDate.slice(0, 4));
  const horizon = Math.min(2100, Math.max(2025, lastYear + ahead));
  const key = `${id}|${horizon}`;
  useEffect(() => {
    let live = true;
    analyticsApi.projection(id, horizon).then((p) => live && setRes({ key: `${id}|${horizon}`, p })).catch(() => {});
    return () => {
      live = false;
    };
  }, [id, horizon]);

  const steps = useMemo(() => {
    const s: number[] = [];
    for (let y = 0; y <= ahead; y += 5) s.push(y);
    return s;
  }, [ahead]);
  const step = Math.min(pick ?? ahead, ahead);

  // Play: walk the scrubber from now to the horizon, then stop.
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      setPick((cur) => {
        const next = (cur ?? 0) + 5;
        if (next >= ahead) {
          setPlaying(false);
          return ahead;
        }
        return next;
      });
    }, 1100);
    return () => clearInterval(t);
  }, [playing, ahead]);

  const imageOf = (y: number) => (y === 0 ? `${API_BASE}/api/explorer/datasets/${id}/observations/${endDate}/layer.png` : `${API_BASE}/api/explorer/datasets/${id}/projection-map.png?years=${y}`);
  // Warm the browser cache so scrubbing and playing do not flash.
  useEffect(() => {
    for (const y of steps) {
      const im = new Image();
      im.src = imageOf(y);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, steps, endDate]);

  const p = res && res.key === key ? res.p : null;
  const last = p?.history?.[p.history.length - 1];
  const end = p?.projection?.[p.projection.length - 1];

  const selYear = lastYear + step;
  let selValue: number | null = null;
  if (p?.available && last && p.projection) {
    const pts = [{ year: last.year, v: last.area_ha }, ...p.projection.map((r) => ({ year: r.year, v: r.central_ha }))].sort((a, b) => a.year - b.year);
    selValue = pts[pts.length - 1].v;
    for (let i = 1; i < pts.length; i++) {
      if (selYear <= pts[i].year) {
        const a = pts[i - 1];
        const b = pts[i];
        selValue = selYear <= a.year ? a.v : a.v + ((b.v - a.v) * (selYear - a.year)) / Math.max(1, b.year - a.year);
        break;
      }
    }
  }
  const shown = useCountUp(selValue ?? 0);
  const delta = last && selValue != null ? selValue - last.area_ha : null;
  const pct = last && delta != null && last.area_ha ? (delta / last.area_ha) * 100 : null;
  const water = p?.key === "water";
  const cNow = water ? "rgb(56,139,253)" : "rgb(214,118,80)";
  const cAdd = water ? "rgb(0,229,255)" : "rgb(255,222,23)";

  const chart = useMemo(() => {
    if (!p?.available || !p.history || !p.projection) return [];
    const m = new Map<number, { year: number; history?: number; central?: number; low?: number; band?: number }>();
    for (const h of p.history) m.set(h.year, { year: h.year, history: h.area_ha });
    for (const r of p.projection) {
      const e = m.get(r.year) ?? { year: r.year };
      e.central = r.central_ha;
      if (r.low_ha != null && r.high_ha != null) {
        e.low = r.low_ha;
        e.band = r.high_ha - r.low_ha;
      }
      m.set(r.year, e);
    }
    return [...m.values()].sort((a, b) => a.year - b.year);
  }, [p]);

  if (error) return <ErrorBox message={error} />;
  if (!rows) return <Loading what="datasets" />;
  const quick = QUICK.filter((q) => rows.some((r) => r.id === q));
  const nice = (r: CatalogueRow) => r.name.replace(/ \((?:GHSL|JRC|ESA)[^)]*\)$/, "").replace(" metropolitan area", "");
  const placeName = p?.name ? p.name.replace(/ \((?:GHSL|JRC|ESA)[^)]*\)$/, "").replace(" metropolitan area", "") : "";
  const pill = "rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition";

  return (
    <>
      {/* Hero */}
      <section className="relative mb-6 overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-br from-slate-950 via-indigo-950 to-sky-900 p-6 text-white shadow-2xl sm:p-8" data-testid="outlook-hero">
        <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-sky-400/25 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute -bottom-28 left-1/3 h-72 w-72 rounded-full bg-fuchsia-500/20 blur-3xl" />
        <div className="relative">
          <p className="text-[11px] font-bold uppercase tracking-[0.28em] text-sky-300">Future Outlook</p>
          <h1 className="mt-1 text-3xl font-extrabold tracking-tight sm:text-4xl">{placeName || "Loading place"}</h1>
          <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-sky-100/80">Drag through time and see how this place could look if the change measured from satellites keeps going. A trend, not a certain prediction.</p>
          <div className="mt-5 flex flex-wrap items-end gap-3">
            <label className="flex min-w-[240px] flex-1 flex-col gap-1 text-[11px] font-semibold uppercase tracking-wider text-sky-200/80 sm:max-w-sm">
              Place
              <select className="nx-input !bg-white/10 !text-white text-[14px] normal-case tracking-normal" value={id} onChange={(e) => { setId(e.target.value); setPick(null); setPlaying(false); }} aria-label="Place">
                {rows.map((r) => (
                  <option key={r.id} value={r.id}>{r.name}</option>
                ))}
              </select>
            </label>
            <div role="group" aria-label="Years ahead" className="flex gap-1 rounded-full bg-white/10 p-1 backdrop-blur">
              {AHEAD.map((h) => (
                <button key={h} type="button" aria-pressed={ahead === h} className={`${pill} ${ahead === h ? "bg-white text-slate-900 shadow" : "text-sky-100 hover:bg-white/10"}`} onClick={() => { setAhead(h); setPick(null); setPlaying(false); }}>In {h} years</button>
              ))}
            </div>
          </div>
          {quick.length ? (
            <div className="mt-4 flex flex-wrap gap-2" aria-label="Quick places">
              {quick.map((q) => {
                const r = rows.find((x) => x.id === q);
                return r ? (
                  <button key={q} type="button" className={`rounded-full border px-3 py-1 text-[12px] transition ${q === id ? "border-sky-300 bg-sky-300/20 text-white" : "border-white/15 text-sky-100/80 hover:border-sky-300/60"}`} onClick={() => { setId(q); setPick(null); setPlaying(false); }}>{nice(r)}</button>
                ) : null;
              })}
            </div>
          ) : null}
        </div>
      </section>

      {!p ? <Loading what="outlook" /> : !p.available ? <ErrorBox message={p.reason ?? "No outlook is available for this dataset."} /> : (
        <>
          {/* Time machine stage */}
          <section className="mb-6 grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]" data-testid="outlook-maps">
            <div className="relative overflow-hidden rounded-3xl border border-white/10 bg-slate-950 p-3 shadow-xl">
              <div className="relative mx-auto aspect-square w-full max-w-[640px] select-none overflow-hidden rounded-2xl bg-slate-900">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img alt={`Outlook ${selYear}`} className="absolute inset-0 h-full w-full object-contain" src={imageOf(step)} draggable={false} />
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img alt={`Measured ${lastYear}`} className="absolute inset-0 h-full w-full object-contain" style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }} src={imageOf(0)} draggable={false} />
                <div aria-hidden className="pointer-events-none absolute inset-y-0 w-0.5 bg-white shadow-[0_0_14px_rgba(255,255,255,0.9)]" style={{ left: `${split}%` }}>
                  <span className="absolute left-1/2 top-1/2 flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-white/70 bg-slate-900/80 text-[13px] text-white backdrop-blur">⇆</span>
                </div>
                <span className="pointer-events-none absolute left-3 top-3 rounded-full bg-black/60 px-3 py-1 text-[11px] font-bold uppercase tracking-wider text-white backdrop-blur">Measured {lastYear}</span>
                <span className="pointer-events-none absolute right-3 top-3 rounded-full bg-sky-500/80 px-3 py-1 text-[11px] font-bold uppercase tracking-wider text-white backdrop-blur">{step === 0 ? `Measured ${lastYear}` : `Outlook ${selYear}`}</span>
                <input type="range" min={0} max={100} value={split} onChange={(e) => setSplit(Number(e.target.value))} aria-label="Compare measured and outlook" className="absolute inset-0 h-full w-full cursor-ew-resize opacity-0" />
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 px-1 text-[12px] text-slate-300">
                <span><i className="mr-1.5 inline-block h-3 w-3 rounded-sm align-middle" style={{ background: cNow }} />{water ? "water today" : "built-up today"}</span>
                <span><i className="mr-1.5 inline-block h-3 w-3 rounded-sm align-middle" style={{ background: cAdd }} />added if the trend continues</span>
                <span><i className="mr-1.5 inline-block h-3 w-3 rounded-sm align-middle" style={{ background: "rgb(230,57,70)" }} />removed if the trend continues</span>
              </div>
            </div>

            <div className="flex flex-col gap-4">
              <div className="relative overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-br from-slate-900 to-indigo-950 p-5 text-white shadow-xl">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-sky-300">{step === 0 ? "Measured" : "If the trend continues"}</p>
                    <p className="mt-1 text-6xl font-black leading-none tabular-nums tracking-tight" data-testid="outlook-year">{selYear}</p>
                  </div>
                  <button type="button" onClick={() => { if (playing) { setPlaying(false); } else { setPick(0); setPlaying(true); } }} className="flex items-center gap-2 rounded-full bg-sky-400 px-4 py-2 text-[13px] font-bold text-slate-950 shadow-lg shadow-sky-500/30 transition hover:bg-sky-300">
                    <span aria-hidden>{playing ? "❚❚" : "▶"}</span>{playing ? "Pause" : "Play"}
                  </button>
                </div>
                <p className="mt-4 text-[34px] font-extrabold leading-none tabular-nums">{fmtNum(shown)} <span className="text-[16px] font-semibold text-sky-200">ha</span></p>
                <p className="mt-1 text-[12.5px] text-sky-100/70">{p.variable}</p>
                {step > 0 && delta != null ? (
                  <p className={`mt-3 inline-block rounded-full px-3 py-1 text-[13px] font-bold ${delta >= 0 ? "bg-emerald-400/20 text-emerald-300" : "bg-rose-400/20 text-rose-300"}`}>
                    {delta >= 0 ? "▲" : "▼"} {delta >= 0 ? "+" : ""}{fmtNum(delta)} ha{pct != null ? ` (${pct >= 0 ? "+" : ""}${fmtNum(pct, 1)}%)` : ""} since {lastYear}
                  </p>
                ) : <p className="mt-3 text-[12.5px] text-sky-100/70">Last satellite measurement. Slide forward in time.</p>}
                <div className="mt-5">
                  <input type="range" min={0} max={ahead} step={5} value={step} onChange={(e) => { setPlaying(false); setPick(Number(e.target.value)); }} aria-label="Years after the last measurement" className="h-2 w-full cursor-pointer accent-sky-400" />
                  <div className="mt-1 flex justify-between text-[11px] tabular-nums text-sky-200/70" aria-hidden>
                    {steps.map((s) => <span key={s} className={s === step ? "font-bold text-white" : ""}>{lastYear + s}</span>)}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3" data-testid="outlook-kpis">
                <div className="nx-glass px-4 py-3" data-testid="kpi">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[color:var(--nx-muted)]">By {horizon}</p>
                  <p className="mt-1 text-[22px] font-bold tabular-nums">{fmtNum(end?.central_ha)} ha</p>
                  <p className="text-[12px] text-[color:var(--nx-muted)]">{end?.low_ha != null ? `range ${fmtNum(end.low_ha)} to ${fmtNum(end.high_ha)}` : "single observed rate, no range"}</p>
                </div>
                <div className="nx-glass px-4 py-3" data-testid="kpi">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[color:var(--nx-muted)]">Trend</p>
                  <p className="mt-1 text-[22px] font-bold tabular-nums">{(p.slope_ha_per_year ?? 0) >= 0 ? "+" : ""}{fmtNum(p.slope_ha_per_year, 1)}</p>
                  <p className="text-[12px] text-[color:var(--nx-muted)]">ha per year (latest {fmtNum(p.recent_rate_ha_per_year, 1)})</p>
                </div>
                <div className="nx-glass col-span-2 flex flex-wrap items-center gap-2 px-4 py-3">
                  <Badge tone="official">SATELLITE OBSERVATIONS</Badge>
                  <Badge tone="model">TREND OUTLOOK</Badge>
                  <Badge tone={p.confidence === "medium" ? "info" : "warn"}>{(p.confidence ?? "low").toUpperCase()} CONFIDENCE</Badge>
                </div>
              </div>
            </div>
          </section>
          <Note>An illustration: the trend area is placed on the cells nearest to the existing {p.variable}, so real change may happen in other places.</Note>

          <Card title="The trend over time" subtitle={`${p.variable}: measured (solid) and trend outlook (dashed). The marker follows the time slider.`} className="mt-5" testid="outlook-chart">
            <div className="h-[380px]" role="img" aria-label="Chart of the measured series and its trend outlook">
              <ResponsiveContainer>
                <ComposedChart data={chart} margin={{ left: 8, right: 16, top: 8 }}>
                  <defs>
                    <linearGradient id="ol-band" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={C.accent} stopOpacity={0.35} />
                      <stop offset="100%" stopColor={C.accent} stopOpacity={0.08} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={C.grid} vertical={false} />
                  <XAxis dataKey="year" type="number" domain={["dataMin", "dataMax"]} {...axisProps} />
                  <YAxis {...axisProps} width={64} tickFormatter={(x) => fmtNum(x)} label={{ value: "hectares", angle: -90, position: "insideLeft", fill: C.muted, fontSize: 11 }} />
                  <Tooltip {...tooltipStyle} formatter={(v, name) => (name === "band" ? "" : `${fmtNum(Number(v))} ha`)} />
                  <Legend />
                  {last ? <ReferenceLine x={last.year} stroke={C.muted} strokeDasharray="3 3" label={{ value: "last measurement", fill: C.muted, fontSize: 11, position: "insideTopLeft" }} /> : null}
                  {p.footprint_ha ? <ReferenceLine y={p.footprint_ha} stroke={C.loss} strokeDasharray="2 4" label={{ value: "study-area limit", fill: C.loss, fontSize: 11, position: "insideBottomRight" }} /> : null}
                  <Area dataKey="low" stackId="b" stroke="none" fill="transparent" legendType="none" isAnimationActive={false} />
                  <Area dataKey="band" stackId="b" stroke="none" fill="url(#ol-band)" name="range of observed rates" isAnimationActive={false} />
                  <Line dataKey="history" name="measured" stroke={C.accent} strokeWidth={3} dot={{ r: 4 }} connectNulls isAnimationActive={false} />
                  <Line dataKey="central" name="trend outlook" stroke={C.orange} strokeWidth={2.5} strokeDasharray="7 5" dot={false} connectNulls isAnimationActive={false} />
                  {selValue != null && step > 0 ? <ReferenceDot x={selYear} y={selValue} r={7} fill={C.orange} stroke="#fff" strokeWidth={2} /> : null}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <Note>{p.method} {p.limits} {p.reaches_footprint ? "The outlook reaches the edge of the study area, so growth beyond it cannot be shown. " : ""}Based on {p.n_observations} observations.</Note>
          </Card>
        </>
      )}
    </>
  );
}
