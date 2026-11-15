"use client";

import { ChevronDown, ChevronUp, Send, Sparkles } from "lucide-react";
import { useState } from "react";
import { fmtDate, fmtHa, fmtPct } from "@/lib/explorer/logic";
import type { ChangeSummary, Explanation, Hotspot, ProgressionPoint } from "@/lib/explorer/types";

export interface ChatTurn {
  q: string;
  a: string;
  source: "groq" | "deterministic";
  notice: string | null;
}

interface Props {
  summary: ChangeSummary;
  explanation: Explanation | null;
  explanationState: "loading" | "ready" | "error" | "none";
  activeHotspot: number;
  onHotspot: (i: number) => void;
  turns: ChatTurn[];
  asking: boolean;
  onAsk: (q: string) => void;
  collapsed: boolean;
  onToggle: () => void;
}

function Spark({ data }: { data: ProgressionPoint[] }) {
  if (data.length < 2) return <p className="text-[12px] text-[color:var(--nx-muted)]">Too few yearly composites to draw a progression.</p>;
  const w = 296;
  const h = 84;
  const xs = data.map((d) => d.year);
  const ys = data.map((d) => d.water_ha);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const lo = Math.min(...ys);
  const hi = Math.max(...ys);
  const sx = (x: number) => 6 + ((x - x0) / (x1 - x0 || 1)) * (w - 12);
  const sy = (y: number) => h - 8 - ((y - lo) / (hi - lo || 1)) * (h - 18);
  const path = data.map((d, i) => `${i ? "L" : "M"}${sx(d.year).toFixed(1)},${sy(d.water_ha).toFixed(1)}`).join(" ");
  return (
    <figure>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img" aria-label={`Estimated water area by year, from ${fmtHa(data[0].water_ha, 0)} in ${x0} to ${fmtHa(data[data.length - 1].water_ha, 0)} in ${x1}`}>
        <path d={path} fill="none" stroke="#38bdf8" strokeWidth="2" strokeLinejoin="round" />
        {data.map((d) => (
          <circle key={d.year} cx={sx(d.year)} cy={sy(d.water_ha)} r="2.2" fill="#38bdf8">
            <title>{`${d.year}: ${fmtHa(d.water_ha)} (${d.observations} observations)`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="flex justify-between text-[11px] text-[color:var(--nx-muted)]">
        <span>
          {x0} · {fmtHa(data[0].water_ha, 0)}
        </span>
        <span>
          {x1} · {fmtHa(data[data.length - 1].water_ha, 0)}
        </span>
      </figcaption>
    </figure>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "loss" | "gain" }) {
  return (
    <div className="rounded-lg bg-white/[0.04] px-3 py-2">
      <dt className="text-[11px] uppercase tracking-wide text-[color:var(--nx-muted)]">{label}</dt>
      <dd className={`text-[15px] font-semibold tabular-nums ${tone === "loss" ? "text-[color:var(--nx-loss)]" : tone === "gain" ? "text-[color:var(--nx-gain)]" : ""}`}>{value}</dd>
    </div>
  );
}

export function SummaryPanel(p: Props) {
  const s = p.summary;
  const [q, setQ] = useState("");
  const temporal = s.dataset?.temporal_resolution ?? "monthly";
  const a = s.areas;
  if (p.collapsed) {
    return (
      <button type="button" className="nx-glass nx-rise flex items-center gap-2 px-4 py-2.5 text-[13px] font-semibold" onClick={p.onToggle} aria-expanded={false} data-testid="summary-toggle">
        <ChevronUp className="h-4 w-4" aria-hidden /> Change summary
      </button>
    );
  }
  const hasMeasure = s.outcome !== "insufficient_data";
  return (
    <aside aria-label="Change summary" data-testid="summary-panel" className="nx-glass nx-rise flex max-h-[calc(100dvh-210px)] w-[392px] max-w-[94vw] flex-col overflow-hidden">
      <header className="flex items-start justify-between gap-2 border-b border-[color:var(--nx-line)] px-4 py-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[color:var(--nx-accent)]">Change summary</p>
          <h2 className="text-[15px] font-semibold leading-tight">{s.location_name ?? "Selected location"}</h2>
          <p className="text-[12px] text-[color:var(--nx-muted)]">
            {s.period?.effective ? `${s.period.effective.start_year}–${s.period.effective.end_year}` : "Period not analysed"}
            {s.dataset ? ` · ${s.dataset.temporal_resolution}` : ""}
          </p>
        </div>
        <button type="button" className="nx-ghost !p-1.5" onClick={p.onToggle} aria-label="Collapse summary panel" aria-expanded data-testid="summary-toggle">
          <ChevronDown className="h-4 w-4" aria-hidden />
        </button>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {s.is_synthetic ? (
          <p className="rounded-md border border-amber-400/40 bg-amber-400/10 px-2 py-1 text-[11.5px] font-semibold text-amber-200">{s.simulated_label ?? "SIMULATED DEMONSTRATION DATA"}</p>
        ) : null}

        {hasMeasure ? (
          <dl className="grid grid-cols-2 gap-2" data-testid="summary-stats">
            <Stat label="Area analysed" value={fmtHa(a.analysed_ha)} />
            <Stat label="Net change" value={`${fmtHa(a.net_ha)} (${fmtPct(a.pct_net_change)})`} />
            <Stat label="Water lost" value={fmtHa(a.lost_ha)} tone="loss" />
            <Stat label="Water gained" value={fmtHa(a.gained_ha)} tone="gain" />
          </dl>
        ) : null}

        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12.5px]">
          {s.first_observation ? (
            <>
              <dt className="text-[color:var(--nx-muted)]">First observation</dt>
              <dd>{fmtDate(s.first_observation.date, temporal)} · {s.first_observation.quality}</dd>
            </>
          ) : null}
          {s.last_observation ? (
            <>
              <dt className="text-[color:var(--nx-muted)]">Last observation</dt>
              <dd>{fmtDate(s.last_observation.date, temporal)} · {s.last_observation.quality}</dd>
            </>
          ) : null}
          <dt className="text-[color:var(--nx-muted)]">Source</dt>
          <dd className="leading-snug">{s.dataset?.source ?? "n/a"}</dd>
          {s.most_affected ? (
            <>
              <dt className="text-[color:var(--nx-muted)]">Most affected</dt>
              <dd data-testid="most-affected">{s.most_affected.description}</dd>
            </>
          ) : null}
          {s.confidence ? (
            <>
              <dt className="text-[color:var(--nx-muted)]">Confidence</dt>
              <dd>
                <span className="font-semibold capitalize">{s.confidence}</span> · {s.quality.mean_valid_fraction != null ? `${(s.quality.mean_valid_fraction * 100).toFixed(0)}% valid pixels` : ""}
              </dd>
            </>
          ) : null}
        </dl>

        {s.hotspots.length ? (
          <div>
            <h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-[color:var(--nx-muted)]">Hotspots</h3>
            <ul className="space-y-1" data-testid="hotspot-list">
              {s.hotspots.map((h: Hotspot, i) => (
                <li key={h.id}>
                  <button type="button" className="nx-ghost w-full !justify-start text-left text-[12.5px]" data-active={p.activeHotspot === i} onClick={() => p.onHotspot(i)}>
                    <span className={h.kind === "loss" ? "text-[color:var(--nx-loss)]" : "text-[color:var(--nx-gain)]"}>●</span>
                    <span>
                      #{h.rank} {h.description}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {s.progression.length ? (
          <div>
            <h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-[color:var(--nx-muted)]">Progression (same-season water area)</h3>
            <Spark data={s.progression} />
            {s.trend ? (
              <p className="mt-1 text-[11.5px] text-[color:var(--nx-muted)]">
                Trend: {s.trend.direction} ({s.trend.slope_ha_per_year > 0 ? "+" : ""}
                {s.trend.slope_ha_per_year.toFixed(2)} ha per year, p = {s.trend.p_value}).
              </p>
            ) : null}
          </div>
        ) : null}

        <div data-testid="explanation">
          <h3 className="mb-1 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-[color:var(--nx-muted)]">
            <Sparkles className="h-3.5 w-3.5" aria-hidden /> Explanation
            {p.explanation ? (
              <span className="rounded-full border border-[color:var(--nx-line)] px-2 py-0.5 text-[10px] normal-case tracking-normal" data-testid="explanation-source">
                {p.explanation.source === "groq" ? `AI · ${p.explanation.model}` : "Generated from the measurements"}
              </span>
            ) : null}
          </h3>
          {p.explanationState === "loading" ? <div className="h-16 animate-pulse rounded-md bg-white/5" aria-label="Writing the explanation" /> : null}
          {p.explanationState === "error" ? <p className="text-[12.5px] text-amber-200">The explanation could not be generated. The measurements above are unaffected.</p> : null}
          {p.explanation ? (
            <>
              <p className="whitespace-pre-line text-[13px] leading-relaxed text-[color:var(--nx-soft)]">{p.explanation.text}</p>
              {p.explanation.notice ? <p className="mt-1 text-[11px] text-[color:var(--nx-muted)]">{p.explanation.notice}</p> : null}
            </>
          ) : null}
        </div>

        {s.limitations.length ? (
          <details className="text-[12px] text-[color:var(--nx-muted)]">
            <summary className="cursor-pointer font-semibold text-[color:var(--nx-soft)]">Confidence and limitations</summary>
            <ul className="mt-1 list-disc space-y-1 pl-5">
              {s.confidence_reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
              {s.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </details>
        ) : null}

        {s.analysis_id ? (
          <div>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (q.trim() && !p.asking) {
                  p.onAsk(q.trim());
                  setQ("");
                }
              }}
            >
              <label className="sr-only" htmlFor="nx-ask">
                Ask about this result
              </label>
              <input id="nx-ask" className="nx-input min-w-0 flex-1 text-[13px]" placeholder="Ask: where did it change? how fast?" value={q} maxLength={600} onChange={(e) => setQ(e.target.value)} />
              <button type="submit" className="nx-btn !px-3" disabled={p.asking || !q.trim()} aria-label="Ask">
                <Send className="h-4 w-4" aria-hidden />
              </button>
            </form>
            <ul className="mt-2 space-y-2" data-testid="chat-turns">
              {p.turns.map((t, i) => (
                <li key={i} className="rounded-lg bg-white/[0.04] p-2.5 text-[12.5px]">
                  <p className="font-semibold text-[color:var(--nx-soft)]">{t.q}</p>
                  <p className="mt-1 leading-relaxed text-[color:var(--nx-soft)]">{t.a}</p>
                  <p className="mt-1 text-[10.5px] text-[color:var(--nx-muted)]">{t.source === "groq" ? "AI answer from measured results" : "Answered from the measurements"}</p>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </aside>
  );
}
