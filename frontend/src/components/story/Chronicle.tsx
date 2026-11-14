"use client";

import { useEffect, useMemo, useState } from "react";
import { Pause, Play } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { DRY, NEUTRAL, WET, anomalyColor } from "@/lib/story";
import type { AtlasResponse, OverviewResponse } from "@/lib/types";
import { ProvenanceBanner } from "@/components/data/DatasetStatus";
import { Badge, Button, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { PlacesMap } from "@/components/story/PlacesMap";
import type { GeoJSONFeatureCollection } from "@/lib/earth/types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const Z_MONTH = 2.5; // monthly colours saturate at ±2.5 standard deviations
const Z_YEAR = 1.2; // yearly means vary less, so they saturate sooner
const MISSING = "#e9edf2";

const KIND_LABEL: Record<string, string> = {
  observation: "In the data",
  comparison: "Compared",
  context: "Context",
  limitation: "Limit",
  hypothesis: "Lead, not a cause",
};

export const zColor = (z: number | null, range = Z_MONTH) => (z === null ? MISSING : anomalyColor(z, range));

export function fmt(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "–";
  const ax = Math.abs(x);
  return x.toLocaleString("en", { maximumFractionDigits: ax >= 100 ? 0 : ax >= 1 ? Math.max(digits, 1) : 2 });
}

const sign = (x: number) => (x >= 0 ? "+" : "−");

function Legend({ label, range }: { label: string; range: number }) {
  const stops = [-1, -0.66, -0.33, 0, 0.33, 0.66, 1].map((t) => t * range);
  return (
    <div className="flex items-center gap-2 text-xs text-muted" aria-label={label} role="img">
      <span>below usual</span>
      <span className="flex h-2.5 overflow-hidden rounded-full">
        {stops.map((z) => (
          <span key={z} className="h-full w-5" style={{ background: zColor(z, range) }} />
        ))}
      </span>
      <span>above usual (full colour at ±{range} SD)</span>
      <span className="ml-2 inline-flex items-center gap-1">
        <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: MISSING }} /> no value
      </span>
    </div>
  );
}

function Stat({ label, value, note, tone }: { label: string; value: string; note: string; tone?: "wet" | "dry" }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-white/60">{label}</p>
      <p className="mt-1 text-xl font-semibold leading-tight" style={{ color: tone === "wet" ? "#7cc4f0" : tone === "dry" ? "#ffa66b" : "#fff" }}>
        {value}
      </p>
      <p className="mt-0.5 text-xs text-white/70">{note}</p>
    </div>
  );
}

/** Hero: one coloured stripe per year, in the style of "warming stripes", plus the headline numbers. */
function Hero({ o, selected, onYear }: { o: OverviewResponse; selected: number | null; onYear: (y: number) => void }) {
  const [hover, setHover] = useState<number | null>(null);
  const n = o.years.length;
  const peak = o.climatology.reduce<{ month: number; mean: number } | null>(
    (b, c) => (c.mean !== null && (b === null || c.mean > b.mean) ? { month: c.month, mean: c.mean } : b),
    null,
  );
  const wy = o.wettest_years[0];
  const dy = o.driest_years[0];
  const shown = hover ?? selected;
  const sp = shown !== null ? o.years.find((y) => y.year === shown) : undefined;
  return (
    <div className="overflow-hidden rounded-xl text-white shadow-card" style={{ background: "linear-gradient(135deg,#0f1b2d 0%,#16324f 60%,#0f3b4a 100%)" }} data-testid="chronicle-hero">
      <div className="p-4 pb-3 sm:p-5 sm:pb-3">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-white/60">The whole record</p>
        <h2 className="mt-1 text-2xl font-semibold sm:text-3xl">
          {o.region} <span className="font-normal text-white/60">{o.first_year}–{o.last_year}</span>
        </h2>
        <p className="mt-1 max-w-2xl text-sm text-white/75">
          Every year as one stripe: blue = above that region&apos;s usual, orange = below, grey = not enough months (full colour at ±{Z_YEAR} SD). Click a stripe to explain that year.
        </p>
      </div>
      <div className="relative">
        <svg viewBox={`0 0 ${n} 30`} preserveAspectRatio="none" className="block h-24 w-full sm:h-28" role="img" aria-label={`Yearly difference from usual for ${o.region}, ${o.first_year} to ${o.last_year}`}>
          {o.years.map((y, i) => (
            <rect
              key={y.year}
              x={i}
              y={0}
              width={1.02}
              height={30}
              fill={zColor(y.mean_z, Z_YEAR)}
              opacity={shown === null || shown === y.year ? 1 : 0.55}
              onMouseEnter={() => setHover(y.year)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onYear(y.year)}
              style={{ cursor: "pointer" }}
            >
              <title>{`${y.year}: ${y.mean_z === null ? "not enough months" : `${y.mean_z >= 0 ? "above" : "below"} usual (${sign(y.mean_z)}${Math.abs(y.mean_z).toFixed(2)} SD)`}`}</title>
            </rect>
          ))}
        </svg>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-between px-3 pb-1 text-[11px] font-medium text-slate-900/70 mix-blend-normal">
          <span>{o.first_year}</span>
          <span>{o.last_year}</span>
        </div>
      </div>
      <p className="min-h-5 px-4 pt-2 text-sm text-white/85 sm:px-5" data-testid="hero-readout" aria-live="polite">
        {sp
          ? sp.mean_z === null
            ? `${sp.year}: only ${sp.n_months} valid month${sp.n_months === 1 ? "" : "s"}, so no yearly number.`
            : `${sp.year}: ${sp.mean_anomaly !== null ? `${sign(sp.mean_anomaly)}${fmt(Math.abs(sp.mean_anomaly))} ${o.unit} vs the usual month` : ""} (${sign(sp.mean_z)}${Math.abs(sp.mean_z).toFixed(2)} SD)`
          : "Hover or click a stripe."}
      </p>
      <div className="grid gap-2 p-4 pt-3 sm:grid-cols-2 sm:p-5 sm:pt-3 lg:grid-cols-4">
        <Stat label="Typical peak" value={peak ? MONTHS[peak.month - 1] : "–"} note={peak ? `${fmt(peak.mean)} ${o.unit} on average` : "needs ≥3 values per month"} />
        <Stat label="Most above normal" value={wy ? String(wy.year) : "–"} note={wy ? `${sign(wy.mean_anomaly)}${fmt(Math.abs(wy.mean_anomaly))} ${o.unit} vs usual` : ""} tone="wet" />
        <Stat label="Most below normal" value={dy ? String(dy.year) : "–"} note={dy ? `${sign(dy.mean_anomaly)}${fmt(Math.abs(dy.mean_anomaly))} ${o.unit} vs usual` : ""} tone="dry" />
        <Stat
          label="Straight-line change"
          value={o.trend ? `${sign(o.trend.slope_per_decade)}${fmt(Math.abs(o.trend.slope_per_decade), 1)}` : "–"}
          note={o.trend ? `${o.unit} per decade · p = ${o.trend.p_value < 0.001 ? "<0.001" : o.trend.p_value.toFixed(3)}` : "needs ≥20 full years"}
        />
      </div>
    </div>
  );
}


/** All located regions at once on a 3D map, with a year slider and a play button (a time-lapse). */
function Snapshot({ datasetId, o, boundaries }: { datasetId: string; o: OverviewResponse; boundaries: GeoJSONFeatureCollection | null }) {
  const [st, setSt] = useState<{ year: number | null; month: number; playing: boolean }>({ year: null, month: 0, playing: false });
  const year = st.year ?? o.last_year;
  const snap = useApi((s) => api.snapshot(datasetId, year, st.month, s), `snapshot:${datasetId}:${year}:${st.month}`);
  const first = o.first_year;
  const last = o.last_year;
  useEffect(() => {
    if (!st.playing) return;
    const id = setInterval(
      () =>
        setSt((c) => {
          const y = (c.year ?? last) + 1;
          return y > last ? { ...c, year: last, playing: false } : { ...c, year: y };
        }),
      900,
    );
    return () => clearInterval(id);
  }, [st.playing, last]);
  const d = snap.data;
  if (d && d.points.length === 0 && !d.unlocated.length && !snap.loading) return null;
  return (
    <Card data-testid="snapshot">
      <CardHeader
        title="The map in motion"
        subtitle="Every region with a known position at once. Press play to watch the years go by; column height = amount, colour = above or below usual."
      />
      <CardBody className="space-y-3">
        <div className="h-[420px]">
          <PlacesMap snapshot={d ?? null} boundaries={boundaries} valueMax={d?.value_max ?? 0} />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => setSt((c) => ({ ...c, year: c.playing ? c.year : (c.year ?? last) >= last ? first : (c.year ?? last), playing: !c.playing }))} aria-label={st.playing ? "Pause" : "Play through the years"}>
            {st.playing ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />} {st.playing ? "Pause" : "Play"}
          </Button>
          <input
            type="range"
            min={first}
            max={last}
            value={year}
            onChange={(e) => setSt((c) => ({ ...c, year: Number(e.target.value), playing: false }))}
            aria-label="Year shown on the map"
            className="min-w-40 flex-1"
          />
          <select
            value={st.month}
            onChange={(e) => setSt((c) => ({ ...c, month: Number(e.target.value) }))}
            aria-label="Month shown on the map"
            className="min-h-9 rounded-md border border-line bg-surface px-2 text-sm"
          >
            <option value={0}>Whole year</option>
            {MONTHS.map((m, i) => (
              <option key={m} value={i + 1}>{m}</option>
            ))}
          </select>
          <p className="tabular min-w-24 text-sm font-semibold text-ink" data-testid="snapshot-label">{d?.label ?? year}</p>
        </div>
        {snap.error ? <ErrorState title="No map data for that choice" error={snap.error} onRetry={snap.reload} /> : null}
        {d ? (
          <ul className="space-y-1" data-testid="snapshot-sentences">
            {d.sentences.map((s, i) => (
              <li key={i} title={`Evidence: ${s.evidence}`} className="text-sm text-ink">
                <Badge tone={s.kind === "limitation" ? "warn" : "neutral"}>{KIND_LABEL[s.kind]}</Badge> {s.text}
              </li>
            ))}
          </ul>
        ) : null}
        {d ? <p className="text-xs text-muted">{d.note}</p> : null}
      </CardBody>
    </Card>
  );
}

/** Year × month grid: each cell is one month, coloured by how far it was from that calendar month's usual value. */
function Calendar({ o, selected, onPick, onYear }: { o: OverviewResponse; selected: number | null; onPick: (y: number, m: number) => void; onYear: (y: number) => void }) {
  const [hover, setHover] = useState<{ y: number; m: number } | null>(null);
  const n = o.years.length;
  const L = 26; // label gutter
  const cell = 6;
  const ch = 9; // cells are taller than wide so twelve months stay legible
  const H = 12 * ch;
  const hv = hover ? { v: o.matrix_values[hover.y - o.first_year]?.[hover.m] ?? null, z: o.matrix_z[hover.y - o.first_year]?.[hover.m] ?? null } : null;
  const decadeTicks = o.years.filter((y) => y.year % 10 === 0);
  return (
    <Card>
      <CardHeader title="Rain calendar" subtitle="Every month on record. Click a cell to explain that month and see it on the map." />
      <CardBody className="space-y-2">
        <svg viewBox={`0 0 ${L + n * cell} ${H + 14}`} className="w-full" role="img" aria-label="Calendar of monthly difference from usual, one cell per month" data-testid="rain-calendar">
          {MONTHS.map((m, i) => (
            <text key={m} x={L - 3} y={i * ch + ch - 2} textAnchor="end" fontSize={6} fill="currentColor" className="text-muted">
              {i % 2 === 0 ? m : ""}
            </text>
          ))}
          {o.years.map((yp, xi) =>
            MONTHS.map((_, mi) => {
              const z = o.matrix_z[xi][mi];
              const v = o.matrix_values[xi][mi];
              const isSel = selected === yp.year;
              return (
                <rect
                  key={`${yp.year}-${mi}`}
                  x={L + xi * cell}
                  y={mi * ch}
                  width={cell - 0.4}
                  height={ch - 0.5}
                  fill={v === null ? MISSING : z === null ? NEUTRAL : zColor(z)}
                  stroke={isSel ? "#0f1b2d" : "none"}
                  strokeWidth={0.5}
                  onMouseEnter={() => setHover({ y: yp.year, m: mi })}
                  onMouseLeave={() => setHover(null)}
                  onClick={() => (v === null ? onYear(yp.year) : onPick(yp.year, mi + 1))}
                  style={{ cursor: "pointer" }}
                />
              );
            }),
          )}
          {decadeTicks.map((y) => (
            <text key={y.year} x={L + (y.year - o.first_year) * cell + cell / 2} y={H + 10} textAnchor="middle" fontSize={6} fill="currentColor" className="text-muted">
              {y.year}
            </text>
          ))}
        </svg>
        <p className="min-h-5 text-sm text-ink-soft" aria-live="polite" data-testid="calendar-readout">
          {hover
            ? hv?.v === null
              ? `${MONTHS[hover.m]} ${hover.y}: no value (left empty, not filled in).`
              : `${MONTHS[hover.m]} ${hover.y}: ${fmt(hv?.v)} ${o.unit}${hv?.z !== null && hv?.z !== undefined ? ` · ${sign(hv.z)}${Math.abs(hv.z).toFixed(1)} SD vs usual ${MONTHS[hover.m]}` : ""}`
            : "Hover a cell for its value."}
        </p>
        <Legend label="Colour scale: blue above usual, orange below usual" range={Z_MONTH} />
      </CardBody>
    </Card>
  );
}

/** Seasonal cycle: the usual month-by-month pattern with its spread, and the chosen years drawn over it. */
function Seasons({ o, selected }: { o: OverviewResponse; selected: number | null }) {
  const W = 360, H = 190, pl = 34, pr = 8, pt = 10, pb = 22;
  const clim = o.climatology;
  const wy = o.wettest_years[0]?.year ?? null;
  const dy = o.driest_years[0]?.year ?? null;
  const rows = (y: number | null) => (y === null ? null : o.matrix_values[y - o.first_year] ?? null);
  const lines: { key: string; label: string; vals: (number | null)[] | null; color: string; dash?: string }[] = [
    { key: "wy", label: `${wy ?? ""} (most above normal)`, vals: rows(wy), color: WET },
    { key: "dy", label: `${dy ?? ""} (most below normal)`, vals: rows(dy), color: DRY },
  ];
  if (selected !== null && selected !== wy && selected !== dy) lines.push({ key: "sel", label: `${selected} (selected)`, vals: rows(selected), color: "#0f1b2d", dash: "4 2" });
  const maxY = Math.max(1e-9, ...clim.map((c) => (c.mean ?? 0) + (c.std ?? 0)), ...lines.flatMap((l) => (l.vals ?? []).map((v) => v ?? 0)));
  const x = (i: number) => pl + (i * (W - pl - pr)) / 11;
  const y = (v: number) => pt + (1 - v / maxY) * (H - pt - pb);
  const ok = clim.every((c) => c.mean !== null);
  const band = ok ? [...clim.map((c, i) => `${x(i)},${y(Math.max(0, (c.mean ?? 0) + (c.std ?? 0)))}`), ...clim.map((c, i) => `${x(11 - i)},${y(Math.max(0, (clim[11 - i].mean ?? 0) - (clim[11 - i].std ?? 0)))}`)].join(" ") : "";
  const path = (vals: (number | null)[]) => {
    let d = "";
    vals.forEach((v, i) => {
      if (v === null) return;
      d += `${d && vals[i - 1] !== null ? "L" : "M"}${x(i)},${y(v)}`;
    });
    return d;
  };
  return (
    <Card>
      <CardHeader title="The yearly rhythm" subtitle="Grey = the usual month (band = typical spread). Lines = the wettest and driest years drawn over it." />
      <CardBody>
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Seasonal cycle of the usual monthly value with extreme years" data-testid="seasons">
          {[0, 0.5, 1].map((t) => (
            <g key={t}>
              <line x1={pl} x2={W - pr} y1={y(maxY * t)} y2={y(maxY * t)} stroke="#e2e8f0" strokeWidth={0.6} />
              <text x={pl - 4} y={y(maxY * t) + 3} fontSize={8} textAnchor="end" fill="#5b6b80">{fmt(maxY * t)}</text>
            </g>
          ))}
          {MONTHS.map((m, i) => (
            <text key={m} x={x(i)} y={H - 6} fontSize={8} textAnchor="middle" fill="#5b6b80">{m[0]}</text>
          ))}
          {ok ? <polygon points={band} fill="#cbd5e1" opacity={0.55} /> : null}
          {ok ? <path d={path(clim.map((c) => c.mean))} fill="none" stroke="#33435a" strokeWidth={2} /> : null}
          {lines.map((l) => (l.vals ? <path key={l.key} d={path(l.vals)} fill="none" stroke={l.color} strokeWidth={1.6} strokeDasharray={l.dash} /> : null))}
        </svg>
        <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-soft">
          <li className="flex items-center gap-1"><span className="inline-block h-0.5 w-4 bg-[#33435a]" /> usual month ({o.unit})</li>
          {lines.map((l) => (
            <li key={l.key} className="flex items-center gap-1"><span className="inline-block h-0.5 w-4" style={{ background: l.color }} /> {l.label}</li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

function Decades({ o }: { o: OverviewResponse }) {
  const max = Math.max(1e-9, ...o.decades.map((d) => Math.abs(d.mean_anomaly)));
  return (
    <Card>
      <CardHeader title="Decade by decade" subtitle="Average difference from usual. Only decades with at least 5 valid years." />
      <CardBody>
        {o.decades.length ? (
          <ul className="space-y-1" data-testid="decades">
            {o.decades.map((d) => (
              <li key={d.decade} className="grid grid-cols-[3.2rem_1fr_4.5rem] items-center gap-2 text-xs">
                <span className="tabular text-ink-soft">{d.decade}s</span>
                <span className="relative h-4 rounded bg-surface-muted">
                  <span className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
                  <span
                    className="absolute inset-y-0.5 rounded-sm"
                    style={{
                      background: d.mean_anomaly >= 0 ? WET : DRY,
                      width: `${(Math.abs(d.mean_anomaly) / max) * 50}%`,
                      left: d.mean_anomaly >= 0 ? "50%" : undefined,
                      right: d.mean_anomaly < 0 ? "50%" : undefined,
                    }}
                  />
                </span>
                <span className="tabular text-right text-ink">{sign(d.mean_anomaly)}{fmt(Math.abs(d.mean_anomaly), 1)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">Not enough full years to compare decades.</p>
        )}
        <p className="mt-2 text-xs text-muted">Unit: {o.unit}, difference from the usual month.</p>
      </CardBody>
    </Card>
  );
}

function Records({ o, onPick, onYear }: { o: OverviewResponse; onPick: (y: number, m: number) => void; onYear: (y: number) => void }) {
  const mon = (iso: string) => ({ y: Number(iso.slice(0, 4)), m: Number(iso.slice(5, 7)) });
  const colBtn = "w-full rounded px-1 py-0.5 text-left text-xs hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
  return (
    <Card>
      <CardHeader title="Records" subtitle="Click one to jump to it." />
      <CardBody className="grid gap-3 sm:grid-cols-2">
        {[
          { title: "Most above-normal months", color: WET, items: o.wettest_months },
          { title: "Most below-normal months", color: DRY, items: o.driest_months },
        ].map((col) => (
          <div key={col.title}>
            <p className="mb-1 text-xs font-semibold" style={{ color: col.color }}>{col.title}</p>
            <ol className="space-y-0.5">
              {col.items.map((r) => {
                const { y, m } = mon(r.date);
                return (
                  <li key={r.date}>
                    <button type="button" className={colBtn} onClick={() => onPick(y, m)}>
                      <span className="font-medium text-ink">{MONTHS[m - 1]} {y}</span> <span className="tabular text-muted">{fmt(r.value)} {o.unit} · {sign(r.z)}{Math.abs(r.z).toFixed(1)} SD</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </div>
        ))}
        {[
          { title: "Most above-normal years", color: WET, items: o.wettest_years },
          { title: "Most below-normal years", color: DRY, items: o.driest_years },
        ].map((col) => (
          <div key={col.title}>
            <p className="mb-1 text-xs font-semibold" style={{ color: col.color }}>{col.title}</p>
            <ol className="space-y-0.5">
              {col.items.map((r) => (
                <li key={r.year}>
                  <button type="button" className={colBtn} onClick={() => onYear(r.year)}>
                    <span className="font-medium text-ink">{r.year}</span> <span className="tabular text-muted">{sign(r.mean_anomaly)}{fmt(Math.abs(r.mean_anomaly))} {o.unit} vs usual</span>
                  </button>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

/** Every region at once: rows are regions, columns are years. Same colour scale, so places can be compared. */
function Atlas({ a, region, onRegion }: { a: AtlasResponse; region: string; onRegion: (r: string, year?: number) => void }) {
  const [order, setOrder] = useState<"name" | "trend">("trend");
  const [hover, setHover] = useState<{ r: string; y: number } | null>(null);
  const regions = useMemo(() => {
    const rs = [...a.regions];
    if (order === "name") return rs.sort((p, q) => p.region.localeCompare(q.region));
    return rs.sort((p, q) => (p.trend_z_per_decade ?? 0) - (q.trend_z_per_decade ?? 0));
  }, [a.regions, order]);
  const L = 118, cell = 5, rh = 8.5, T = 10;
  const W = L + a.years.length * cell;
  const H = T + regions.length * rh + 12;
  const hr = hover ? a.regions.find((r) => r.region === hover.r) : undefined;
  const hz = hr && hover ? hr.z[hover.y - a.years[0]] : null;
  return (
    <Card data-testid="atlas">
      <CardHeader
        title="All regions at a glance"
        subtitle="Every region, every year, on one colour scale. Click a row to open that region."
        actions={
          <div className="flex gap-1 text-xs" role="group" aria-label="Sort regions">
            {(["trend", "name"] as const).map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={order === k}
                onClick={() => setOrder(k)}
                className={`rounded-md border px-2 py-1 ${order === k ? "border-accent bg-accent-soft text-accent-strong" : "border-line bg-surface text-ink-soft"}`}
              >
                {k === "trend" ? "Drying → wetting" : "A–Z"}
              </button>
            ))}
          </div>
        }
      />
      <CardBody className="space-y-2">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Yearly difference from usual for every region">
          {regions.map((r, ri) => {
            const active = r.region === region;
            return (
              <g key={r.region}>
                {active ? <rect x={0} y={T + ri * rh - 0.5} width={W} height={rh} fill="none" stroke="#0f1b2d" strokeWidth={0.7} /> : null}
                <text
                  x={L - 4}
                  y={T + ri * rh + rh - 2.2}
                  textAnchor="end"
                  fontSize={6}
                  fontWeight={active ? 700 : 400}
                  fill="currentColor"
                  className="cursor-pointer text-ink"
                  role="button"
                  tabIndex={0}
                  aria-label={`Open ${r.region}`}
                  onClick={() => onRegion(r.region)}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onRegion(r.region)}
                >
                  {r.region.length > 24 ? r.region.slice(0, 23) + "…" : r.region}
                </text>
                {r.z.map((z, yi) => (
                  <rect
                    key={yi}
                    x={L + yi * cell}
                    y={T + ri * rh}
                    width={cell - 0.3}
                    height={rh - 0.8}
                    fill={zColor(z, Z_YEAR)}
                    onMouseEnter={() => setHover({ r: r.region, y: a.years[yi] })}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => onRegion(r.region, a.years[yi])}
                    style={{ cursor: "pointer" }}
                  />
                ))}
              </g>
            );
          })}
          {a.years.filter((y) => y % 20 === 0).map((y) => (
            <text key={y} x={L + (y - a.years[0]) * cell + cell / 2} y={H - 2} textAnchor="middle" fontSize={5.5} fill="#5b6b80">{y}</text>
          ))}
        </svg>
        <p className="min-h-5 text-sm text-ink-soft" aria-live="polite">
          {hover && hr ? `${hr.region}, ${hover.y}: ${hz === null || hz === undefined ? "not enough months" : `${sign(hz)}${Math.abs(hz).toFixed(2)} SD vs usual`}` : "Hover a cell for its value."}
        </p>
        <Legend label="Colour scale: blue above usual, orange below usual" range={Z_YEAR} />
        <p className="text-xs text-muted">{a.note}</p>
      </CardBody>
    </Card>
  );
}

export function Chronicle({
  datasetId,
  region,
  onPickPeriod,
  onPickRegion,
  boundaries,
}: {
  boundaries: GeoJSONFeatureCollection | null;
  datasetId: string;
  region: string;
  onPickPeriod: (start: string, end: string) => void;
  onPickRegion: (region: string) => void;
}) {
  const overview = useApi((s) => api.overview(datasetId, region, s), `overview:${datasetId}:${region}`);
  const atlas = useApi((s) => api.atlas(datasetId, s), `atlas:${datasetId}`);
  const [pick, setPick] = useState<{ region: string; year: number } | null>(null);
  const selected = pick && pick.region === region ? pick.year : null;
  const o = overview.data;

  const pad = (m: number) => String(m).padStart(2, "0");
  const pickMonth = (y: number, m: number) => {
    setPick({ region, year: y });
    onPickPeriod(`${y}-${pad(m)}`, `${y}-${pad(m)}`);
  };
  const pickYear = (y: number) => {
    setPick({ region, year: y });
    onPickPeriod(`${y}-01`, `${y}-12`);
  };

  if (overview.loading) return <LoadingState label="Reading the whole record" variant="chart" />;
  if (overview.error) return <ErrorState title="Could not build the whole-record view" error={overview.error} onRetry={overview.reload} />;
  if (!o) return null;
  return (
    <section className="space-y-4" aria-label="Whole-record view" data-testid="chronicle">
      <ProvenanceBanner provenance={o.provenance} />
      <Hero o={o} selected={selected} onYear={pickYear} />
      <Snapshot datasetId={datasetId} o={o} boundaries={boundaries} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Calendar o={o} selected={selected} onPick={pickMonth} onYear={pickYear} />
        <Seasons o={o} selected={selected} />
      </div>
      <Card>
        <CardHeader title="The story in plain words" subtitle="Written by rules from the numbers; hover a line for its evidence. No AI service is used." />
        <CardBody className="space-y-2">
          <ul className="space-y-2" data-testid="chronicle-sentences">
            {o.sentences.map((s, i) => (
              <li key={i} title={`Evidence: ${s.evidence}`} className="text-sm text-ink">
                <Badge tone={s.kind === "limitation" ? "warn" : "neutral"}>{KIND_LABEL[s.kind]}</Badge> {s.text}
              </li>
            ))}
          </ul>
          {o.caveats.length ? <ul className="list-disc pl-5 text-xs text-warn">{o.caveats.map((c) => <li key={c}>{c}</li>)}</ul> : null}
        </CardBody>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Decades o={o} />
        <Records o={o} onPick={pickMonth} onYear={pickYear} />
      </div>
      {atlas.data ? (
        <Atlas
          a={atlas.data}
          region={region}
          onRegion={(r, y) => {
            if (y !== undefined) setPick({ region: r, year: y });
            onPickRegion(r);
          }}
        />
      ) : atlas.loading ? (
        <LoadingState label="Building the all-regions view" variant="chart" />
      ) : atlas.error ? (
        <ErrorState title="Could not build the all-regions view" error={atlas.error} onRetry={atlas.reload} />
      ) : null}
    </section>
  );
}
