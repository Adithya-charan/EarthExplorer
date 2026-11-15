"use client";

import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useMemo, useRef } from "react";
import { fmtDate, nearestIndex, PLAY_SPEEDS, timelinePositions } from "@/lib/explorer/logic";
import type { ObservationInfo } from "@/lib/explorer/types";

interface Props {
  observations: ObservationInfo[];
  temporal: string;
  index: number;
  active: boolean; // the cursor is driving the map
  onIndex: (i: number) => void;
  playing: boolean;
  onPlay: () => void;
  speed: number;
  onSpeed: (s: number) => void;
  onPrev: () => void;
  onNext: () => void;
  simulated: boolean;
}

const QUALITY_COLOR = { good: "#38bdf8", fair: "#fbbf24", poor: "#fb7185" } as const;

/**
 * Bottom timeline. Every tick is a real observation, placed by its date, so gaps in the record are visible as gaps and
 * the cursor can only land on dates that exist. Nothing between observations is interpolated.
 */
export function Timeline(p: Props) {
  const trackRef = useRef<HTMLDivElement>(null);
  const dates = useMemo(() => p.observations.map((o) => o.date), [p.observations]);
  const pos = useMemo(() => timelinePositions(dates), [dates]);
  const n = p.observations.length;
  const cur = p.observations[Math.min(p.index, n - 1)];

  const years = useMemo(() => {
    if (!n) return [] as { y: number; x: number }[];
    const first = Number(dates[0].slice(0, 4));
    const last = Number(dates[n - 1].slice(0, 4));
    const step = Math.max(1, Math.ceil((last - first) / 8));
    const out: { y: number; x: number }[] = [];
    for (let y = first; y <= last; y += step) {
      const t = Date.UTC(y, 0, 1) / 86_400_000;
      const t0 = Date.UTC(first, Number(dates[0].slice(5, 7)) - 1, 1) / 86_400_000;
      const t1 = Date.UTC(last, Number(dates[n - 1].slice(5, 7)) - 1, 1) / 86_400_000;
      out.push({ y, x: Math.min(1, Math.max(0, (t - t0) / (t1 - t0 || 1))) });
    }
    return out;
  }, [dates, n]);

  const pick = (clientX: number) => {
    const r = trackRef.current?.getBoundingClientRect();
    if (!r || !n) return;
    p.onIndex(nearestIndex(pos, (clientX - r.left) / r.width));
  };

  if (!n) return null;
  return (
    <section aria-label="Observation timeline" data-testid="timeline" className="nx-glass nx-rise w-[min(1040px,96vw)] px-4 pb-3 pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="nx-ghost" aria-label="Previous observation" onClick={p.onPrev} disabled={p.index <= 0}>
          <SkipBack className="h-4 w-4" aria-hidden />
        </button>
        <button type="button" className="nx-btn !px-3 !py-1.5" aria-label={p.playing ? "Pause animation" : "Play historical animation"} onClick={p.onPlay} data-testid="play">
          {p.playing ? <Pause className="h-4 w-4" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}
        </button>
        <button type="button" className="nx-ghost" aria-label="Next observation" onClick={p.onNext} disabled={p.index >= n - 1}>
          <SkipForward className="h-4 w-4" aria-hidden />
        </button>
        <div className="ml-1 flex items-center gap-0.5" role="group" aria-label="Playback speed">
          {PLAY_SPEEDS.map((s) => (
            <button key={s} type="button" className="nx-ghost !px-2 !py-1 text-[12px]" aria-pressed={p.speed === s} onClick={() => p.onSpeed(s)}>
              {s}×
            </button>
          ))}
        </div>
        <div className="ml-auto text-right" data-testid="timeline-readout">
          <span className="text-[15px] font-semibold">{fmtDate(cur.date, p.temporal)}</span>
          <span className="ml-2 text-[12px]" style={{ color: QUALITY_COLOR[cur.quality] }}>
            {cur.quality} · {(cur.valid_fraction * 100).toFixed(0)}% valid
          </span>
          <span className="ml-2 text-[11px] text-[color:var(--nx-muted)]">
            {p.index + 1} of {n}
            {p.simulated ? " · simulated" : ""}
          </span>
        </div>
      </div>

      <div
        ref={trackRef}
        role="slider"
        tabIndex={0}
        aria-label="Observation date"
        aria-valuemin={0}
        aria-valuemax={n - 1}
        aria-valuenow={p.index}
        aria-valuetext={`${fmtDate(cur.date, p.temporal)}, quality ${cur.quality}`}
        data-testid="timeline-track"
        className={`relative mt-3 h-9 cursor-pointer touch-none select-none rounded-lg ${p.active ? "bg-sky-400/10" : "bg-white/5"}`}
        onPointerDown={(e) => {
          (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
          pick(e.clientX);
        }}
        onPointerMove={(e) => {
          if (e.buttons & 1) pick(e.clientX);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight" || e.key === "ArrowUp") p.onNext();
          else if (e.key === "ArrowLeft" || e.key === "ArrowDown") p.onPrev();
          else if (e.key === "Home") p.onIndex(0);
          else if (e.key === "End") p.onIndex(n - 1);
          else return;
          e.preventDefault();
        }}
      >
        {p.observations.map((o, i) => (
          <span
            key={o.date}
            data-testid="tick"
            title={`${fmtDate(o.date, p.temporal)} · ${o.quality}`}
            className="absolute top-2 h-5 w-[3px] -translate-x-1/2 rounded-full"
            style={{
              left: `${pos[i] * 100}%`,
              background: o.quality === "poor" ? "transparent" : QUALITY_COLOR[o.quality],
              border: o.quality === "poor" ? `1px solid ${QUALITY_COLOR.poor}` : undefined,
              opacity: i === p.index ? 1 : 0.55,
            }}
          />
        ))}
        <span
          aria-hidden
          className="absolute top-0.5 h-8 w-[3px] -translate-x-1/2 rounded-full bg-white shadow-[0_0_12px_2px_rgba(255,255,255,0.7)]"
          style={{ left: `${pos[Math.min(p.index, n - 1)] * 100}%` }}
          data-testid="cursor"
        />
      </div>
      <div className="relative mt-1 h-4 text-[10.5px] text-[color:var(--nx-muted)]" aria-hidden>
        {years.map((t) => (
          <span key={t.y} className="absolute -translate-x-1/2" style={{ left: `${t.x * 100}%` }}>
            {t.y}
          </span>
        ))}
      </div>
      <p className="mt-1 text-[11px] text-[color:var(--nx-muted)]">Each mark is an observation that exists. Gaps are dates with no data; nothing is interpolated. Hollow marks are poor-quality observations.</p>
    </section>
  );
}
