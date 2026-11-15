"use client";

import { ArrowLeft, ArrowRight, Loader2, Mic, MicOff, Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { explorerApi } from "@/lib/explorer/api";
import { dataLabel, levelName, yearOptions } from "@/lib/explorer/logic";
import type { DatasetInfo, LocationOut } from "@/lib/explorer/types";
import { VOICE_EXAMPLES } from "@/lib/explorer/voice";

// A fixed upper bound: reading the clock during render would make the prerendered page stale.
const MAX_YEAR = 2026;

export const EXAMPLES = ["Bellandur Lake, Bengaluru", "Hyderabad", "Sundarbans", "Himalayas", "Uttarakhand"];

export interface VoiceUi {
  supported: boolean;
  listening: boolean;
  /** What was heard so far, shown while listening. */
  heard: string;
  onToggle: () => void;
  /** Result of the last command: what was understood, or why it failed. */
  note: { tone: "info" | "ok" | "error"; text: string } | null;
}

interface Props {
  query: string;
  onQuery: (q: string) => void;
  startYear: number;
  endYear: number;
  onStart: (y: number) => void;
  onEnd: (y: number) => void;
  onSubmit: () => void;
  onExample: (q: string) => void;
  onPick: (loc: LocationOut) => void;
  busy: boolean;
  compact: boolean;
  datasets: DatasetInfo[] | null;
  datasetsError: boolean;
  canBack: boolean;
  canForward: boolean;
  onBack: () => void;
  onForward: () => void;
  voice: VoiceUi;
}

export function SearchPanel(p: Props) {
  const id = useId();
  const years = yearOptions(1980, MAX_YEAR);
  const invalid = p.startYear >= p.endYear;
  const [sugg, setSugg] = useState<LocationOut[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [loadingSugg, setLoadingSugg] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const skip = useRef(false);
  /** The text that was last submitted or chosen: suggestions that arrive late for it must not reopen the list. */
  const closedFor = useRef<string | null>(null);

  // Suggestions while typing: debounced, offline-first on the server, and never allowed to block the search box.
  useEffect(() => {
    const q = p.query.trim();
    if (skip.current) {
      skip.current = false;
      return;
    }
    const c = new AbortController();
    const t = setTimeout(() => {
      if (q.length < 2) {
        setSugg([]);
        setOpen(false);
        return;
      }
      setLoadingSugg(true);
      explorerApi
        .suggest(q, c.signal)
        .then((r) => {
          if (closedFor.current === q) return;
          setSugg(r);
          setActive(-1);
          setOpen(r.length > 0);
        })
        .catch(() => {
          if (!c.signal.aborted) setSugg([]);
        })
        .finally(() => !c.signal.aborted && setLoadingSugg(false));
    }, 180);
    return () => {
      clearTimeout(t);
      c.abort();
    };
  }, [p.query]);

  const choose = (loc: LocationOut) => {
    skip.current = true;
    closedFor.current = loc.name.trim();
    setOpen(false);
    setSugg([]);
    p.onPick(loc);
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || sugg.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % sugg.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a <= 0 ? sugg.length - 1 : a - 1));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      choose(sugg[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const v = p.voice;
  return (
    <div className="flex w-[760px] max-w-[94vw] flex-col items-stretch gap-2">
      <form
        className="nx-glass flex flex-wrap items-center gap-2 p-2.5"
        role="search"
        aria-label="Search a place"
        onSubmit={(e) => {
          e.preventDefault();
          closedFor.current = p.query.trim();
          setOpen(false);
          if (!invalid && p.query.trim()) p.onSubmit();
        }}
      >
        <div className="flex items-center gap-1" role="group" aria-label="Location history">
          <button type="button" className="nx-ghost !p-2" onClick={p.onBack} disabled={!p.canBack || p.busy} aria-label="Back to the previous location" title="Back">
            <ArrowLeft className="h-4 w-4" aria-hidden />
          </button>
          <button type="button" className="nx-ghost !p-2" onClick={p.onForward} disabled={!p.canForward || p.busy} aria-label="Forward to the next location" title="Forward">
            <ArrowRight className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <label htmlFor={`${id}-q`} className="sr-only">
          Place name or command
        </label>
        <div className="relative min-w-[200px] flex-[1_1_260px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--nx-muted)]" aria-hidden />
          <input
            id={`${id}-q`}
            className="nx-input w-full pl-9 pr-9"
            placeholder="Search a place, lake, city, region or say a command…"
            value={p.query}
            maxLength={200}
            autoComplete="off"
            role="combobox"
            aria-expanded={open}
            aria-controls={`${id}-list`}
            aria-autocomplete="list"
            aria-activedescendant={active >= 0 ? `${id}-opt-${active}` : undefined}
            onChange={(e) => {
              closedFor.current = null;
              p.onQuery(e.target.value);
            }}
            onKeyDown={onKey}
            onFocus={() => sugg.length > 0 && setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 120)}
          />
          {loadingSugg ? <Loader2 className="nx-spin absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--nx-muted)]" aria-hidden /> : null}
          {open && sugg.length > 0 ? (
            <ul id={`${id}-list`} role="listbox" aria-label="Place suggestions" data-testid="suggestions" className="nx-glass absolute left-0 right-0 top-[calc(100%+6px)] z-40 max-h-[320px] overflow-y-auto p-1 !bg-[rgba(7,14,30,0.98)]">
              {sugg.map((s, i) => (
                <li key={s.id} id={`${id}-opt-${i}`} role="option" aria-selected={i === active}>
                  <button type="button" className="nx-ghost w-full !justify-between text-left" data-active={i === active} onMouseDown={(e) => e.preventDefault()} onClick={() => choose(s)}>
                    <span className="min-w-0">
                      <span className="block truncate text-[13.5px] font-semibold">{s.name}</span>
                      <span className="block truncate text-[11.5px] text-[color:var(--nx-muted)]">{[...s.hierarchy].reverse().join(", ") || s.source}</span>
                    </span>
                    <span className="nx-chip !px-2 !py-0.5 !text-[10.5px]">{levelName(s.level)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        {v.supported ? (
          <button
            type="button"
            className={`nx-ghost !p-2 ${v.listening ? "nx-listening" : ""}`}
            onClick={v.onToggle}
            aria-pressed={v.listening}
            aria-label={v.listening ? "Stop listening" : "Speak a command"}
            title={v.listening ? "Stop listening" : "Speak a command"}
            data-testid="mic"
          >
            {v.listening ? <Mic className="h-4 w-4 text-[color:var(--nx-accent)]" aria-hidden /> : <MicOff className="h-4 w-4" aria-hidden />}
          </button>
        ) : null}
        <label className="flex items-center gap-1.5 text-[12px] text-[color:var(--nx-muted)]" htmlFor={`${id}-s`}>
          From
          <select id={`${id}-s`} className="nx-input py-2" value={p.startYear} onChange={(e) => p.onStart(Number(e.target.value))}>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-[12px] text-[color:var(--nx-muted)]" htmlFor={`${id}-e`}>
          To
          <select id={`${id}-e`} className="nx-input py-2" value={p.endYear} onChange={(e) => p.onEnd(Number(e.target.value))}>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="nx-btn" disabled={p.busy || invalid || !p.query.trim()}>
          {p.busy ? "Working…" : "Explore"}
        </button>
        {invalid ? (
          <p role="alert" className="basis-full px-1 text-[12px] text-amber-200">
            The start year must be earlier than the end year.
          </p>
        ) : null}
      </form>

      {v.listening || v.note ? (
        <div className="flex flex-wrap items-center justify-center gap-2" data-testid="voice-feedback">
          {v.listening ? (
            <p role="status" aria-live="polite" className="nx-glass nx-rise flex items-center gap-2 px-3 py-1.5 text-[12.5px]">
              <span className="nx-dot" aria-hidden /> Listening… {v.heard ? <span className="text-[color:var(--nx-soft)]">“{v.heard}”</span> : <span className="text-[color:var(--nx-muted)]">say a command</span>}
            </p>
          ) : null}
          {v.note ? (
            <p
              role={v.note.tone === "error" ? "alert" : "status"}
              className={`nx-glass nx-rise px-3 py-1.5 text-[12.5px] ${v.note.tone === "error" ? "border-rose-400/40 text-rose-200" : v.note.tone === "ok" ? "text-emerald-200" : "text-[color:var(--nx-soft)]"}`}
              data-testid="voice-note"
            >
              {v.note.text}
            </p>
          ) : null}
        </div>
      ) : null}

      {!p.compact ? (
        <div className="nx-rise flex flex-col items-center gap-2 text-center">
          <p className="text-[12.5px] text-[color:var(--nx-muted)]">Search a place, choose a period, then Explore. Drag to turn the globe, scroll to zoom.</p>
          <div className="flex flex-wrap justify-center gap-2" aria-label="Example locations">
            {EXAMPLES.map((e) => (
              <button key={e} type="button" className="nx-chip" onClick={() => p.onExample(e)} disabled={p.busy}>
                {e}
              </button>
            ))}
          </div>
          <button type="button" className="text-[12px] text-[color:var(--nx-muted)] underline-offset-2 hover:underline" aria-expanded={helpOpen} onClick={() => setHelpOpen((o) => !o)}>
            {helpOpen ? "Hide" : "Show"} voice and text commands
          </button>
          {helpOpen ? (
            <ul className="nx-glass nx-rise grid max-w-[620px] grid-cols-1 gap-x-6 gap-y-1 p-3 text-left text-[12px] text-[color:var(--nx-soft)] sm:grid-cols-2" data-testid="voice-help">
              {VOICE_EXAMPLES.map((x) => (
                <li key={x}>“{x}”</li>
              ))}
            </ul>
          ) : null}
          <DatasetAvailability datasets={p.datasets} error={p.datasetsError} />
        </div>
      ) : null}
    </div>
  );
}

export function DatasetAvailability({ datasets, error }: { datasets: DatasetInfo[] | null; error: boolean }) {
  if (error) return <p className="text-[12px] text-amber-200" data-testid="availability">Dataset availability could not be loaded. Is the backend running?</p>;
  if (!datasets) return <p className="text-[12px] text-[color:var(--nx-muted)]" data-testid="availability">Checking which datasets are available…</p>;
  if (datasets.length === 0) return <p className="text-[12px] text-amber-200" data-testid="availability">No datasets are loaded, so no location has observations.</p>;
  return (
    <p className="max-w-[720px] text-[12px] leading-relaxed text-[color:var(--nx-muted)]" data-testid="availability">
      <span className="font-semibold text-[color:var(--nx-soft)]">Historical layers: </span>
      {datasets.map((d, i) => (
        <span key={d.id}>
          {i > 0 ? " · " : ""}
          {d.name.replace(/ \((?:illustrative|simulated)[^)]*\)$/i, "")} {d.coverage.start.slice(0, 4)}–{d.coverage.end.slice(0, 4)} ({dataLabel(d)})
        </span>
      ))}
      . Other places can be shown on the globe, but have no observations to compare.
    </p>
  );
}
