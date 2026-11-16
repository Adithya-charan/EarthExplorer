"use client";

import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { analyticsApi, fmtNum, primaryVariable, type CatalogueRow, type DatasetStats } from "@/lib/explorer/analytics";
import { toApiError } from "@/lib/api";
import { axisProps, Badge, C, Card, ErrorBox, Loading, Note, PageTitle, tooltipStyle } from "@/components/analytics/ui";

interface Side {
  id: string;
  label: string;
  variable: string;
  series: { date: string; year: number; ha: number }[];
  net: number;
  pct: number | null;
  perYear: number;
  source: string | null;
}

function toSide(row: CatalogueRow, st: DatasetStats): Side | null {
  const p = primaryVariable(st);
  if (!p || p[1].series.length < 2) return null;
  const s = p[1].series.map((x) => ({ date: x.date, year: Number(x.date.slice(0, 4)), ha: x.area_ha }));
  const first = s[0];
  const last = s[s.length - 1];
  const label = row.name.replace(/ \((?:GHSL|JRC|ESA)[^)]*\)$/, "").replace(" metropolitan area", "");
  return { id: row.id, label, variable: p[1].label, series: s, net: last.ha - first.ha, pct: first.ha ? ((last.ha - first.ha) / first.ha) * 100 : null, perYear: (last.ha - first.ha) / Math.max(1, last.year - first.year), source: row.source };
}

function Column({ s, color }: { s: Side | null; color: string }) {
  if (!s) return <Loading what="measurements" />;
  const last = s.series[s.series.length - 1];
  const tile = "nx-glass px-3 py-2";
  const cap = "text-[11px] uppercase text-[color:var(--nx-muted)]";
  return (
    <div className="space-y-3" data-testid="compare-col">
      <h3 className="text-[18px] font-bold" style={{ color }}>{s.label}</h3>
      <div className="flex flex-wrap gap-1.5">
        <Badge tone="official">SATELLITE OBSERVATIONS</Badge>
        <Badge tone="info">{s.variable.toUpperCase()}</Badge>
      </div>
      <dl className="grid grid-cols-2 gap-2 text-[13px]">
        <div className={tile}><dt className={cap}>{s.series[0].year}</dt><dd className="text-[18px] font-bold tabular-nums">{fmtNum(s.series[0].ha)} ha</dd></div>
        <div className={tile}><dt className={cap}>{last.year}</dt><dd className="text-[18px] font-bold tabular-nums">{fmtNum(last.ha)} ha</dd></div>
        <div className={tile}><dt className={cap}>Net change</dt><dd className="text-[18px] font-bold tabular-nums">{s.net >= 0 ? "+" : ""}{fmtNum(s.net)} ha</dd></div>
        <div className={tile}><dt className={cap}>Change</dt><dd className="text-[18px] font-bold tabular-nums">{s.pct == null ? "n/a" : `${s.pct >= 0 ? "+" : ""}${fmtNum(s.pct, 1)}%`}</dd></div>
        <div className={`${tile} col-span-2`}><dt className={cap}>Average per year</dt><dd className="text-[16px] font-semibold tabular-nums">{s.perYear >= 0 ? "+" : ""}{fmtNum(s.perYear, 1)} ha / year</dd></div>
      </dl>
      <p className="text-[12px] text-[color:var(--nx-muted)]">Source: {s.source}</p>
    </div>
  );
}

export function CompareView() {
  const [rows, setRows] = useState<CatalogueRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [a, setA] = useState("ghsl-built-up-chennai");
  const [b, setB] = useState("ghsl-built-up-pune");
  const [stats, setStats] = useState<Record<string, DatasetStats>>({});

  useEffect(() => {
    let live = true;
    analyticsApi.catalogue().then((r) => live && setRows(r.datasets.filter((d) => d.observations >= 2))).catch((e) => live && setError(toApiError(e).message));
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    const need = [a, b].filter((id) => id && !stats[id]);
    if (!need.length) return;
    let live = true;
    for (const id of need) analyticsApi.stats(id).then((s) => live && setStats((m) => ({ ...m, [id]: s }))).catch(() => {});
    return () => {
      live = false;
    };
  }, [a, b, stats]);

  const sa = useMemo(() => {
    const r = rows?.find((x) => x.id === a);
    return r && stats[a] ? toSide(r, stats[a]) : null;
  }, [a, stats, rows]);
  const sb = useMemo(() => {
    const r = rows?.find((x) => x.id === b);
    return r && stats[b] ? toSide(r, stats[b]) : null;
  }, [b, stats, rows]);
  const merged = useMemo(() => {
    if (!sa || !sb) return [];
    const years = [...new Set([...sa.series.map((x) => x.year), ...sb.series.map((x) => x.year)])].sort((x, y) => x - y);
    const idx = (s: Side, y: number) => {
      const p = s.series.find((x) => x.year === y);
      return p && s.series[0].ha ? (p.ha / s.series[0].ha) * 100 : null;
    };
    return years.map((y) => ({ year: y, [sa.label]: idx(sa, y), [sb.label]: idx(sb, y) }));
  }, [sa, sb]);

  if (error) return <ErrorBox message={error} />;
  if (!rows) return <Loading what="datasets" />;
  const sameKind = sa && sb ? sa.variable === sb.variable : true;
  const select = (value: string, set: (v: string) => void, other: string, label: string) => (
    <label className="flex flex-col gap-1 text-[12px] font-semibold uppercase tracking-wider text-[color:var(--nx-muted)]">
      {label}
      <select className="nx-input text-[14px] normal-case tracking-normal" value={value} onChange={(e) => set(e.target.value)} aria-label={label}>
        {rows.map((r) => (
          <option key={r.id} value={r.id} disabled={r.id === other}>{r.name}</option>
        ))}
      </select>
    </label>
  );

  return (
    <>
      <PageTitle title="Compare Places">Two places side by side, measured from satellite products. The chart indexes each place to 100 at its first observation, so places of different size can be compared fairly.</PageTitle>
      <div className="mb-5 grid gap-4 sm:grid-cols-2">
        {select(a, setA, b, "Place A")}
        {select(b, setB, a, "Place B")}
      </div>
      {!sameKind ? <p role="status" className="mb-4 rounded-lg border border-amber-700/40 bg-amber-50 px-3 py-2 text-[12.5px] text-amber-900">These two measure different things ({sa?.variable} and {sb?.variable}), so compare the shape of change, not the hectares.</p> : null}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card testid="compare-a"><Column s={sa} color={C.series[0]} /></Card>
        <Card testid="compare-b"><Column s={sb} color={C.series[2]} /></Card>
      </div>
      {sa && sb ? (
        <Card title="Growth since the first observation" subtitle="Index: 100 = the first observation of each place" className="mt-6" testid="compare-chart">
          <div className="h-[320px]" role="img" aria-label="Line chart of the indexed change of both places">
            <ResponsiveContainer>
              <LineChart data={merged} margin={{ left: 4, right: 16, top: 8 }}>
                <CartesianGrid stroke={C.grid} vertical={false} />
                <XAxis dataKey="year" type="number" domain={["dataMin", "dataMax"]} {...axisProps} />
                <YAxis {...axisProps} width={48} domain={["auto", "auto"]} />
                <Tooltip {...tooltipStyle} formatter={(v) => fmtNum(Number(v), 1)} />
                <Legend />
                <Line type="monotone" dataKey={sa.label} stroke={C.series[0]} strokeWidth={2.5} dot connectNulls />
                <Line type="monotone" dataKey={sb.label} stroke={C.series[2]} strokeWidth={2.5} dot connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <Note>Built-up values are GHSL epochs (modelled years, not acquisition dates). Water values compare the first and last year of the JRC record, and early coverage is sparse.</Note>
        </Card>
      ) : null}
    </>
  );
}
