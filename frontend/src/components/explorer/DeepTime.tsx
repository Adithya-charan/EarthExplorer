"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Flame, Loader2, Mountain, Pause, Play, RotateCcw, Search, Send, X } from "lucide-react";
import { explorerApi } from "@/lib/explorer/api";
import {
  LABELLED_AGES, MODE_LABELS, fmtLatLon, formatAge, formatMa, periodColor,
  type AppEra, type DeepModel, type DeepView, type FossilProps,
} from "@/lib/explorer/deeptime";
import type { LocationOut } from "@/lib/explorer/types";
import type { DeepTime } from "./useDeepTime";

/** Earth Today / Historical Earth / Deep-Time Earth. The first two are the existing satellite modes. */
export function EraSwitch({ era, onEra }: { era: AppEra; onEra: (e: AppEra) => void }) {
  const items: { id: AppEra; hint: string }[] = [
    { id: "today", hint: "Latest satellite observation" },
    { id: "historical", hint: "Satellite observations through the years" },
    { id: "deep", hint: "Geological reconstruction, millions of years" },
  ];
  return (
    <div className="nx-glass flex flex-col gap-1 p-1.5" role="radiogroup" aria-label="Time scale" data-testid="era-switch">
      {items.map((i) => (
        <button key={i.id} type="button" role="radio" aria-checked={era === i.id} title={i.hint} data-testid={`era-${i.id}`} onClick={() => onEra(i.id)} className={`nx-ghost !justify-start text-[12.5px] ${era === i.id ? "!bg-white/15 font-semibold" : ""}`}>
          {MODE_LABELS[i.id]}
        </button>
      ))}
    </div>
  );
}

const VIEWS: { id: DeepView; label: string }[] = [
  { id: "reconstruction", label: "Geological Reconstruction" },
  { id: "fossils", label: "Fossil Discoveries" },
  { id: "formations", label: "Geological Formation" },
];

/** Search in Deep-Time Earth: same gazetteer as satellite mode; the result is a reference point mapped onto the plate. */
export function DeepSearch({ dt }: { dt: DeepTime }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<LocationOut[]>([]);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const t = q.trim();
    if (t.length < 2) return;
    const c = new AbortController();
    const id = setTimeout(() => {
      explorerApi.suggest(t, c.signal).then((h) => !c.signal.aborted && setHits(h.slice(0, 6))).catch(() => undefined);
    }, 180);
    return () => {
      clearTimeout(id);
      c.abort();
    };
  }, [q]);
  const shown = q.trim().length >= 2 ? hits : [];
  return (
    <div className="relative w-[min(480px,92vw)]" data-testid="deep-search">
      <form
        className="nx-glass flex items-center gap-2 px-3 py-2"
        onSubmit={(e) => {
          e.preventDefault();
          void dt.searchPlace(q);
          setOpen(false);
        }}
      >
        <Search className="h-4 w-4 shrink-0 text-[color:var(--nx-muted)]" aria-hidden />
        <input value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} aria-label="Search a place in Deep-Time Earth" placeholder="Himalayas, Hyderabad, Western Ghats, Sundarbans…" className="min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-[color:var(--nx-muted)]" />
        <button type="submit" className="nx-chip">Where was it?</button>
      </form>
      {open && shown.length ? (
        <ul className="nx-glass absolute left-0 right-0 top-full z-40 mt-1 p-1" role="listbox">
          {shown.map((h) => (
            <li key={h.id}>
              <button type="button" className="nx-ghost !justify-start w-full text-left text-[13px]" onClick={() => { dt.pickLocation(h.id); setQ(h.name); setOpen(false); }}>
                {h.display_name}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {dt.notice ? <p role="status" className="nx-glass mt-2 px-3 py-1.5 text-[12px] text-amber-200">{dt.notice}</p> : null}
    </div>
  );
}

function Tick({ age, label, color, active, onClick }: { age: number; label: string; color: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-label={`Go to ${label}`} aria-pressed={active} className="group flex flex-col items-center gap-0.5 px-1">
      <span className={`block h-3 w-1.5 rounded-sm ${active ? "ring-2 ring-white" : "opacity-80 group-hover:opacity-100"}`} style={{ background: color }} />
      <span className={`text-[10px] tabular-nums ${active ? "font-bold text-white" : "text-[color:var(--nx-muted)]"}`}>{age === 0 ? "Now" : formatMa(age)}</span>
    </button>
  );
}

export function DeepTimeBar({ dt }: { dt: DeepTime }) {
  const { manifest, age, info, frame } = dt;
  const [open, setOpen] = useState(false);
  const rank = (a: number) => dt.ages.indexOf(a);
  const sorted = [...dt.ages].sort((a, b) => b - a); // oldest at the left
  const idx = sorted.indexOf(age);
  const labelled = sorted.filter((a) => LABELLED_AGES.includes(a));
  void rank;
  if (!manifest) {
    return (
      <div className="nx-glass flex items-center gap-2 px-4 py-3 text-[13px]" role="status">
        {dt.error ? <span role="alert" className="text-rose-200">{dt.error}</span> : <><Loader2 className="nx-spin h-4 w-4" aria-hidden /> Loading the geological time scale…</>}
      </div>
    );
  }
  const interp = frame?.interpolation ?? info?.interpolation[dt.model] ?? "";
  return (
    <section className="nx-glass nx-rise w-[min(980px,96vw)] p-3" aria-label="Geological time" data-testid="deep-bar">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="nx-btn" onClick={dt.togglePlay} aria-label={dt.playing ? "Pause" : "Play through geological time"} data-testid="deep-play">
          {dt.playing ? <Pause className="h-4 w-4" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}
        </button>
        <button type="button" className="nx-ghost" onClick={() => dt.step(1)} aria-label="Previous (older) age" disabled={idx <= 0}><ChevronLeft className="h-4 w-4" aria-hidden /></button>
        <button type="button" className="nx-ghost" onClick={() => dt.step(-1)} aria-label="Next (younger) age" disabled={idx >= sorted.length - 1}><ChevronRight className="h-4 w-4" aria-hidden /></button>
        <button type="button" className="nx-ghost" onClick={dt.reset} aria-label="Reset to the present day" data-testid="deep-reset"><RotateCcw className="h-4 w-4" aria-hidden /> Present</button>
        <div className="mx-1 leading-tight" data-testid="deep-current">
          <p className="text-[15px] font-bold">{formatAge(age)} <span className="text-[12px] font-normal text-[color:var(--nx-muted)]">({formatMa(age)})</span></p>
          <p className="text-[12px] text-[color:var(--nx-soft)]">
            <span className="mr-1 inline-block h-2 w-2 rounded-full align-middle" style={{ background: periodColor(manifest, age) }} />
            {info ? `${info.era} · ${info.period}${info.epoch ? ` · ${info.epoch}` : ""}` : ""}
          </p>
        </div>
        <label className="ml-auto flex items-center gap-1.5 text-[12px]">
          Speed
          <select value={dt.speed} onChange={(e) => dt.setSpeed(Number(e.target.value))} className="rounded bg-white/10 px-1.5 py-1 text-[12px]" aria-label="Animation speed">
            {[0.5, 1, 2, 4].map((s) => <option key={s} value={s} className="text-black">{s}×</option>)}
          </select>
        </label>
        <button type="button" className="nx-chip" aria-expanded={open} onClick={() => setOpen((o) => !o)}>Layers</button>
      </div>

      <div className="mt-2 flex items-end gap-1 overflow-x-auto pb-1" role="group" aria-label="Geological ages, oldest to youngest">
        {sorted.map((a) => {
          const show = labelled.includes(a) || a === age;
          return (
            <div key={a} className="flex min-w-[14px] flex-1 flex-col items-center">
              {show ? <Tick age={a} label={formatAge(a)} color={periodColor(manifest, a)} active={a === age} onClick={() => dt.setAge(a)} /> : (
                <button type="button" onClick={() => dt.setAge(a)} aria-label={`Go to ${formatAge(a)}`} className="flex h-full flex-col items-center px-1">
                  <span className="block h-3 w-1 rounded-sm opacity-60 hover:opacity-100" style={{ background: periodColor(manifest, a) }} />
                  <span className="h-[15px]" />
                </button>
              )}
            </div>
          );
        })}
      </div>
      <input type="range" min={0} max={Math.max(0, sorted.length - 1)} step={1} value={Math.max(0, idx)} onChange={(e) => dt.setAge(sorted[Number(e.target.value)])} aria-label="Geological age" aria-valuetext={formatAge(age)} className="w-full" data-testid="deep-slider" />

      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11.5px]">
        <span className="rounded border border-sky-300/40 bg-sky-400/10 px-2 py-0.5 font-semibold text-sky-200" data-testid="deep-mode-badge">{frame?.mode_label ?? "Geological Reconstruction"} · not a satellite observation</span>
        {interp ? <span className="rounded border border-white/20 px-2 py-0.5 text-[color:var(--nx-soft)]" data-testid="deep-interp">{interp}</span> : null}
        {info && !info.has_paleogeography ? <span className="rounded border border-amber-300/40 px-2 py-0.5 text-amber-200">No paleogeography map at this age; plates and present-day shapes carried on plates only</span> : null}
        {dt.loading ? <span className="flex items-center gap-1 text-[color:var(--nx-muted)]"><Loader2 className="nx-spin h-3 w-3" aria-hidden /> loading</span> : null}
        {dt.error ? <span role="alert" className="text-rose-200">{dt.error}</span> : null}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label="What to show" className="flex gap-1">
          {VIEWS.map((v) => (
            <button key={v.id} type="button" role="radio" aria-checked={dt.view === v.id} onClick={() => dt.setView(v.id)} className={`nx-chip ${dt.view === v.id ? "!bg-white/20 font-semibold" : ""}`} data-testid={`view-${v.id}`}>{v.label}</button>
          ))}
        </div>
        <div role="radiogroup" aria-label="Plate model" className="ml-auto flex gap-1">
          {(["earthbyte", "paleomap"] as DeepModel[]).map((m) => (
            <button key={m} type="button" role="radio" aria-checked={dt.model === m} onClick={() => dt.setModel(m)} title={manifest.models[m]} className={`nx-chip ${dt.model === m ? "!bg-white/20 font-semibold" : ""}`} data-testid={`model-${m}`}>{m === "earthbyte" ? "EarthByte" : "PALEOMAP"}</button>
          ))}
        </div>
        {dt.view !== "reconstruction" ? (
          <label className="flex items-center gap-1.5 text-[12px]"><input type="checkbox" checked={dt.widen} onChange={(e) => dt.setWiden(e.target.checked)} /> ±5 Ma</label>
        ) : null}
        <label className="flex items-center gap-1.5 text-[12px]"><input type="checkbox" checked={dt.follow} onChange={(e) => dt.setFollow(e.target.checked)} /> Follow India</label>
      </div>

      {open && frame ? (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 border-t border-white/10 pt-2" data-testid="deep-layers">
          {frame.raster ? (
            <label className="flex items-center gap-1.5 text-[12px]"><input type="checkbox" checked={dt.visible.paleomap ?? true} onChange={(e) => dt.toggleLayer("paleomap", e.target.checked)} /> Paleogeographic map (PALEOMAP, {formatMa(frame.raster.map_age_ma)})</label>
          ) : null}
          {frame.layers.map((l) => {
            const on = dt.visible[l.name] ?? !(["continents", "coastlines"].includes(l.name) && frame.has_paleogeography);
            return (
              <label key={l.name} className="flex items-center gap-1.5 text-[12px]" title={l.kind}>
                <input type="checkbox" checked={on} onChange={(e) => dt.toggleLayer(l.name, e.target.checked)} /> {l.label}
              </label>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function Section({ title, children, id }: { title: string; children: React.ReactNode; id?: string }) {
  return (
    <section className="mt-3 border-t border-white/10 pt-2" data-testid={id}>
      <h3 className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--nx-muted)]">{title}</h3>
      <div className="mt-1 text-[12.5px] leading-snug text-[color:var(--nx-soft)]">{children}</div>
    </section>
  );
}

export function DeepTimePanel({ dt }: { dt: DeepTime }) {
  const { frame, info, model, place } = dt;
  const [tab, setTab] = useState<"now" | "himalaya" | "dino" | "ask">("now");
  const [q, setQ] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (tab === "himalaya") dt.loadHimalaya();
    if (tab === "dino") dt.loadDinos();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [dt.turns.length]);
  const pos = frame?.india[model];
  const other: DeepModel = model === "earthbyte" ? "paleomap" : "earthbyte";
  const f = dt.picked?.kind === "fossil" ? (dt.picked.properties as unknown as FossilProps) : null;
  return (
    <aside className="nx-glass nx-rise flex max-h-[calc(100vh-120px)] w-[min(400px,94vw)] flex-col overflow-hidden" aria-label="Deep-Time details" data-testid="deep-panel">
      <div className="flex items-center gap-1 border-b border-white/10 p-1.5" role="tablist">
        {([["now", "This time"], ["himalaya", "Himalayan Formation"], ["dino", "Dinosaur Era"], ["ask", "Ask"]] as const).map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} type="button" onClick={() => setTab(id)} className={`nx-chip ${tab === id ? "!bg-white/20 font-semibold" : ""}`}>{label}</button>
        ))}
      </div>
      <div className="overflow-y-auto p-3">
        {tab === "now" && frame ? (
          <>
            <h2 className="text-[16px] font-bold">{frame.label}</h2>
            <p className="text-[12.5px] text-[color:var(--nx-soft)]">{frame.period} · {frame.epoch}{frame.age_stage ? ` · ${frame.age_stage}` : ""}</p>
            <p className="mt-1 text-[11.5px] text-[color:var(--nx-muted)]">{frame.boundary}</p>
            <Section title="Indian Plate Journey" id="deep-india">
              <p>Indian plate (reference point), {frame.model_label.split(" (")[0]}: <b>{fmtLatLon(pos?.india)}</b></p>
              {pos?.gap_km != null ? <p>Distance to Eurasia (model): about {Math.round(pos.gap_km).toLocaleString("en-US")} km</p> : null}
              {frame.india[other]?.india ? <p>{other === "paleomap" ? "PALEOMAP" : "EarthByte"} puts it at {fmtLatLon(frame.india[other].india)}{frame.models_disagree_km != null ? `; the models differ by about ${Math.round(frame.models_disagree_km).toLocaleString("en-US")} km` : ""}.</p> : null}
            </Section>
            <Section title="Ancient India: environment">
              <p>{frame.environment.kind}</p>
              {frame.environment.points.slice(0, 4).map((p) => <p key={p.id}>{p.name}: {p.context ?? "no paleogeography mapped"}</p>)}
            </Section>
            <Section title="Geological Events" id="deep-events">
              {frame.events.length ? <ul className="list-disc pl-4">{frame.events.map((e) => <li key={e.event_id}><b>{e.event_name}</b> ({formatMa(e.start_age_ma)}{e.end_age_ma !== e.start_age_ma ? `–${formatMa(e.end_age_ma)}` : ""}, {e.confidence} confidence)</li>)}</ul> : <p>No catalogued event at this age.</p>}
            </Section>
            <Section title="Fossil Discoveries">
              <p>{frame.fossil_count} real PBDB occurrence(s) in India whose recorded age range includes {formatMa(frame.age_ma)}. Use the Fossil Discoveries view to see them.</p>
              {frame.age_ma < 66 ? <p className="text-[11.5px] text-amber-200/90">PBDB files birds (Aves) under Dinosauria, so records younger than 66 Ma are birds, not non-avian dinosaurs.</p> : null}
            </Section>
            {f ? (
              <Section title="Selected fossil" id="deep-picked">
                <p><b>{f.taxon_name}</b> ({f.higher_taxonomy})</p>
                <p>{f.locality}, {f.state}{f.formation ? ` · ${f.formation}` : ""}</p>
                <p>{f.age_label}; {f.fossil_type}; quality: {f.data_quality}</p>
                <p className="text-[11.5px] text-[color:var(--nx-muted)]">{f.occurrence_id} · {f.source_database} · {f.reference_text}</p>
              </Section>
            ) : dt.picked ? (
              <Section title="Selected formation" id="deep-picked">
                {Object.entries(dt.picked.properties).filter(([, v]) => v != null && v !== "").slice(0, 10).map(([k, v]) => <p key={k}><b>{k.replace(/_/g, " ")}:</b> {String(v)}</p>)}
              </Section>
            ) : null}
            {place ? (
              <Section title={`Where was ${place.name}?`} id="deep-place">
                <p>{place.explanation}</p>
                <p>Reconstructed plate position: <b>{fmtLatLon(place.reconstructed_position[model])}</b></p>
                {place.limitations.map((l) => <p key={l} className="text-[11.5px] text-amber-200/90">{l}</p>)}
                <button type="button" className="nx-chip mt-1" onClick={dt.clearPlace}><X className="h-3 w-3" aria-hidden /> Clear place</button>
              </Section>
            ) : null}
            <Section title="Sources, confidence and limits">
              <p>{frame.resolution}</p>
              <p>{frame.interpolation}</p>
              <p className="text-amber-200/90">{frame.caveat}</p>
              <p className="mt-1 text-[11.5px]">{frame.sources.map((s) => s.id).join(", ")} · confidence: {frame.confidence}</p>
              {frame.raster ? <p className="text-[11.5px]">{frame.raster.note}</p> : null}
            </Section>
          </>
        ) : null}
        {tab === "now" && !frame ? <p className="text-[13px]">{info ? info.label : "Loading…"}</p> : null}

        {tab === "himalaya" ? (
          dt.himalaya ? (
            <>
              <p className="text-[12px] text-[color:var(--nx-soft)]">{dt.himalaya.note}</p>
              <p className="mt-1 text-[12px] text-amber-200/90">{dt.himalaya.gap_note}</p>
              {dt.himalaya.stages.map((s) => (
                <button key={s.age_ma} type="button" onClick={() => { dt.setAge(s.age_ma); }} className={`mt-2 block w-full rounded-lg border p-2 text-left ${dt.age === s.age_ma ? "border-amber-300/60 bg-amber-300/10" : "border-white/10 hover:bg-white/5"}`}>
                  <p className="flex items-center gap-1.5 text-[13px] font-semibold"><Mountain className="h-3.5 w-3.5" aria-hidden /> {s.label} · {s.stage}</p>
                  <p className="text-[12px] text-[color:var(--nx-soft)]">{s.collision}</p>
                  <p className="text-[11.5px] text-[color:var(--nx-muted)]">{s.mountains}</p>
                  <p className="text-[11.5px] text-amber-200/80">Uncertainty: {s.uncertainty}</p>
                </button>
              ))}
            </>
          ) : <p className="flex items-center gap-2 text-[13px]"><Loader2 className="nx-spin h-4 w-4" aria-hidden /> Loading…</p>
        ) : null}

        {tab === "dino" ? (
          dt.dinos ? (
            <>
              <h2 className="text-[15px] font-bold">India During the Age of Dinosaurs</h2>
              <p className="text-[12px] text-[color:var(--nx-soft)]">{dt.dinos.note}</p>
              {dt.dinos.slices.map((s) => (
                <button key={s.age_ma} type="button" onClick={() => { dt.setAge(s.age_ma); dt.setView("fossils"); }} className={`mt-2 flex w-full items-center justify-between rounded-lg border p-2 text-left ${dt.age === s.age_ma ? "border-orange-300/60 bg-orange-300/10" : "border-white/10 hover:bg-white/5"}`}>
                  <span><b className="text-[13px]">{s.label}</b><br /><span className="text-[11.5px] text-[color:var(--nx-muted)]">{s.period} · {s.epoch}</span></span>
                  <span className="flex items-center gap-1 text-[12px]"><Flame className="h-3.5 w-3.5" aria-hidden /> {s.fossil_count} records ({s.fossil_count_within_5_ma} within ±5 Ma)</span>
                </button>
              ))}
            </>
          ) : <p className="flex items-center gap-2 text-[13px]"><Loader2 className="nx-spin h-4 w-4" aria-hidden /> Loading…</p>
        ) : null}

        {tab === "ask" ? (
          <>
            <p className="text-[12px] text-[color:var(--nx-muted)]">Answers use only the records and reconstruction on this page, in four labelled parts.</p>
            <div className="mt-2 space-y-3" aria-live="polite">
              {dt.turns.map((t, i) => (
                <div key={i}>
                  <p className="text-[12.5px] font-semibold">{t.q}</p>
                  <p className="mt-0.5 whitespace-pre-wrap text-[12.5px] text-[color:var(--nx-soft)]" data-testid="deep-answer">{t.a}</p>
                  <p className="text-[10.5px] text-[color:var(--nx-muted)]">{t.source === "groq" ? "AI wording over dataset records" : "Rule-based answer from dataset records"}{t.notice ? ` · ${t.notice}` : ""}</p>
                </div>
              ))}
              {dt.asking ? <p className="flex items-center gap-2 text-[12px]"><Loader2 className="nx-spin h-3.5 w-3.5" aria-hidden /> Looking at the records…</p> : null}
              <div ref={endRef} />
            </div>
            <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); const t = q.trim(); if (t) { setQ(""); void dt.ask(t); } }}>
              <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Ask about this geological time" placeholder="Where was India 66 million years ago?" className="min-w-0 flex-1 rounded-lg bg-white/10 px-3 py-2 text-[13px] outline-none" />
              <button type="submit" className="nx-btn" aria-label="Ask" disabled={dt.asking}><Send className="h-4 w-4" aria-hidden /></button>
            </form>
          </>
        ) : null}
      </div>
    </aside>
  );
}
