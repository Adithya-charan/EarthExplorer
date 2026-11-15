"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { explorerApi } from "@/lib/explorer/api";
import {
  deepApi, deepUrl, nearestAge, stepAge,
  type DeepFrame, type DeepLayer, type DeepManifest, type DeepModel, type DeepPlace, type DeepView, type DinoSlice, type HimalayaStage, type PointCollection,
} from "@/lib/explorer/deeptime";
import type { LayerSpec } from "@/lib/explorer/logic";
import { toApiError } from "@/lib/api";
import type { DeepGlobeState } from "./Globe";
import type { DeepVectorSpec, PickedDeep } from "./deepGlobe";

export interface DeepTurn {
  q: string;
  a: string;
  source: "groq" | "deterministic";
  notice: string | null;
}

/** Places whose history is the Himalayan one (the Indian-margin crust of the range). */
export const HIMALAYAN_IDS = new Set(["mountain:himalayas", "river:dhauliganga-catchment", "glacier:gangotri-glacier", "state:uttarakhand", "city:joshimath", "city:dehradun", "city:rishikesh", "city:haridwar"]);

const ORDER = ["continents", "shallow_marine", "landmass", "mountains", "ice_sheet", "plates", "coastlines", "india_outline_earthbyte", "india_outline_paleomap"];

/** Layers that are drawn by default; the rest can be switched on. Present-day shapes are only used where no paleogeography exists. */
export function defaultVisible(name: string, hasPaleo: boolean): boolean {
  if (name === "continents" || name === "coastlines") return !hasPaleo;
  return true;
}

export function vectorSpecs(layers: DeepLayer[], key: string, visible: Record<string, boolean>, hasPaleo: boolean): DeepVectorSpec[] {
  const out: DeepVectorSpec[] = [];
  const sorted = [...layers].sort((a, b) => ORDER.indexOf(a.name) - ORDER.indexOf(b.name));
  for (const l of sorted) {
    if (!(visible[l.name] ?? defaultVisible(l.name, hasPaleo))) continue;
    const url = deepUrl(l.url);
    const k = `${key}:${l.name}`;
    if (l.name === "plates") {
      out.push({ key: `${k}:rest`, url, stroke: "#94a3b8", strokeAlpha: 0.45, strokeWidth: 1, filter: (p) => !p.is_indian_plate });
      out.push({ key: `${k}:india`, url, fill: "#f59e0b", fillAlpha: 0.22, stroke: "#f59e0b", strokeAlpha: 0.95, strokeWidth: 2.5, filter: (p) => Boolean(p.is_indian_plate) });
    } else if (l.name === "continents") out.push({ key: k, url, fill: "#3f7f5f", fillAlpha: 0.5 });
    else if (l.name === "coastlines") out.push({ key: k, url, stroke: "#e5e7eb", strokeAlpha: 0.7, strokeWidth: 1 });
    else if (l.name === "landmass") out.push({ key: k, url, fill: "#5aa469", fillAlpha: 0.8 });
    else if (l.name === "shallow_marine") out.push({ key: k, url, fill: "#3fb2d6", fillAlpha: 0.5 });
    else if (l.name === "mountains") out.push({ key: k, url, fill: "#9a7b55", fillAlpha: 0.9 });
    else if (l.name === "ice_sheet") out.push({ key: k, url, fill: "#f1f8ff", fillAlpha: 0.9 });
    else if (l.name.startsWith("india_outline")) out.push({ key: k, url, stroke: "#fbbf24", strokeAlpha: 1, strokeWidth: 3 });
  }
  return out;
}

interface Opts {
  /** Move the camera over (lat, lon). */
  onFocus: (lat: number, lon: number, height: number) => void;
}

export function useDeepTime({ onFocus }: Opts) {
  const [active, setActive] = useState(false);
  const [manifest, setManifest] = useState<DeepManifest | null>(null);
  const [age, setAgeRaw] = useState(100);
  const [model, setModel] = useState<DeepModel>("earthbyte");
  const [view, setView] = useState<DeepView>("reconstruction");
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [frame, setFrame] = useState<DeepFrame | null>(null);
  const [fossils, setFossils] = useState<PointCollection<Record<string, unknown>> | null>(null);
  const [formations, setFormations] = useState<PointCollection<Record<string, unknown>> | null>(null);
  const [widen, setWiden] = useState(false);
  const [placeId, setPlaceId] = useState<string | null>(null);
  const [place, setPlace] = useState<DeepPlace | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [follow, setFollow] = useState(true);
  const [picked, setPicked] = useState<PickedDeep | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [himalaya, setHimalaya] = useState<{ note: string; gap_note: string; stages: HimalayaStage[] } | null>(null);
  const [dinos, setDinos] = useState<{ note: string; slices: DinoSlice[] } | null>(null);
  const [turns, setTurns] = useState<DeepTurn[]>([]);
  const [asking, setAsking] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const frameCache = useRef(new Map<string, DeepFrame>());
  const focusRef = useRef(onFocus);
  useEffect(() => {
    focusRef.current = onFocus;
  });

  const ages = useMemo(() => manifest?.ages.map((a) => a.age_ma) ?? [], [manifest]);
  const info = useMemo(() => manifest?.ages.find((a) => a.age_ma === age) ?? null, [manifest, age]);

  const setAge = useCallback(
    (a: number) => {
      setAgeRaw(ages.length ? nearestAge(ages, a) : a);
      setPicked(null);
    },
    [ages],
  );

  // ----------------------------------------------------------------------- manifest (once, on first entry)
  useEffect(() => {
    if (!active || manifest) return;
    const c = new AbortController();
    deepApi
      .manifest(c.signal)
      .then((m) => {
        setManifest(m);
        setError(null);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(toApiError(e).message);
      });
    return () => c.abort();
  }, [active, manifest]);

  // ----------------------------------------------------------------------- the frame for the chosen age and model
  useEffect(() => {
    if (!active || !manifest) return;
    const c = new AbortController();
    const k = `${age}|${model}`;
    const cached = frameCache.current.get(k);
    const apply = (f: DeepFrame) => {
      setFrame(f);
      setLoading(false);
      setError(null);
      const p = f.india[model]?.india;
      if (follow && !playing && p) focusRef.current(p[0], p[1], 15_000_000);
    };
    if (cached) {
      queueMicrotask(() => !c.signal.aborted && apply(cached));
    } else {
      queueMicrotask(() => !c.signal.aborted && setLoading(true));
      deepApi
        .frame(age, model, c.signal)
        .then((f) => {
          frameCache.current.set(k, f);
          if (frameCache.current.size > 40) frameCache.current.delete(frameCache.current.keys().next().value as string);
          if (!c.signal.aborted) apply(f);
        })
        .catch((e) => {
          if (!c.signal.aborted) {
            setLoading(false);
            setError(toApiError(e).message);
          }
        });
    }
    return () => c.abort();
    // The camera follows only when the age or model changes, not when "follow" or "playing" flip.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, manifest, age, model]);

  // ----------------------------------------------------------------------- fossils / formations
  useEffect(() => {
    if (!active || !manifest || view === "reconstruction") return;
    const c = new AbortController();
    const win = widen ? 5 : 0;
    const call = view === "fossils" ? deepApi.fossils(age, model, win, c.signal) : deepApi.formations(age, model, win, c.signal);
    call
      .then((fc) => {
        if (c.signal.aborted) return;
        if (view === "fossils") setFossils(fc as PointCollection<Record<string, unknown>>);
        else setFormations(fc as PointCollection<Record<string, unknown>>);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(toApiError(e).message);
      });
    return () => c.abort();
  }, [active, manifest, view, age, model, widen]);

  // ----------------------------------------------------------------------- the picked place
  useEffect(() => {
    if (!active || !manifest || !placeId) return;
    const c = new AbortController();
    deepApi
      .place(placeId, age, c.signal)
      .then((p) => !c.signal.aborted && setPlace(p))
      .catch(() => !c.signal.aborted && setPlace(null));
    return () => c.abort();
  }, [active, manifest, placeId, age]);

  // ----------------------------------------------------------------------- presets (fetched when first needed)
  const wantHimalaya = placeId != null && HIMALAYAN_IDS.has(placeId);
  useEffect(() => {
    if (!active || !manifest || !wantHimalaya || himalaya) return;
    const c = new AbortController();
    deepApi.himalaya(c.signal).then((h) => !c.signal.aborted && setHimalaya(h)).catch(() => undefined);
    return () => c.abort();
  }, [active, manifest, wantHimalaya, himalaya]);
  const loadHimalaya = useCallback(() => {
    if (himalaya) return;
    deepApi.himalaya().then(setHimalaya).catch(() => undefined);
  }, [himalaya]);
  const loadDinos = useCallback(() => {
    if (dinos) return;
    deepApi.dinosaurs().then(setDinos).catch(() => undefined);
  }, [dinos]);

  // ----------------------------------------------------------------------- playback: forward in time (older to younger)
  useEffect(() => {
    if (!playing || !ages.length) return;
    const id = setInterval(() => {
      setAgeRaw((cur) => {
        const next = stepAge(ages, cur, -1);
        if (next === cur) {
          setPlaying(false);
          return cur;
        }
        return next;
      });
    }, 1500 / speed);
    return () => clearInterval(id);
  }, [playing, speed, ages]);

  // ----------------------------------------------------------------------- derived props for the globe
  const hasPaleo = frame?.has_paleogeography ?? false;
  const vectors = useMemo(() => (frame ? vectorSpecs(frame.layers, `${frame.age_ma}|${frame.model}`, visible, hasPaleo) : []), [frame, visible, hasPaleo]);
  const raster: LayerSpec | null = useMemo(() => (active && frame?.raster && (visible.paleomap ?? true) ? { key: `paleomap:${frame.raster.map_age_ma}`, url: deepUrl(frame.raster.url), bbox: [-180, -90, 180, 90], alpha: 1, side: "none" } : null), [active, frame, visible]);
  const placeShape = useMemo(() => (place ? { name: place.name, reconstructed: place.reconstructed_position[model], modern: [place.modern_position.latitude, place.modern_position.longitude] as [number, number] } : null), [place, model]);
  const globe: DeepGlobeState = {
    active,
    vectors,
    points: view === "fossils" ? fossils : view === "formations" ? formations : null,
    pointKind: view === "formations" ? "formation" : "fossil",
    place: placeShape,
  };

  // ----------------------------------------------------------------------- actions
  const enter = useCallback(() => {
    setActive(true);
    setPlaying(false);
  }, []);
  const leave = useCallback(() => {
    setActive(false);
    setPlaying(false);
    setPicked(null);
  }, []);
  const reset = useCallback(() => {
    setPlaying(false);
    setAge(0);
  }, [setAge]);
  const step = useCallback((dir: 1 | -1) => setAge(stepAge(ages, age, dir)), [ages, age, setAge]);
  const togglePlay = useCallback(() => {
    if (!playing && ages.length && age === 0) setAgeRaw(Math.max(...ages));
    setPlaying((p) => !p);
  }, [playing, ages, age]);

  /** Search in Deep-Time Earth: resolve the text with the same gazetteer as the satellite mode, then reconstruct the plate under it. */
  const searchPlace = useCallback(async (q: string) => {
    const text = q.trim();
    if (!text) return;
    setNotice(null);
    try {
      const hits = await explorerApi.searchLocations(text);
      const top = hits[0];
      if (!top) {
        setNotice(`No place called "${text}" was found, so there is nothing to reconstruct.`);
        return;
      }
      setPlaceId(top.id);
      setPlace(null);
      setNotice(null);
    } catch (e) {
      setNotice(toApiError(e).message);
    }
  }, []);
  const pickLocation = useCallback((id: string) => {
    setPlaceId(id);
    setPlace(null);
    setNotice(null);
  }, []);

  const ask = useCallback(
    async (question: string) => {
      setAsking(true);
      try {
        const r = await deepApi.chat({ question, age, location: placeId, history: turns.slice(-4).flatMap((t) => [{ role: "user", content: t.q }, { role: "assistant", content: t.a }]) });
        setTurns((t) => [...t, { q: question, a: r.answer, source: r.source, notice: r.notice ?? null }]);
      } catch (e) {
        setTurns((t) => [...t, { q: question, a: toApiError(e).message, source: "deterministic", notice: null }]);
      } finally {
        setAsking(false);
      }
    },
    [age, placeId, turns],
  );

  return {
    active, manifest, age, info, model, view, visible, frame, fossils, formations, widen, placeId, place, playing, speed, follow, picked, error, loading, himalaya, dinos, turns, asking, notice, ages,
    raster, globe, wantHimalaya,
    setAge, setModel, setView, setWiden, setSpeed, setFollow, setPicked, setNotice,
    toggleLayer: (name: string, on: boolean) => setVisible((v) => ({ ...v, [name]: on })),
    enter, leave, reset, step, togglePlay, searchPlace, pickLocation, ask, loadHimalaya, loadDinos,
    clearPlace: () => {
      setPlaceId(null);
      setPlace(null);
    },
  };
}

export type DeepTime = ReturnType<typeof useDeepTime>;
