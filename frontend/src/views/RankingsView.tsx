"use client";

import { useEffect, useMemo, useState } from "react";
import { analyticsApi, fmtNum, type RankingRow } from "@/lib/explorer/analytics";
import { toApiError } from "@/lib/api";
import { Badge, Card, ErrorBox, Loading, Note, PageTitle } from "@/components/analytics/ui";

type Ring = [number, number][];
interface StateShape {
  n: string;
  p: Ring[][];
}

const W = 600;
const H = 660;
const LON0 = 68;
const LAT1 = 37.5;
const SCALE = 17;
const KX = Math.cos((22 * Math.PI) / 180);
const proj = ([lon, lat]: [number, number]) => `${((lon - LON0) * KX * SCALE).toFixed(1)},${((LAT1 - lat) * SCALE).toFixed(1)}`;
const pathOf = (s: StateShape) => s.p.map((poly) => poly.map((r) => "M" + r.map(proj).join("L") + "Z").join("")).join("");

/** Sequential blue for growth; diverging red (loss) to blue (gain) for water. `t` runs from -1 to 1. */
function colour(kind: "built_up" | "water", v: number, max: number): string {
  const t = Math.max(-1, Math.min(1, v / (max || 1)));
  if (kind === "built_up") return `hsl(214 ${40 + 45 * Math.abs(t)}% ${92 - 52 * Math.abs(t)}%)`;
  return t >= 0 ? `hsl(214 ${40 + 45 * t}% ${92 - 50 * t}%)` : `hsl(356 ${40 + 45 * -t}% ${92 - 48 * -t}%)`;
}

const unit = (r: RankingRow) => `${r.first_date.slice(0, 4)}–${r.last_date.slice(0, 4)}`;

export function RankingsView() {
  const [rows, setRows] = useState<RankingRow[] | null>(null);
  const [shapes, setShapes] = useState<StateShape[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"built_up" | "water">("built_up");
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    analyticsApi.rankings().then((r) => live && setRows(r.rows)).catch((e) => live && setError(toApiError(e).message));
    fetch("/data/india_states.json").then((r) => r.json()).then((d: StateShape[]) => live && setShapes(d)).catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const ofKind = useMemo(() => (rows ?? []).filter((r) => r.kind === kind && r.pct != null), [rows, kind]);
  const byState = useMemo(() => {
    const m = new Map<string, { sum: number; n: number; places: string[] }>();
    for (const r of ofKind) for (const s of r.states) {
      const e = m.get(s) ?? { sum: 0, n: 0, places: [] };
      e.sum += r.pct ?? 0;
      e.n += 1;
      e.places.push(r.place);
      m.set(s, e);
    }
    return m;
  }, [ofKind]);
  const max = useMemo(() => Math.max(1, ...[...byState.values()].map((e) => Math.abs(e.sum / e.n))), [byState]);
  const board = useMemo(() => [...ofKind].sort((a, b) => (kind === "built_up" ? (b.pct ?? 0) - (a.pct ?? 0) : a.net_ha - b.net_ha)).slice(0, 10), [ofKind, kind]);
  const inHover = hover ? byState.get(hover) : null;

  if (error) return <ErrorBox message={error} />;
  if (!rows) return <Loading what="rankings" />;
  const tab = "rounded-lg px-3 py-1.5 text-[13px] font-medium";

  return (
    <>
      <PageTitle title="Rankings & Map">Change measured from satellite products, summarised per state and ranked by place. A state is coloured only where we hold data for it; grey states have none yet.</PageTitle>
      <div className="mb-4 flex gap-1 rounded-xl bg-slate-100 p-1 w-fit" role="tablist" aria-label="Measure">
        <button type="button" role="tab" aria-selected={kind === "built_up"} className={`${tab} ${kind === "built_up" ? "bg-white shadow" : ""}`} onClick={() => setKind("built_up")}>Built-up growth</button>
        <button type="button" role="tab" aria-selected={kind === "water"} className={`${tab} ${kind === "water" ? "bg-white shadow" : ""}`} onClick={() => setKind("water")}>Water change</button>
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(320px,520px)_1fr]">
        <Card title={kind === "built_up" ? "Built-up growth by state, 2000 to 2020" : "Water-area change by state, 1984 to 2021"} subtitle="Average of the places measured in each state" testid="state-map">
          {!shapes ? (
            <Loading what="map" />
          ) : (
            <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Map of India coloured by measured change per state" className="mx-auto h-auto w-full max-w-[520px]">
              {shapes.map((s) => {
                const e = byState.get(s.n);
                return (
                  <path key={s.n} d={pathOf(s)} fill={e ? colour(kind, e.sum / e.n, max) : "#e5e9f0"} stroke="#ffffff" strokeWidth={hover === s.n ? 1.8 : 0.7} onMouseEnter={() => setHover(s.n)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(s.n)} tabIndex={e ? 0 : -1}>
                    <title>{e ? `${s.n}: ${fmtNum(e.sum / e.n, 1)}% (${e.places.join(", ")})` : `${s.n}: no data yet`}</title>
                  </path>
                );
              })}
            </svg>
          )}
          <p className="mt-2 min-h-[2.5rem] text-[13px]" aria-live="polite">
            {hover ? (inHover ? <><strong>{hover}</strong>: {fmtNum(inHover.sum / inHover.n, 1)}% average across {inHover.places.join(", ")}</> : <><strong>{hover}</strong>: no data yet</>) : "Hover or focus a state for its figure."}
          </p>
          <div className="mt-1 flex items-center gap-2 text-[11px] text-[color:var(--nx-muted)]" aria-hidden>
            {kind === "water" ? <><span>loss</span><span className="h-2 w-24 rounded" style={{ background: "linear-gradient(90deg,hsl(356 85% 44%),hsl(0 0% 94%),hsl(214 85% 42%))" }} /><span>gain</span></> : <><span>low</span><span className="h-2 w-24 rounded" style={{ background: "linear-gradient(90deg,hsl(214 40% 92%),hsl(214 85% 40%))" }} /><span>high growth</span></>}
          </div>
        </Card>

        <Card title={kind === "built_up" ? "Fastest growing cities" : "Water change, largest losses first"} subtitle={kind === "built_up" ? "Built-up area, first to last epoch (GHSL)" : "Open water, 1984 versus 2021 (JRC Global Surface Water)"} testid="leaderboard">
          <ol className="divide-y divide-[color:var(--nx-line)]">
            {board.map((r, i) => (
              <li key={r.id} className="flex items-center gap-3 py-2.5 text-[13.5px]">
                <span className="w-6 text-right text-[15px] font-bold tabular-nums text-[color:var(--nx-muted)]">{i + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{r.place}</span>
                  <span className="block truncate text-[12px] text-[color:var(--nx-muted)]">{r.states.join(", ") || "India"} · {unit(r)}</span>
                </span>
                <span className="text-right tabular-nums">
                  <span className={`block text-[15px] font-bold ${r.net_ha < 0 ? "text-[color:var(--nx-loss)]" : "text-[color:var(--nx-gain)]"}`}>{(r.pct ?? 0) >= 0 ? "+" : ""}{fmtNum(r.pct, 1)}%</span>
                  <span className="block text-[12px] text-[color:var(--nx-muted)]">{r.net_ha >= 0 ? "+" : ""}{fmtNum(r.net_ha)} ha</span>
                </span>
              </li>
            ))}
          </ol>
          {kind === "water" && board.every((r) => r.net_ha >= 0) ? <Note>None of the measured water bodies shows a net loss between the two dates; the list starts with the smallest gains. The 1984 record has sparse coverage, so large gains can reflect better observation as well as real change.</Note> : null}
          <div className="mt-3"><Badge tone="official">SATELLITE OBSERVATIONS</Badge></div>
        </Card>
      </div>
    </>
  );
}
