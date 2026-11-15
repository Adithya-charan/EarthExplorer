"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { AlertTriangle, Globe2, Loader2, Menu } from "lucide-react";
import { explorerApi } from "@/lib/explorer/api";
import { bboxRadiusM, dataLabel, isIllustrative, observationsInPeriod, planLayers, playDelayMs, stepIndex } from "@/lib/explorer/logic";
import type { BoundaryOut, ChangeSummary, DatasetInfo, Explanation, HotspotCollection, LocationOut, MapMode, ObservationInfo, SessionResponse } from "@/lib/explorer/types";
import { describeCommand, parseCommand, recognitionCtor, voiceErrorMessage, type VoiceCommand } from "@/lib/explorer/voice";
import { toApiError } from "@/lib/api";
import type { BoundaryShape, CameraState, GlobeFocus } from "./Globe";
import { HotspotNav, Legend, LatestCard, ModeBar, OutcomeBanner, PlaceNotice, StatusPill, type Phase } from "./Overlays";
import { SearchPanel, type VoiceUi } from "./SearchPanel";
import { SummaryPanel, type ChatTurn } from "./SummaryPanel";
import { Timeline } from "./Timeline";
import { DeepSearch, DeepTimeBar, DeepTimePanel, EraSwitch } from "./DeepTime";
import { useDeepTime } from "./useDeepTime";
import type { AppEra } from "@/lib/explorer/deeptime";

const Globe = dynamic(() => import("./Globe"), {
  ssr: false,
  loading: () => (
    <div className="absolute inset-0 grid place-items-center text-[color:var(--nx-muted)]" role="status">
      <span className="flex items-center gap-2">
        <Loader2 className="nx-spin h-4 w-4" aria-hidden /> Loading the globe…
      </span>
    </div>
  ),
});

const NAV_LINKS = [
  { href: "/analytics", label: "Change Analytics" },
  { href: "/deep-time", label: "Deep-Time Analytics" },
  { href: "/datasets", label: "Datasets" },
  { href: "/data", label: "Data & Methods" },
];

function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia("(prefers-reduced-motion: reduce)");
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );
}

/** One step of the visit history: enough to put the person back exactly where they were. */
interface NavEntry {
  query: string;
  locationId: string;
  startYear: number;
  endYear: number;
  datasetId: string | null;
  variable: string | null;
  mode: MapMode;
  cursorDate: string | null;
  camera: CameraState | null;
}

interface ExploreOpts {
  locationId?: string;
  datasetId?: string;
  variable?: string;
  /** Re-run for the same place (dataset switch): do not move the camera or add a history entry. */
  keepView?: boolean;
  restore?: NavEntry;
}

type Rec = InstanceType<NonNullable<ReturnType<typeof recognitionCtor>>>;
type FocusInput = GlobeFocus extends infer U ? (U extends { token: number } ? Omit<U, "token"> : never) : never;
const NEEDS_ANALYSIS: MapMode[] = ["beforeafter", "swipe", "difference", "hotspots"];

export function ExplorerApp() {
  const reduced = useReducedMotion();
  const [query, setQuery] = useState("");
  const [startYear, setStartYear] = useState(2000);
  const [endYear, setEndYear] = useState(2025);
  const [datasets, setDatasets] = useState<DatasetInfo[] | null>(null);
  const [datasetsError, setDatasetsError] = useState(false);

  const [locating, setLocating] = useState(false);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [summary, setSummary] = useState<ChangeSummary | null>(null);
  const [analysis, setAnalysis] = useState<"idle" | "running" | "done">("idle");
  const [error, setError] = useState<string | null>(null);
  const [observations, setObservations] = useState<ObservationInfo[]>([]);
  const [hotspotFc, setHotspotFc] = useState<HotspotCollection | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [explState, setExplState] = useState<"loading" | "ready" | "error" | "none">("none");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [asking, setAsking] = useState(false);

  const [mode, setMode] = useState<MapMode>("latest");
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [baShowAfter, setBaShowAfter] = useState(false);
  const [split, setSplit] = useState(0.5);
  const [activeHotspot, setActiveHotspot] = useState(-1);
  const [exploredAnyway, setExploredAnyway] = useState(false);
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  // Shown by default on tall screens; on short ones it is one click away so it never covers the map.
  const [latestOpen, setLatestOpen] = useState(() => typeof window !== "undefined" && window.innerHeight >= 760);

  const [focus, setFocus] = useState<GlobeFocus | null>(null);
  const [flightDone, setFlightDone] = useState(0);
  const [spin, setSpin] = useState(true);
  const [globeError, setGlobeError] = useState<string | null>(null);
  const [layerBusy, setLayerBusy] = useState(false);
  const [layerError, setLayerError] = useState<string | null>(null);
  const [boundary, setBoundary] = useState<BoundaryOut | null>(null);
  const [navView, setNavView] = useState({ pos: -1, len: 0 });
  const [listening, setListening] = useState(false);
  const [heard, setHeard] = useState("");
  const [voiceNote, setVoiceNote] = useState<VoiceUi["note"]>(null);
  const voiceSupported = useSyncExternalStore(
    () => () => undefined,
    () => recognitionCtor() !== null,
    () => false,
  );

  const runRef = useRef(0);
  const tokenRef = useRef(0);
  const sessionToken = useRef(0);
  const autoZoomed = useRef<string | null>(null);
  const cameraRef = useRef<CameraState | null>(null);
  const navRef = useRef<{ entries: NavEntry[]; pos: number }>({ entries: [], pos: -1 });
  const observationsRef = useRef<ObservationInfo[]>([]);
  const recRef = useRef<Rec | null>(null);
  const commandRef = useRef<(c: VoiceCommand) => void>(() => undefined);
  const liveRef = useRef({ mode: "latest" as MapMode, cursorDate: null as string | null, variable: null as string | null, datasetId: null as string | null, startYear: 2000, endYear: 2025 });

  // ------------------------------------------------------------------ dataset availability
  useEffect(() => {
    const c = new AbortController();
    explorerApi
      .datasets(c.signal)
      .then(setDatasets)
      .catch((e) => {
        if (!c.signal.aborted) {
          setDatasetsError(true);
          void toApiError(e);
        }
      });
    return () => c.abort();
  }, []);

  // ------------------------------------------------------------------------------- derived
  const ds = session?.dataset ?? null;
  const temporal = ds?.temporal_resolution ?? "monthly";
  const eff = summary?.period?.effective ?? session?.period?.effective ?? null;
  const periodObs = useMemo(() => {
    if (!observations.length) return [];
    const inP = eff ? observationsInPeriod(observations, eff.start_year, eff.end_year) : observations;
    return inP.length ? inP : observations;
  }, [observations, eff]);
  const cursorIdx = Math.min(cursor, Math.max(0, periodObs.length - 1));
  const flightComplete = !session || flightDone >= sessionToken.current || globeError !== null;
  const revealed = session != null && flightComplete && analysis === "done";
  const hasAnalysis = summary?.analysis_id != null && summary.outcome !== "insufficient_data";
  const bbox = ds?.bbox ?? null;

  // Latest view state, read when a history entry is saved.
  const liveCursorDate = periodObs[cursorIdx]?.date ?? null;
  const liveVariable = summary?.variable?.key ?? null;
  const liveDatasetId = ds?.id ?? null;
  useEffect(() => {
    liveRef.current = { mode, cursorDate: liveCursorDate, variable: liveVariable, datasetId: liveDatasetId, startYear, endYear };
  }, [mode, liveCursorDate, liveVariable, liveDatasetId, startYear, endYear]);

  // The outline of the searched place, from the backend (authoritative where one exists, otherwise marked approximate).
  const locationId = session?.location?.id ?? null;
  useEffect(() => {
    setBoundary(null);
    if (!locationId) return;
    const c = new AbortController();
    explorerApi
      .boundary(locationId, c.signal)
      .then(setBoundary)
      .catch(() => undefined);
    return () => c.abort();
  }, [locationId]);
  const boundaryShape: BoundaryShape | null = boundary?.geometry ? { id: boundary.location_id, geometry: boundary.geometry, approximate: !boundary.authoritative } : null;

  const plan = useMemo(
    () =>
      planLayers({
        mode,
        summary,
        datasetId: ds?.id ?? null,
        bbox,
        latestDate: session?.latest?.date ?? null,
        cursorDate: periodObs[cursorIdx]?.date ?? null,
        baShowAfter,
        temporal,
        variableLabel: summary?.variable?.label,
      }),
    [mode, summary, ds, bbox, session, periodObs, cursorIdx, baShowAfter, temporal],
  );
  const prefetch = useMemo(() => {
    if (mode !== "history" || !ds || !bbox) return [];
    return [1, 2]
      .map((k) => periodObs[cursorIdx + k]?.date)
      .filter((d): d is string => Boolean(d))
      .map((d) => planLayers({ mode: "history", summary, datasetId: ds.id, bbox, latestDate: null, cursorDate: d, baShowAfter: false, temporal }).primary!)
      .filter(Boolean);
  }, [mode, ds, bbox, periodObs, cursorIdx, summary, temporal]);

  const phase: Phase = error ? "error" : locating ? "locating" : session && !flightComplete ? "flying" : analysis === "running" ? "analysing" : session ? "ready" : "idle";
  const showResults = revealed || session?.status === "not_found";
  const marker = session?.location && session.status !== "not_found" ? { lon: session.location.lon, lat: session.location.lat, label: `${session.location.name} · ${Math.abs(session.location.lat).toFixed(3)}°${session.location.lat >= 0 ? "N" : "S"}, ${Math.abs(session.location.lon).toFixed(3)}°${session.location.lon >= 0 ? "E" : "W"}` } : null;

  // ---------------------------------------------------------------------------------- camera
  const flyTo = useCallback((f: FocusInput) => {
    tokenRef.current += 1;
    setFocus({ ...f, token: tokenRef.current } as GlobeFocus);
    return tokenRef.current;
  }, []);

  const deep = useDeepTime({ onFocus: (lat, lon, height) => flyTo({ kind: "camera", lon, lat, height, heading: 0, pitch: -1.5707963267948966, roll: 0 }) });
  const era: AppEra = deep.active ? "deep" : mode === "history" ? "historical" : "today";
  const changeEra = (e: AppEra) => {
    if (e === "deep") {
      setPlaying(false);
      setSpin(false);
      deep.enter();
      return;
    }
    if (deep.active) deep.leave();
    setMode(e === "historical" && ds ? "history" : "latest");
  };

  const zoomHotspot = useCallback(
    (i: number, s: ChangeSummary | null = summary) => {
      const h = s?.hotspots[i];
      if (!h) return;
      setActiveHotspot(i);
      setMode((m) => (m === "hotspots" || m === "difference" ? m : "hotspots"));
      flyTo({ kind: "sphere", lon: h.centroid.lon, lat: h.centroid.lat, radius: bboxRadiusM(h.bbox) });
    },
    [summary, flyTo],
  );

  const overview = useCallback(() => {
    setActiveHotspot(-1);
    if (session?.location && ds) flyTo({ kind: "place", lon: session.location.lon, lat: session.location.lat, altitude: session.location.zoom_altitude_m, bbox: ds.bbox });
  }, [session, ds, flyTo]);

  // ------------------------------------------------------------------------- visit history
  const syncNav = () => setNavView({ pos: navRef.current.pos, len: navRef.current.entries.length });
  /** Save what the person is looking at into the current history entry, so Back can restore it. */
  const saveCurrent = () => {
    const n = navRef.current;
    if (n.pos < 0 || !n.entries[n.pos]) return;
    const l = liveRef.current;
    n.entries[n.pos] = { ...n.entries[n.pos], mode: l.mode, cursorDate: l.cursorDate, variable: l.variable, datasetId: l.datasetId ?? n.entries[n.pos].datasetId, startYear: l.startYear, endYear: l.endYear, camera: cameraRef.current };
  };
  const record = (e: NavEntry) => {
    saveCurrent();
    const n = navRef.current;
    n.entries = [...n.entries.slice(0, n.pos + 1), e];
    n.pos = n.entries.length - 1;
    syncNav();
  };

  // ------------------------------------------------------------------------------ analysis
  const analyse = useCallback(async (datasetId: string, sy: number, ey: number, variable: string | undefined, stale: () => boolean, opts: { loadObservations: boolean; restore?: NavEntry }) => {
    setAnalysis("running");
    const [sum, obs] = await Promise.all([
      explorerApi.detect({ dataset_id: datasetId, start_year: sy, end_year: ey, ...(variable ? { params: { variable } } : {}) }),
      opts.loadObservations ? explorerApi.observations(datasetId) : Promise.resolve(null),
    ]);
    if (stale()) return;
    const all = obs ?? observationsRef.current;
    if (obs) {
      observationsRef.current = obs;
      setObservations(obs);
    }
    setSummary(sum);
    const usable = sum.analysis_id != null && sum.outcome !== "insufficient_data";
    const r = opts.restore;
    const wanted: MapMode = r && (!NEEDS_ANALYSIS.includes(r.mode) || usable) ? r.mode : sum.outcome === "change_detected" ? "hotspots" : "latest";
    setMode(wanted);
    const e = sum.period?.effective;
    const inP = e ? observationsInPeriod(all, e.start_year, e.end_year) : all;
    const list = inP.length ? inP : all;
    const at = r?.cursorDate ? list.findIndex((o) => o.date === r.cursorDate) : -1;
    setCursor(at >= 0 ? at : Math.max(0, list.length - 1));
    if (r && sum.analysis_id) autoZoomed.current = sum.analysis_id;
    setAnalysis("done");
    if (usable && sum.analysis_id) {
      const id = sum.analysis_id;
      explorerApi
        .hotspots(id)
        .then((fc) => !stale() && setHotspotFc(fc))
        .catch(() => undefined);
      setExplState("loading");
      explorerApi
        .explain(id)
        .then((x) => {
          if (stale()) return;
          setExplanation(x);
          setExplState("ready");
        })
        .catch(() => !stale() && setExplState("error"));
    }
  }, []);

  // --------------------------------------------------------------------------------- explore
  const explore = async (q: string, sy: number, ey: number, opts: ExploreOpts = {}) => {
    const run = ++runRef.current;
    const stale = () => run !== runRef.current;
    if (!opts.keepView && !opts.restore) saveCurrent();
    setSpin(false);
    setPlaying(false);
    setError(null);
    setLocating(true);
    if (!opts.keepView) setSession(null);
    setSummary(null);
    setHotspotFc(null);
    setExplanation(null);
    setExplState("none");
    setTurns([]);
    setActiveHotspot(-1);
    setExploredAnyway(false);
    setLayerError(null);
    setAnalysis("idle");
    if (!opts.keepView) {
      setObservations([]);
      observationsRef.current = [];
      setMode("latest");
    }
    try {
      const sess = await explorerApi.session({ ...(opts.locationId ? { location_id: opts.locationId } : { query: q }), start_year: sy, end_year: ey, ...(opts.datasetId ? { dataset_id: opts.datasetId } : {}) });
      if (stale()) return;
      setLocating(false);
      setSession(sess);
      if (sess.status === "not_found" || !sess.location) {
        setSpin(true);
        setAnalysis("done");
        return;
      }
      const loc = sess.location;
      if (!opts.keepView) {
        if (opts.restore?.camera) sessionToken.current = flyTo({ kind: "camera", ...opts.restore.camera });
        else sessionToken.current = flyTo({ kind: "place", lon: loc.lon, lat: loc.lat, altitude: loc.zoom_altitude_m, bbox: sess.dataset?.bbox ?? loc.bbox });
      }
      if (!opts.restore && !opts.keepView) {
        record({ query: q, locationId: loc.id, startYear: sy, endYear: ey, datasetId: sess.dataset?.id ?? null, variable: opts.variable ?? null, mode: "latest", cursorDate: null, camera: null });
      }
      if (sess.status !== "ready" || !sess.dataset) {
        setAnalysis("done");
        return;
      }
      await analyse(sess.dataset.id, sy, ey, opts.variable, stale, { loadObservations: true, restore: opts.restore });
    } catch (err) {
      if (stale()) return;
      setLocating(false);
      setAnalysis("done");
      setError(toApiError(err).message);
      setSpin(true);
    }
  };

  const pickVariable = (key: string) => {
    if (!ds || key === summary?.variable?.key) return;
    const run = ++runRef.current;
    setPlaying(false);
    setHotspotFc(null);
    setExplanation(null);
    setExplState("none");
    setActiveHotspot(-1);
    setLayerError(null);
    analyse(ds.id, startYear, endYear, key, () => run !== runRef.current, { loadObservations: false }).catch((err) => {
      if (run !== runRef.current) return;
      setAnalysis("done");
      setError(toApiError(err).message);
    });
  };
  const pickDataset = (id: string) => {
    if (!session?.location || id === ds?.id) return;
    void explore(session.location.name, startYear, endYear, { locationId: session.location.id, datasetId: id, keepView: true });
  };
  // A dataset inside a larger area: go to the dataset's own place (its name resolves through the same search).
  const openNearby = (d: DatasetInfo) => {
    const place = d.name.replace(/ \((?:illustrative|simulated)[^)]*\)$/i, "");
    setQuery(place);
    void explore(place, startYear, endYear, { datasetId: d.id });
  };
  const pickPlace = (loc: LocationOut) => {
    setQuery(loc.name);
    void explore(loc.name, startYear, endYear, { locationId: loc.id });
  };

  const restoreEntry = (e: NavEntry) => {
    setQuery(e.query);
    setStartYear(e.startYear);
    setEndYear(e.endYear);
    void explore(e.query, e.startYear, e.endYear, { locationId: e.locationId, datasetId: e.datasetId ?? undefined, variable: e.variable ?? undefined, restore: e });
  };
  const goBack = () => {
    const n = navRef.current;
    if (n.pos <= 0) return;
    saveCurrent();
    n.pos -= 1;
    syncNav();
    restoreEntry(n.entries[n.pos]);
  };
  const goForward = () => {
    const n = navRef.current;
    if (n.pos >= n.entries.length - 1) return;
    saveCurrent();
    n.pos += 1;
    syncNav();
    restoreEntry(n.entries[n.pos]);
  };

  // Same functions as the buttons: typed and spoken commands both end up here.
  const say = (tone: "info" | "ok" | "error", text: string) => setVoiceNote({ tone, text });
  const runCommand = (c: VoiceCommand) => {
    const needPlace = () => say("error", "Search a place first, then I can do that.");
    switch (c.type) {
      case "goto":
        say("ok", describeCommand(c));
        setQuery(c.place);
        void explore(c.place, startYear, endYear);
        break;
      case "compare":
        if (!session?.location) return needPlace();
        say("ok", describeCommand(c));
        setStartYear(c.start);
        setEndYear(c.end);
        void explore(session.location.name, c.start, c.end, { locationId: session.location.id, datasetId: ds?.id });
        break;
      case "latest":
        if (!ds) return needPlace();
        say("ok", describeCommand(c));
        setMode("latest");
        setPlaying(false);
        break;
      case "history":
        if (!ds) return needPlace();
        say("ok", describeCommand(c));
        setMode("history");
        break;
      case "changes":
      case "hotspots":
      case "beforeafter":
      case "swipe":
        if (!ds) return needPlace();
        if (!hasAnalysis) return say("error", "There is no change analysis for this place and period, so there is nothing to show.");
        say("ok", describeCommand(c));
        setPlaying(false);
        setMode(c.type === "changes" ? "difference" : c.type);
        break;
      case "zoom":
        if (!session?.location) return needPlace();
        say("ok", describeCommand(c));
        overview();
        break;
      case "back":
        if (navRef.current.pos <= 0) return say("error", "There is no earlier location to go back to.");
        say("ok", describeCommand(c));
        goBack();
        break;
      case "forward":
        if (navRef.current.pos >= navRef.current.entries.length - 1) return say("error", "There is no later location to go forward to.");
        say("ok", describeCommand(c));
        goForward();
        break;
      case "unknown":
        say("error", `Sorry, I did not understand "${c.text}". Try "Take me to Hyderabad" or "Compare this location between 2000 and 2020".`);
        break;
    }
  };
  useEffect(() => {
    commandRef.current = runCommand;
  });

  const toggleVoice = () => {
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const Ctor = recognitionCtor();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = typeof navigator !== "undefined" && navigator.language ? navigator.language : "en-IN";
    rec.continuous = false;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    let finalText = "";
    rec.onstart = () => {
      setListening(true);
      setHeard("");
      setVoiceNote(null);
    };
    rec.onresult = (e) => {
      let text = "";
      for (let i = 0; i < e.results.length; i++) {
        text += e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText = text;
      }
      setHeard(text);
    };
    rec.onerror = (e) => {
      const m = voiceErrorMessage(e.error);
      if (m) say("error", m);
    };
    rec.onend = () => {
      setListening(false);
      recRef.current = null;
      const t = finalText.trim();
      if (t) {
        setQuery(t);
        commandRef.current(parseCommand(t));
      }
    };
    recRef.current = rec;
    try {
      rec.start();
    } catch {
      say("error", "Voice input could not start. You can type the command instead.");
    }
  };
  useEffect(() => () => recRef.current?.abort(), []);

  const submit = () => {
    const c = parseCommand(query);
    // Commands typed in the search box work like spoken ones; anything else is searched as a place name.
    if (c.type !== "goto" && c.type !== "unknown" && !(c.type === "compare" && !/compare/i.test(query))) {
      runCommand(c);
      return;
    }
    void explore(query.trim(), startYear, endYear);
  };
  const pickExample = (e: string) => {
    setQuery(e);
    void explore(e, startYear, endYear);
  };
  const useSuggestion = (s: number, e: number) => {
    setStartYear(s);
    setEndYear(e);
    void explore(query.trim() || session?.location?.name || "", s, e, session?.location ? { locationId: session.location.id } : {});
  };

  // After the flight and the analysis are both done and change was found, move in on the biggest hotspot.
  useEffect(() => {
    if (!revealed || !summary || summary.outcome !== "change_detected" || !summary.analysis_id) return;
    if (autoZoomed.current === summary.analysis_id) return;
    autoZoomed.current = summary.analysis_id;
    const id = setTimeout(() => zoomHotspot(0, summary), reduced ? 0 : 1800);
    return () => clearTimeout(id);
  }, [revealed, summary, reduced, zoomHotspot]);

  // ------------------------------------------------------------------------------- timeline
  useEffect(() => {
    if (!playing) return;
    const id = setTimeout(() => {
      setCursor((c) => {
        const next = stepIndex(Math.min(c, periodObs.length - 1), periodObs.length, 1);
        if (next === c || next >= periodObs.length - 1) setPlaying(false);
        return next;
      });
    }, playDelayMs(speed));
    return () => clearTimeout(id);
  }, [playing, cursor, speed, periodObs.length]);

  const scrub = (i: number) => {
    setCursor(i);
    if (mode !== "history") setMode("history");
  };
  const togglePlay = () => {
    if (!playing) {
      setMode("history");
      if (cursorIdx >= periodObs.length - 1) setCursor(0);
    }
    setPlaying((p) => !p);
  };
  const exploreAnyway = () => {
    setExploredAnyway(true);
    if (hasAnalysis) setMode("difference");
  };

  const ask = async (question: string) => {
    if (!summary?.analysis_id) return;
    setAsking(true);
    try {
      const r = await explorerApi.chat({ question, analysis_id: summary.analysis_id, history: turns.slice(-4).flatMap((t) => [{ role: "user", content: t.q }, { role: "assistant", content: t.a }]) });
      setTurns((t) => [...t, { q: question, a: r.answer, source: r.source, notice: r.notice }]);
    } catch (err) {
      setTurns((t) => [...t, { q: question, a: toApiError(err).message, source: "deterministic", notice: null }]);
    } finally {
      setAsking(false);
    }
  };

  const panelVisible = summary != null && session != null && flightComplete && (analysis === "done" || analysis === "running");
  const panelOpen = panelVisible && !panelCollapsed;
  const simulated = isIllustrative(ds);
  const voice: VoiceUi = { supported: voiceSupported, listening, heard, onToggle: toggleVoice, note: voiceNote };

  return (
    <div className="nx" data-testid="explorer" data-phase={phase}>
      <Globe
        deep={deep.globe}
        onDeepPick={deep.setPicked}
        focus={focus}
        marker={marker}
        primary={deep.active ? deep.raster : revealed || mode === "latest" ? plan.primary : null}
        secondary={deep.active ? null : plan.secondary}
        prefetch={prefetch}
        splitPosition={split}
        hotspots={hotspotFc}
        boundary={boundaryShape}
        onCamera={(c) => {
          cameraRef.current = c;
        }}
        showHotspots={plan.hotspots && Boolean(hotspotFc)}
        activeHotspot={summary?.hotspots[activeHotspot]?.id ?? null}
        spin={spin}
        reducedMotion={reduced}
        onReady={() => undefined}
        onUnsupported={(m) => setGlobeError(m)}
        onInteract={() => setSpin(false)}
        onFlightEnd={(t) => setFlightDone(t)}
        onLayerBusy={setLayerBusy}
        onLayerError={setLayerError}
      />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_55%,rgba(3,8,22,0.55)_100%)]" aria-hidden />

      {/* brand and navigation */}
      <header className="absolute left-4 top-4 z-20 flex items-center gap-3">
        <Globe2 className="h-6 w-6 text-[color:var(--nx-accent)]" aria-hidden />
        <div className="leading-tight">
          <h1 className="text-[17px] font-bold tracking-wide">NASAX</h1>
          <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--nx-muted)]">Earth Time Machine</p>
        </div>
      </header>
      <div className="absolute right-4 top-4 z-30 flex flex-col items-end gap-2">
        <div className="flex items-start gap-2">
          <button type="button" className="nx-glass flex items-center gap-2 px-3 py-2 text-[13px]" aria-expanded={menuOpen} aria-haspopup="menu" onClick={() => setMenuOpen((o) => !o)}>
            <Menu className="h-4 w-4" aria-hidden /> <span className="hidden sm:inline">More tools</span><span className="sr-only sm:hidden">More tools</span>
          </button>
        </div>
        {menuOpen ? (
          <nav className="nx-glass nx-rise mt-2 flex w-48 flex-col p-1.5" aria-label="Other pages">
            {NAV_LINKS.map((l) => (
              <Link key={l.href} href={l.href} className="nx-ghost !justify-start text-[13px]">
                {l.label}
              </Link>
            ))}
          </nav>
        ) : null}
      </div>

      {/* search + status + outcome */}
      <div className="absolute left-4 top-[68px] z-20 max-sm:mt-12" style={{ top: ds && !deep.active ? 100 : 68 }}>
        <EraSwitch era={era} onEra={changeEra} />
      </div>
      {deep.active ? (
        <div className="pointer-events-none absolute inset-x-0 top-4 z-10 flex flex-col items-center gap-3 px-3 pt-[112px] sm:pt-0">
          <div className="pointer-events-auto relative z-30"><DeepSearch dt={deep} /></div>
        </div>
      ) : null}
      <div className={`pointer-events-none absolute inset-x-0 top-4 z-10 flex-col items-center gap-3 px-3 pt-[112px] sm:pt-0 ${deep.active ? "hidden" : "flex"} ${panelOpen ? "lg:pr-[420px]" : ""}`}>
        <div className="pointer-events-auto relative z-30">
          <SearchPanel
            query={query}
            onQuery={setQuery}
            startYear={startYear}
            endYear={endYear}
            onStart={setStartYear}
            onEnd={setEndYear}
            onSubmit={submit}
            onExample={pickExample}
            onPick={pickPlace}
            canBack={navView.pos > 0}
            canForward={navView.pos < navView.len - 1}
            onBack={goBack}
            onForward={goForward}
            voice={voice}
            busy={locating || analysis === "running"}
            compact={Boolean(session)}
            datasets={datasets}
            datasetsError={datasetsError}
          />
        </div>
        <StatusPill phase={phase} name={session?.location?.name ?? null} />
        {error ? (
          <div role="alert" data-testid="error-banner" className="nx-glass nx-rise pointer-events-auto w-[560px] max-w-[92vw] border-rose-400/40 p-4">
            <p className="flex items-center gap-2 font-semibold text-rose-200">
              <AlertTriangle className="h-4 w-4" aria-hidden /> Something went wrong
            </p>
            <p className="mt-1 text-[13px] text-[color:var(--nx-soft)]">{error}</p>
            <button type="button" className="nx-chip mt-3" onClick={submit}>
              Try again
            </button>
          </div>
        ) : null}
        {showResults && !error ? (
          <div className="pointer-events-auto">
            <OutcomeBanner summary={summary} session={session} onUseSuggestion={useSuggestion} onExploreAnyway={exploreAnyway} onExample={pickExample} exploredAnyway={exploredAnyway} />
          </div>
        ) : null}
        {showResults && !error ? (
          <div className="pointer-events-auto">
            <PlaceNotice session={session} onPickPlace={pickPlace} onOpenDataset={openNearby} onExample={pickExample} />
          </div>
        ) : null}
        {globeError ? (
          <p role="alert" data-testid="globe-error" className="nx-glass pointer-events-auto max-w-[560px] p-3 text-[12.5px] text-amber-200">
            The 3D globe could not start ({globeError}). It needs WebGL. Search and analysis still work and show here as text.
          </p>
        ) : null}
      </div>

      {/* data-source badge, always visible while a dataset is on screen */}
      {ds && !deep.active ? (
        <p
          data-testid="data-badge"
          className={`absolute left-4 top-[68px] z-20 rounded-md border px-2.5 py-1 text-[11px] font-bold tracking-wide backdrop-blur ${simulated ? "border-amber-400/50 bg-amber-400/15 text-amber-200" : "border-emerald-400/50 bg-emerald-400/15 text-emerald-200"}`}
        >
          {dataLabel(ds).toUpperCase()}
        </p>
      ) : null}

      {/* left column: latest observation + legend */}
      {revealed && session?.latest && !deep.active ? (
        <div className="absolute bottom-[212px] left-4 z-10 hidden flex-col gap-3 md:flex">
          <button type="button" className="nx-chip self-start" aria-expanded={latestOpen} onClick={() => setLatestOpen((o) => !o)}>
            {latestOpen ? "Hide" : "Show"} latest observation
          </button>
          {latestOpen ? <LatestCard latest={session.latest} session={session} /> : null}
          {plan.primary ? <Legend kind={plan.legend} simulated={simulated} classes={ds?.classes} variableLabel={summary?.variable?.label} /> : null}
        </div>
      ) : null}

      {/* mode bar, hotspot navigation, caption */}
      {revealed && ds && !deep.active ? (
        <div className={`absolute inset-x-0 bottom-[196px] z-10 flex flex-col items-center gap-2 px-3 ${panelOpen ? "lg:pr-[420px]" : ""}`}>
          {plan.caption ? (
            <p className="nx-glass pointer-events-none px-3 py-1 text-[12px] text-[color:var(--nx-soft)]" data-testid="map-caption">
              {plan.caption}
              {simulated ? " · Illustrative Dataset" : ""}
              {layerBusy ? " · loading…" : ""}
            </p>
          ) : null}
          {layerError ? (
            <p role="alert" className="nx-glass border-rose-400/40 px-3 py-1 text-[12px] text-rose-200" data-testid="layer-error">
              {layerError}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center justify-center gap-2">
            <ModeBar mode={mode} onMode={(m) => { setMode(m); setPlaying(false); }} hasAnalysis={hasAnalysis} baShowAfter={baShowAfter} onToggleBA={() => setBaShowAfter((v) => !v)} />
            {summary && summary.hotspots.length ? <HotspotNav hotspots={summary.hotspots} active={activeHotspot} onPick={(i) => zoomHotspot(i)} onOverview={overview} /> : null}
            {mode === "swipe" ? (
              <label className="nx-glass flex items-center gap-2 px-3 py-2 text-[12px]">
                Swipe
                <input type="range" min={0.02} max={0.98} step={0.01} value={split} onChange={(e) => setSplit(Number(e.target.value))} aria-label="Swipe position between the earliest and latest observation" />
              </label>
            ) : null}
          </div>
        </div>
      ) : null}
      {mode === "swipe" && revealed && plan.split ? <div className="pointer-events-none absolute inset-y-0 z-[5] w-[2px] bg-white/80 shadow-[0_0_12px_rgba(255,255,255,0.8)]" style={{ left: `${split * 100}%` }} aria-hidden data-testid="swipe-line" /> : null}

      {/* timeline */}
      {revealed && ds && periodObs.length && !deep.active ? (
        <div className={`absolute inset-x-0 bottom-6 z-10 flex justify-center px-3 ${panelOpen ? "lg:pr-[420px]" : ""}`}>
          <Timeline
            observations={periodObs}
            temporal={temporal}
            index={cursorIdx}
            active={mode === "history"}
            onIndex={scrub}
            playing={playing}
            onPlay={togglePlay}
            speed={speed}
            onSpeed={setSpeed}
            onPrev={() => scrub(stepIndex(cursorIdx, periodObs.length, -1))}
            onNext={() => scrub(stepIndex(cursorIdx, periodObs.length, 1))}
            simulated={simulated}
          />
        </div>
      ) : null}

      {/* Deep-Time Earth: time bar and details */}
      {deep.active ? (
        <>
          <div className="absolute inset-x-0 bottom-4 z-10 flex justify-center px-3 lg:pr-[420px]"><DeepTimeBar dt={deep} /></div>
          <div className="absolute right-4 top-[84px] z-10 hidden lg:block"><DeepTimePanel dt={deep} /></div>
        </>
      ) : null}

      {/* summary panel */}
      {summary && panelVisible && !deep.active ? (
        <div className="absolute right-4 top-[84px] z-10">
          <SummaryPanel
            summary={summary}
            explanation={explanation}
            explanationState={summary.analysis_id ? explState : "none"}
            activeHotspot={activeHotspot}
            onHotspot={(i) => zoomHotspot(i)}
            turns={turns}
            asking={asking}
            onAsk={ask}
            collapsed={panelCollapsed}
            onToggle={() => setPanelCollapsed((c) => !c)}
            details={{ location: session?.location ?? null, boundary, dataset: ds, latest: session?.latest ?? null, summary }}
            datasets={(datasets ?? []).filter((d) => !session?.location || (session.location.lon >= d.bbox[0] && session.location.lon <= d.bbox[2] && session.location.lat >= d.bbox[1] && session.location.lat <= d.bbox[3]))}
            activeDatasetId={ds?.id ?? null}
            onPickDataset={pickDataset}
            onPickVariable={pickVariable}
            busy={analysis === "running" || locating}
          />
        </div>
      ) : null}

    </div>
  );
}
