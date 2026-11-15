"use client";

import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Info, Layers, Loader2, Sparkles } from "lucide-react";
import { cap, dataLabel, fmtDate, fmtHa, isIllustrative, OUTCOME_COPY } from "@/lib/explorer/logic";
import type { ChangeSummary, DatasetInfo, Hotspot, LatestObservation, LocationOut, MapMode, SessionResponse } from "@/lib/explorer/types";

export type Phase = "idle" | "locating" | "flying" | "analysing" | "ready" | "error";

const PHASE_TEXT: Record<Phase, string> = {
  idle: "",
  locating: "Finding the place…",
  flying: "Travelling to the location…",
  analysing: "Checking observations and measuring change…",
  ready: "",
  error: "",
};

export function StatusPill({ phase, name }: { phase: Phase; name: string | null }) {
  const text = PHASE_TEXT[phase];
  if (!text) return null;
  return (
    <div role="status" aria-live="polite" data-testid="status-pill" className="nx-glass nx-rise pointer-events-none flex items-center gap-2 px-4 py-2 text-[13px] text-[color:var(--nx-soft)]">
      <Loader2 className="nx-spin h-4 w-4 text-[color:var(--nx-accent)]" aria-hidden />
      <span>{phase === "flying" && name ? `Travelling to ${name}…` : text}</span>
    </div>
  );
}

export function LatestCard({ latest, session }: { latest: LatestObservation; session: SessionResponse }) {
  const q = { good: "text-emerald-300", fair: "text-amber-300", poor: "text-rose-300" }[latest.quality];
  return (
    <section aria-label="Latest available observation" data-testid="latest-card" className="nx-glass nx-rise w-[300px] max-w-[88vw] p-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[color:var(--nx-accent)]">{latest.label}</p>
      <p className="mt-1 text-lg font-semibold leading-tight">
        {fmtDate(latest.date, latest.temporal_resolution)} <span className="text-sm font-normal text-[color:var(--nx-muted)]">· {latest.location}</span>
      </p>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[12.5px]">
        <dt className="text-[color:var(--nx-muted)]">Observed</dt>
        <dd>{latest.date}</dd>
        <dt className="text-[color:var(--nx-muted)]">Source</dt>
        <dd className="leading-snug">{latest.source}</dd>
        <dt className="text-[color:var(--nx-muted)]">Resolution</dt>
        <dd>{latest.spatial_resolution_m.toFixed(0)} m per pixel · {latest.temporal_resolution}</dd>
        <dt className="text-[color:var(--nx-muted)]">Quality</dt>
        <dd className={q}>
          {latest.quality} · {(latest.valid_fraction * 100).toFixed(0)}% valid pixels
        </dd>
        <dt className="text-[color:var(--nx-muted)]">Coverage</dt>
        <dd>
          {latest.historical_coverage.start.slice(0, 7)} to {latest.historical_coverage.end.slice(0, 7)}
        </dd>
      </dl>
      {latest.is_synthetic ? (
        <p data-testid="simulated-tag" className="mt-3 rounded-md border border-amber-400/40 bg-amber-400/10 px-2 py-1 text-[11.5px] font-semibold text-amber-200">
          {latest.simulated_label ?? "Illustrative Dataset: a generated demonstration layer, not satellite imagery."}
        </p>
      ) : null}
      <p className="mt-2 text-[11.5px] leading-snug text-[color:var(--nx-muted)]">{latest.note}</p>
      <span className="sr-only">{session.message}</span>
    </section>
  );
}

interface BannerProps {
  summary: ChangeSummary | null;
  session: SessionResponse | null;
  onUseSuggestion: (start: number, end: number) => void;
  onExploreAnyway: () => void;
  onExample: (q: string) => void;
  exploredAnyway: boolean;
}

/** One banner for every result: A change detected, B no clear change, C insufficient data, or a lookup problem. */
export function OutcomeBanner({ summary, session, onUseSuggestion, onExploreAnyway, onExample, exploredAnyway }: BannerProps) {
  if (session?.status === "not_found") {
    return (
      <div role="alert" data-testid="banner-not-found" className="nx-glass nx-rise w-[560px] max-w-[92vw] border-amber-400/30 p-4">
        <p className="flex items-center gap-2 font-semibold text-amber-200">
          <AlertTriangle className="h-4 w-4" aria-hidden /> Place not found
        </p>
        <p className="mt-1 text-[13px] text-[color:var(--nx-soft)]">{session.message}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {session.examples.map((e) => (
            <button key={e} type="button" className="nx-chip" onClick={() => onExample(e)}>
              {e}
            </button>
          ))}
        </div>
      </div>
    );
  }
  const ins = summary?.insufficient ?? session?.insufficient ?? null;
  const outcome = summary?.outcome ?? (ins ? "insufficient_data" : null);
  if (!outcome) return null;
  const copy = OUTCOME_COPY[outcome];
  const tone =
    copy.tone === "change" ? "border-[color:var(--nx-warn)]/50" : copy.tone === "calm" ? "border-sky-400/40" : "border-orange-400/50";
  const Icon = copy.tone === "change" ? Sparkles : copy.tone === "calm" ? CheckCircle2 : AlertTriangle;
  const iconColor = copy.tone === "change" ? "text-amber-300" : copy.tone === "calm" ? "text-sky-300" : "text-orange-300";
  return (
    <div role="status" aria-live="polite" data-testid={`banner-${outcome}`} className={`nx-glass nx-rise w-[620px] max-w-[92vw] p-4 ${tone}`}>
      <p className={`flex items-center gap-2 text-[13px] font-semibold uppercase tracking-[0.1em] ${iconColor}`}>
        <Icon className="h-4 w-4" aria-hidden /> {session?.status === "no_dataset" ? "Data Unavailable" : copy.badge}
      </p>
      <p className="mt-1 text-[15px] font-medium leading-snug">{summary?.headline ?? session?.message}</p>
      {outcome === "no_clear_change" && summary ? (
        <>
          <p className="mt-2 text-[13px] text-[color:var(--nx-soft)]">{summary.what_was_analysed}</p>
          {!exploredAnyway ? (
            <button type="button" className="nx-chip mt-3" onClick={onExploreAnyway}>
              <Layers className="h-3.5 w-3.5" aria-hidden /> Explore the observations anyway
            </button>
          ) : null}
        </>
      ) : null}
      {outcome === "insufficient_data" && ins ? (
        <div className="mt-2 text-[13px] text-[color:var(--nx-soft)]">
          <p>{ins.reason}</p>
          {ins.missing.filter(Boolean).length ? (
            <ul className="mt-2 list-disc space-y-0.5 pl-5">
              {ins.missing.filter(Boolean).map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          ) : null}
          {ins.available_dates.length ? (
            <p className="mt-2 text-[color:var(--nx-muted)]">
              Usable observation dates: {ins.available_dates.slice(0, 12).join(", ")}
              {ins.available_dates.length > 12 ? ` … (${ins.available_dates.length} in all)` : ""}
            </p>
          ) : null}
          <p className="mt-2 text-[12px] text-[color:var(--nx-muted)]">This is not a finding of “no change”: the data needed to decide are missing.</p>
          {ins.suggested_period ? (
            <button type="button" className="nx-chip mt-3" onClick={() => onUseSuggestion(ins.suggested_period!.start_year, ins.suggested_period!.end_year)}>
              Try {ins.suggested_period.start_year}–{ins.suggested_period.end_year}, the period with enough observations
            </button>
          ) : null}
        </div>
      ) : null}
      {outcome === "change_detected" && summary?.most_affected ? (
        <p className="mt-2 text-[13px] text-[color:var(--nx-soft)]">
          Most affected: <strong className="text-white">{summary.most_affected.description}</strong>. Moving in on the biggest change…
        </p>
      ) : null}
      {summary?.period?.messages?.length ? (
        <p className="mt-2 flex gap-2 text-[12px] text-[color:var(--nx-muted)]">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {summary.period.messages.join(" ")}
        </p>
      ) : null}
    </div>
  );
}

/** Extra context under the outcome banner: other places with the same name, or data that exists inside a larger area. */
export function PlaceNotice({ session, onPickPlace, onOpenDataset, onExample }: { session: SessionResponse | null; onPickPlace: (l: LocationOut) => void; onOpenDataset: (d: DatasetInfo) => void; onExample?: (q: string) => void }) {
  if (!session || session.status === "not_found" || !session.location) return null;
  const alts = session.status === "ambiguous" ? session.alternatives.filter((a) => a.name.toLowerCase() === session.location!.name.toLowerCase()) : [];
  const nearby = session.status === "no_dataset" ? session.nearby_datasets : [];
  const suggest = session.status === "no_dataset" && nearby.length === 0 && onExample ? session.examples : [];
  if (alts.length === 0 && nearby.length === 0 && suggest.length === 0) return null;
  return (
    <div className="nx-glass nx-rise w-[620px] max-w-[92vw] p-3" data-testid="place-notice">
      {alts.length ? (
        <>
          <p className="text-[12.5px] text-[color:var(--nx-soft)]">Several places share this name. Did you mean:</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {alts.map((a) => (
              <button key={a.id} type="button" className="nx-chip" onClick={() => onPickPlace(a)}>
                {a.display_name}
              </button>
            ))}
          </div>
        </>
      ) : null}
      {suggest.length ? (
        <>
          <p className="text-[12.5px] text-[color:var(--nx-soft)]">Places with satellite observations:</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {suggest.map((e) => (
              <button key={e} type="button" className="nx-chip" onClick={() => onExample?.(e)}>{e}</button>
            ))}
          </div>
        </>
      ) : null}
      {nearby.length ? (
        <>
          <p className="text-[12.5px] text-[color:var(--nx-soft)]">Places with satellite observations in or near this area. Open one:</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {nearby.map((d) => (
              <button key={d.id} type="button" className="nx-chip" onClick={() => onOpenDataset(d)} data-testid="nearby-dataset">
                <span className={isIllustrative(d) ? "text-amber-200" : "text-emerald-300"}>●</span> {d.name.replace(/ \((?:illustrative|simulated)[^)]*\)$/i, "")} · {dataLabel(d)}
              </button>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

const MODES: { id: MapMode; label: string; needs: "none" | "analysis" }[] = [
  { id: "latest", label: "Latest", needs: "none" },
  { id: "history", label: "History", needs: "none" },
  { id: "beforeafter", label: "Before / after", needs: "analysis" },
  { id: "swipe", label: "Swipe", needs: "analysis" },
  { id: "difference", label: "Difference", needs: "analysis" },
  { id: "hotspots", label: "Hotspots", needs: "analysis" },
];

export function ModeBar({ mode, onMode, hasAnalysis, baShowAfter, onToggleBA }: { mode: MapMode; onMode: (m: MapMode) => void; hasAnalysis: boolean; baShowAfter: boolean; onToggleBA: () => void }) {
  return (
    <div className="nx-glass nx-rise flex flex-wrap items-center gap-1 p-1.5" role="group" aria-label="Map mode" data-testid="mode-bar">
      {MODES.map((m) => {
        const disabled = m.needs === "analysis" && !hasAnalysis;
        return (
          <button key={m.id} type="button" className="nx-ghost text-[13px]" aria-pressed={mode === m.id} disabled={disabled} title={disabled ? "Needs a completed analysis" : undefined} onClick={() => onMode(m.id)}>
            {m.label}
          </button>
        );
      })}
      {mode === "beforeafter" ? (
        <button type="button" className="nx-chip ml-1" onClick={onToggleBA} data-testid="ba-toggle">
          Showing {baShowAfter ? "after" : "before"} · switch
        </button>
      ) : null}
    </div>
  );
}

export function HotspotNav({ hotspots, active, onPick, onOverview }: { hotspots: Hotspot[]; active: number; onPick: (i: number) => void; onOverview: () => void }) {
  if (hotspots.length === 0) return null;
  const h = active >= 0 ? hotspots[active] : null;
  return (
    <div className="nx-glass nx-rise flex items-center gap-1 p-1.5" data-testid="hotspot-nav" role="group" aria-label="Change hotspots">
      <button type="button" className="nx-ghost" aria-label="Previous hotspot" onClick={() => onPick(active <= 0 ? hotspots.length - 1 : active - 1)}>
        <ChevronLeft className="h-4 w-4" aria-hidden />
      </button>
      <button type="button" className="nx-ghost min-w-[190px] text-left text-[13px]" onClick={() => (h ? onOverview() : onPick(0))} title={h ? "Back to the whole area" : "Zoom to the biggest change"}>
        {h ? (
          <span>
            <span className={h.kind === "loss" ? "text-[color:var(--nx-loss)]" : "text-[color:var(--nx-gain)]"}>●</span> #{h.rank} {h.region} · {fmtHa(h.area_ha)} {h.kind === "loss" ? "lost" : "gained"}
          </span>
        ) : (
          <span>
            {hotspots.length} hotspot{hotspots.length === 1 ? "" : "s"} · zoom in
          </span>
        )}
      </button>
      <button type="button" className="nx-ghost" aria-label="Next hotspot" onClick={() => onPick(active + 1 >= hotspots.length ? 0 : active + 1)}>
        <ChevronRight className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}

// Same colours as the raster palette in backend/app/explorer/rendering.py.
const CLASS_COLOR: Record<string, string> = {
  "1": "#a89678", "2": "#328cff", "3": "#4a8c50", "4": "#d67650", "5": "#f0f6ff", "6": "#96d6ec", "7": "#c4b278", "8": "#186e46", "9": "#d6c460", "10": "#78c85a", "11": "#60a896",
};

export function Legend({ kind, simulated, classes, variableLabel }: { kind: "diff" | "classes"; simulated: boolean; classes?: Record<string, string>; variableLabel?: string }) {
  const vl = cap(variableLabel ?? "water");
  const rows: string[][] =
    kind === "diff"
      ? [
          ["#388bfd", `${vl} (unchanged)`],
          ["#e63946", `${vl} lost`],
          ["#2ecc71", `${vl} gained`],
          ["#7a808c", "Unchanged other"],
        ]
      : Object.entries(classes ?? { "2": "Water", "3": "Vegetation", "4": "Built-up", "1": "Other land" })
          .filter(([k]) => k !== "255")
          .map(([k, label]) => [CLASS_COLOR[k] ?? "#888", label]);
  return (
    <aside aria-label="Legend" data-testid="legend" className="nx-glass nx-rise w-[196px] p-3 text-[12px]">
      <ul className="space-y-1">
        {rows.map(([c, l]) => (
          <li key={l} className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-sm" style={{ background: c }} aria-hidden />
            {l}
          </li>
        ))}
        <li className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-sm border border-slate-300/60" style={{ background: "repeating-linear-gradient(135deg, rgba(205,215,232,0.7) 0 2px, transparent 2px 5px)" }} aria-hidden />
          Uncertain (cloud / no data)
        </li>
      </ul>
      {simulated ? <p className="mt-2 border-t border-[color:var(--nx-line)] pt-2 text-[11px] font-semibold text-amber-200">Illustrative Dataset</p> : null}
    </aside>
  );
}
