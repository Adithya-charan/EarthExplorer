"use client";

/**
 * CesiumJS globe. Everything Cesium-specific lives here: the viewer, camera flights, the animated marker, raster
 * overlays (exact lon/lat rectangles from the API), swipe splitting and hotspot outlines. The rest of the app only passes
 * plain props, so it can be tested without WebGL.
 *
 * The base map is Natural Earth II shipped with Cesium (offline), with Esri World Imagery layered on top purely as visual
 * context. Analysis layers are drawn above it and come only from the backend.
 */
import { useEffect, useRef } from "react";
import "cesium/Build/Cesium/Widgets/widgets.css";
import type { LayerSpec } from "@/lib/explorer/logic";
import type { PointCollection } from "@/lib/explorer/deeptime";
import type { BBox, HotspotCollection } from "@/lib/explorer/types";
import { DeepScene, type DeepVectorSpec, type PickedDeep } from "./deepGlobe";

type Cesium = typeof import("cesium");

export interface CameraState {
  lon: number;
  lat: number;
  height: number;
  heading: number;
  pitch: number;
  roll: number;
}

export type GlobeFocus =
  | { kind: "place"; token: number; lon: number; lat: number; altitude: number; bbox: BBox | null }
  | { kind: "sphere"; token: number; lon: number; lat: number; radius: number }
  | ({ kind: "camera"; token: number } & CameraState);

export interface BoundaryShape {
  id: string;
  geometry: { type: string; coordinates: unknown };
  /** Approximate outlines are drawn dashed and amber so they are never mistaken for an authoritative boundary. */
  approximate: boolean;
}

export interface DeepGlobeState {
  active: boolean;
  vectors: DeepVectorSpec[];
  points: PointCollection<Record<string, unknown>> | null;
  pointKind: PickedDeep["kind"];
  place: { name: string; reconstructed: [number, number] | null; modern: [number, number] } | null;
}

export interface GlobeProps {
  deep?: DeepGlobeState;
  onDeepPick?: (p: PickedDeep) => void;
  focus: GlobeFocus | null;
  marker: { lon: number; lat: number; label: string } | null;
  primary: LayerSpec | null;
  secondary: LayerSpec | null;
  prefetch: LayerSpec[];
  splitPosition: number;
  hotspots: HotspotCollection | null;
  boundary?: BoundaryShape | null;
  onCamera?: (c: CameraState) => void;
  showHotspots: boolean;
  activeHotspot: string | null;
  spin: boolean;
  reducedMotion: boolean;
  onReady: () => void;
  onUnsupported: (message: string) => void;
  onInteract: () => void;
  onFlightEnd: (token: number) => void;
  onLayerBusy: (busy: boolean) => void;
  onLayerError: (message: string | null) => void;
}

interface Slot {
  key: string;
  layer: import("cesium").ImageryLayer;
}

const LOSS = "#ff4d5e";
const GAIN = "#35e08a";

export default function Globe(props: GlobeProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const propsRef = useRef(props);
  const cesiumRef = useRef<Cesium | null>(null);
  const viewerRef = useRef<import("cesium").Viewer | null>(null);
  const slotsRef = useRef<{ primary: Slot | null; secondary: Slot | null }>({ primary: null, secondary: null });
  const seqRef = useRef({ primary: 0, secondary: 0 });
  const pendingRef = useRef(0);
  const providerCache = useRef(new Map<string, Promise<import("cesium").SingleTileImageryProvider>>());
  const markerRef = useRef<import("cesium").Entity[]>([]);
  const hotspotRef = useRef<import("cesium").Entity[]>([]);
  const boundaryRef = useRef<import("cesium").Entity[]>([]);
  const lastFocus = useRef(0);
  const readyRef = useRef(false);
  const syncRef = useRef<() => void>(() => undefined);
  const deepRef = useRef<DeepScene | null>(null);

  useEffect(() => {
    propsRef.current = props;
  });

  // ------------------------------------------------------------------------------ viewer lifecycle
  useEffect(() => {
    let destroyed = false;
    let viewer: import("cesium").Viewer | null = null;
    (async () => {
      try {
        (window as unknown as { CESIUM_BASE_URL: string }).CESIUM_BASE_URL = "/vendor/cesium";
        const C = await import("cesium");
        if (destroyed || !containerRef.current) return;
        cesiumRef.current = C;
        viewer = new C.Viewer(containerRef.current, {
          baseLayer: false,
          baseLayerPicker: false,
          geocoder: false,
          homeButton: false,
          sceneModePicker: false,
          navigationHelpButton: false,
          animation: false,
          timeline: false,
          fullscreenButton: false,
          infoBox: false,
          selectionIndicator: false,
          vrButton: false,
          scene3DOnly: true,
        });
        viewerRef.current = viewer;
        const scene = viewer.scene;
        scene.backgroundColor = C.Color.fromCssColorString("#030816");
        scene.globe.baseColor = C.Color.fromCssColorString("#06122b");
        scene.globe.showGroundAtmosphere = true;
        scene.globe.enableLighting = false;
        if (scene.skyAtmosphere) scene.skyAtmosphere.show = true;
        scene.screenSpaceCameraController.minimumZoomDistance = 60;
        scene.screenSpaceCameraController.maximumZoomDistance = 40_000_000;
        viewer.camera.setView({ destination: C.Cartesian3.fromDegrees(78, 18, 21_000_000) });

        // Offline base map, then Esri imagery as visual context (failures leave the offline map visible).
        const natural = await C.TileMapServiceImageryProvider.fromUrl(C.buildModuleUrl("Assets/Textures/NaturalEarthII"));
        if (destroyed) return;
        viewer.imageryLayers.addImageryProvider(natural);
        const esri = new C.UrlTemplateImageryProvider({
          url: "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
          maximumLevel: 18,
          credit: "Basemap imagery © Esri, Maxar, Earthstar Geographics (context only)",
        });
        esri.errorEvent.addEventListener((e) => {
          e.retry = false;
        });
        viewer.imageryLayers.addImageryProvider(esri);
        deepRef.current = new DeepScene(C, viewer, (b) => propsRef.current.onLayerBusy(b));

        viewer.scene.preRender.addEventListener(() => {
          if (propsRef.current.spin && !propsRef.current.reducedMotion) viewer!.camera.rotate(C.Cartesian3.UNIT_Z, -0.0005);
        });
        viewer.camera.moveEnd.addEventListener(() => {
          const v = viewerRef.current;
          if (!v || v.isDestroyed()) return;
          const c = v.camera.positionCartographic;
          propsRef.current.onCamera?.({ lon: C.Math.toDegrees(c.longitude), lat: C.Math.toDegrees(c.latitude), height: c.height, heading: v.camera.heading, pitch: v.camera.pitch, roll: v.camera.roll });
        });
        const handler = new C.ScreenSpaceEventHandler(viewer.canvas);
        handler.setInputAction((m: { position: import("cesium").Cartesian2 }) => {
          const picked = viewer!.scene.pick(m.position) as { id?: PickedDeep } | undefined;
          if (picked?.id && (picked.id.kind === "fossil" || picked.id.kind === "formation")) propsRef.current.onDeepPick?.(picked.id);
        }, C.ScreenSpaceEventType.LEFT_CLICK);
        for (const t of [C.ScreenSpaceEventType.LEFT_DOWN, C.ScreenSpaceEventType.WHEEL, C.ScreenSpaceEventType.PINCH_START, C.ScreenSpaceEventType.RIGHT_DOWN]) {
          handler.setInputAction(() => propsRef.current.onInteract(), t);
        }
        readyRef.current = true;
        propsRef.current.onReady();
        // Apply whatever was requested while Cesium was loading.
        syncRef.current();
      } catch (err) {
        if (!destroyed) propsRef.current.onUnsupported(err instanceof Error ? err.message : "The 3D globe could not start.");
      }
    })();
    return () => {
      destroyed = true;
      readyRef.current = false;
      try {
        if (viewer && !viewer.isDestroyed()) viewer.destroy();
      } catch {
        /* ignore teardown errors */
      }
      viewerRef.current = null;
      slotsRef.current = { primary: null, secondary: null };
      deepRef.current = null;
    };
     
  }, []);

  const getProvider = (spec: LayerSpec) => {
    const C = cesiumRef.current!;
    const key = `${spec.url}|${spec.bbox.join(",")}`;
    let p = providerCache.current.get(key);
    if (!p) {
      p = C.SingleTileImageryProvider.fromUrl(spec.url, { rectangle: C.Rectangle.fromDegrees(...spec.bbox) });
      p.catch(() => providerCache.current.delete(key));
      providerCache.current.set(key, p);
      if (providerCache.current.size > 60) providerCache.current.delete(providerCache.current.keys().next().value as string);
    }
    return p;
  };

  const setBusy = (delta: number) => {
    pendingRef.current = Math.max(0, pendingRef.current + delta);
    propsRef.current.onLayerBusy(pendingRef.current > 0);
  };

  const applySlot = (slot: "primary" | "secondary", spec: LayerSpec | null) => {
    const C = cesiumRef.current;
    const viewer = viewerRef.current;
    if (!C || !viewer || viewer.isDestroyed()) return;
    const cur = slotsRef.current[slot];
    const dir = (side: LayerSpec["side"]) => (side === "left" ? C.SplitDirection.LEFT : side === "right" ? C.SplitDirection.RIGHT : C.SplitDirection.NONE);
    if (!spec) {
      seqRef.current[slot]++;
      if (cur) viewer.imageryLayers.remove(cur.layer, true);
      slotsRef.current[slot] = null;
      return;
    }
    if (cur && cur.key === spec.key) {
      cur.layer.alpha = spec.alpha;
      cur.layer.splitDirection = dir(spec.side);
      return;
    }
    const mine = ++seqRef.current[slot];
    setBusy(1);
    getProvider(spec)
      .then((provider) => {
        if (viewer.isDestroyed() || mine !== seqRef.current[slot]) return;
        const layer = viewer.imageryLayers.addImageryProvider(provider);
        layer.alpha = spec.alpha;
        layer.splitDirection = dir(spec.side);
        const old = slotsRef.current[slot];
        slotsRef.current[slot] = { key: spec.key, layer };
        if (old) viewer.imageryLayers.remove(old.layer, true); // old layer stays until the new one is in place: no flicker
        propsRef.current.onLayerError(null);
      })
      .catch(() => {
        if (mine === seqRef.current[slot]) propsRef.current.onLayerError("That map layer could not be loaded. The observation may be missing or unreadable.");
      })
      .finally(() => setBusy(-1));
  };

  const applyMarker = () => {
    const C = cesiumRef.current;
    const viewer = viewerRef.current;
    if (!C || !viewer || viewer.isDestroyed()) return;
    for (const e of markerRef.current) viewer.entities.remove(e);
    markerRef.current = [];
    const m = propsRef.current.marker;
    if (!m) return;
    const still = propsRef.current.reducedMotion;
    const pos = C.Cartesian3.fromDegrees(m.lon, m.lat);
    const t0 = performance.now();
    const phase = () => ((performance.now() - t0) % 2400) / 2400;
    const heightM = () => Math.max(300, viewer.camera.positionCartographic.height);
    const ring = (offset: number) => {
      // One radius per frame, shared by both axes (Cesium requires semiMajorAxis >= semiMinorAxis).
      let lastT = -1;
      let lastR = 0;
      let lastA = 0;
      const sample = () => {
        const t = performance.now();
        if (t - lastT > 6) {
          lastT = t;
          const ph = (phase() + offset) % 1;
          lastR = still ? heightM() * 0.02 : heightM() * (0.004 + 0.03 * ph);
          lastA = still ? 0.25 : 0.55 * (1 - ph);
        }
      };
      return viewer.entities.add({
        position: pos,
        ellipse: {
          semiMajorAxis: new C.CallbackProperty(() => (sample(), lastR), false),
          semiMinorAxis: new C.CallbackProperty(() => (sample(), lastR), false),
          material: new C.ColorMaterialProperty(new C.CallbackProperty(() => (sample(), C.Color.fromCssColorString("#38bdf8").withAlpha(lastA)), false)),
          outline: false,
        },
      });
    };
    markerRef.current.push(ring(0), ring(0.5));
    markerRef.current.push(
      viewer.entities.add({
        position: pos,
        point: { pixelSize: 11, color: C.Color.fromCssColorString("#38bdf8"), outlineColor: C.Color.WHITE, outlineWidth: 2, disableDepthTestDistance: Number.POSITIVE_INFINITY },
        label: {
          text: m.label,
          font: "600 14px Inter, system-ui, sans-serif",
          fillColor: C.Color.WHITE,
          outlineColor: C.Color.fromCssColorString("#030816"),
          outlineWidth: 3,
          style: C.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new C.Cartesian2(0, -24),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          scaleByDistance: new C.NearFarScalar(1e3, 1.1, 8e6, 0.7),
        },
      }),
    );
  };

  const applyHotspots = () => {
    const C = cesiumRef.current;
    const viewer = viewerRef.current;
    if (!C || !viewer || viewer.isDestroyed()) return;
    for (const e of hotspotRef.current) viewer.entities.remove(e);
    hotspotRef.current = [];
    const p = propsRef.current;
    if (!p.showHotspots || !p.hotspots) return;
    for (const f of p.hotspots.features) {
      const base = C.Color.fromCssColorString(f.properties.kind === "loss" ? LOSS : GAIN);
      const active = p.activeHotspot === f.properties.id;
      const polys: number[][][][] = f.geometry.type === "Polygon" ? [f.geometry.coordinates as number[][][]] : (f.geometry.coordinates as number[][][][]);
      for (const poly of polys) {
        const ring = poly[0].flat();
        hotspotRef.current.push(
          viewer.entities.add({
            polygon: { hierarchy: C.Cartesian3.fromDegreesArray(ring), material: base.withAlpha(active ? 0.38 : 0.16), classificationType: C.ClassificationType.TERRAIN },
            polyline: { positions: C.Cartesian3.fromDegreesArray(ring), width: active ? 4 : 2.5, material: base, clampToGround: true },
          }),
        );
      }
      const coords = polys[0][0];
      const cx = coords.reduce((a, c) => a + c[0], 0) / coords.length;
      const cy = coords.reduce((a, c) => a + c[1], 0) / coords.length;
      hotspotRef.current.push(
        viewer.entities.add({
          position: C.Cartesian3.fromDegrees(cx, cy),
          label: {
            text: `#${f.properties.rank}`,
            font: "700 13px Inter, system-ui, sans-serif",
            fillColor: C.Color.WHITE,
            outlineColor: C.Color.fromCssColorString("#030816"),
            outlineWidth: 3,
            style: C.LabelStyle.FILL_AND_OUTLINE,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            scaleByDistance: new C.NearFarScalar(500, 1.1, 60_000, 0.8),
            translucencyByDistance: new C.NearFarScalar(500, 1, 120_000, 0),
          },
        }),
      );
    }
  };

  const applyBoundary = () => {
    const C = cesiumRef.current;
    const viewer = viewerRef.current;
    if (!C || !viewer || viewer.isDestroyed()) return;
    for (const e of boundaryRef.current) viewer.entities.remove(e);
    boundaryRef.current = [];
    const b = propsRef.current.boundary;
    if (!b || !b.geometry) return;
    const color = C.Color.fromCssColorString(b.approximate ? "#fbbf24" : "#22d3ee");
    const polys: number[][][][] = b.geometry.type === "Polygon" ? [b.geometry.coordinates as number[][][]] : b.geometry.type === "MultiPolygon" ? (b.geometry.coordinates as number[][][][]) : [];
    for (const poly of polys) {
      const outer = poly[0].flat();
      if (outer.length < 6) continue;
      const holes = poly.slice(1).map((h) => new C.PolygonHierarchy(C.Cartesian3.fromDegreesArray(h.flat())));
      boundaryRef.current.push(
        viewer.entities.add({
          polygon: { hierarchy: new C.PolygonHierarchy(C.Cartesian3.fromDegreesArray(outer), holes), material: color.withAlpha(b.approximate ? 0.05 : 0.08), classificationType: C.ClassificationType.TERRAIN },
          polyline: {
            positions: C.Cartesian3.fromDegreesArray(outer),
            width: b.approximate ? 2.5 : 3,
            clampToGround: true,
            material: b.approximate ? new C.PolylineDashMaterialProperty({ color, dashLength: 14 }) : new C.PolylineGlowMaterialProperty({ color, glowPower: 0.18 }),
          },
        }),
      );
    }
  };

  // ------------------------------------------------------------------------------------ camera
  const flyTo = (f: GlobeFocus) => {
    const C = cesiumRef.current;
    const viewer = viewerRef.current;
    if (!C || !viewer || viewer.isDestroyed() || f.token === lastFocus.current) return;
    lastFocus.current = f.token;
    const cam = viewer.camera;
    const reduced = propsRef.current.reducedMotion;
    cam.cancelFlight();
    const done = () => propsRef.current.onFlightEnd(f.token);
    const topDown = { heading: 0, pitch: -C.Math.PI_OVER_TWO, roll: 0 };
    if (f.kind === "camera") {
      const dest = C.Cartesian3.fromDegrees(f.lon, f.lat, f.height);
      if (reduced) {
        cam.setView({ destination: dest, orientation: { heading: f.heading, pitch: f.pitch, roll: f.roll } });
        done();
      } else {
        cam.flyTo({ destination: dest, orientation: { heading: f.heading, pitch: f.pitch, roll: f.roll }, duration: 1.8, easingFunction: C.EasingFunction.QUADRATIC_IN_OUT, complete: done, cancel: done });
      }
      return;
    }
    if (f.kind === "sphere") {
      const sphere = new C.BoundingSphere(C.Cartesian3.fromDegrees(f.lon, f.lat), f.radius);
      const offset = new C.HeadingPitchRange(0, -C.Math.PI_OVER_TWO, f.radius * 3.4);
      if (reduced) {
        cam.viewBoundingSphere(sphere, offset);
        cam.lookAtTransform(C.Matrix4.IDENTITY);
        done();
      } else {
        cam.flyToBoundingSphere(sphere, { duration: 1.9, offset, complete: done, easingFunction: C.EasingFunction.QUADRATIC_IN_OUT });
      }
      return;
    }
    let destination: import("cesium").Cartesian3;
    if (f.bbox) {
      const [w, s, e, n] = f.bbox;
      const padX = (e - w) * 0.18;
      const padY = (n - s) * 0.18;
      destination = cam.getRectangleCameraCoordinates(C.Rectangle.fromDegrees(w - padX, s - padY, e + padX, n + padY));
    } else {
      destination = C.Cartesian3.fromDegrees(f.lon, f.lat, f.altitude);
    }
    if (reduced) {
      cam.setView({ destination, orientation: topDown });
      done();
      return;
    }
    // Stage 1: turn the globe toward the place from high up. Stage 2: descend onto it.
    const cruise = Math.max(f.altitude * 2.2, 2_800_000);
    cam.flyTo({
      destination: C.Cartesian3.fromDegrees(f.lon, f.lat, cruise),
      orientation: topDown,
      duration: 2.3,
      easingFunction: C.EasingFunction.QUADRATIC_IN_OUT,
      complete: () => cam.flyTo({ destination, orientation: topDown, duration: 2.8, easingFunction: C.EasingFunction.QUADRATIC_IN_OUT, complete: done, cancel: done }),
      cancel: done,
    });
  };

  const applyDeep = () => {
    const d = propsRef.current.deep;
    const sc = deepRef.current;
    if (!sc) return;
    sc.setActive(Boolean(d?.active));
    if (d?.active) {
      void sc.sync(d.vectors);
      sc.setPoints(d.points, d.pointKind);
      sc.setPlace(d.place);
    }
  };

  const syncAll = () => {
    applyDeep();
    const p = propsRef.current;
    applySlot("primary", p.primary);
    applySlot("secondary", p.secondary);
    applyMarker();
    applyHotspots();
    applyBoundary();
    const v = viewerRef.current;
    if (v && !v.isDestroyed()) v.scene.splitPosition = p.splitPosition;
    if (p.focus) flyTo(p.focus);
  };

  useEffect(() => {
    syncRef.current = syncAll;
  });

  // --------------------------------------------------------------------------------- reactions
  useEffect(() => {
    if (readyRef.current) applySlot("primary", props.primary);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.primary?.key, props.primary?.alpha, props.primary?.side]);
  useEffect(() => {
    if (readyRef.current) applySlot("secondary", props.secondary);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.secondary?.key, props.secondary?.alpha, props.secondary?.side]);
  useEffect(() => {
    if (readyRef.current) applyMarker();
     
  }, [props.marker?.lon, props.marker?.lat, props.marker?.label, props.reducedMotion]);
  useEffect(() => {
    if (readyRef.current) applyHotspots();
     
  }, [props.hotspots, props.showHotspots, props.activeHotspot]);
  useEffect(() => {
    if (readyRef.current) applyBoundary();
  }, [props.boundary?.id, props.boundary?.approximate]);
  useEffect(() => {
    if (!readyRef.current || !deepRef.current) return;
    deepRef.current.setActive(Boolean(props.deep?.active));
    if (props.deep?.active) void deepRef.current.sync(props.deep.vectors);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.deep?.active, props.deep?.vectors.map((v) => v.key).join("|")]);
  useEffect(() => {
    if (readyRef.current && deepRef.current && props.deep?.active) deepRef.current.setPoints(props.deep.points, props.deep.pointKind);
  }, [props.deep?.active, props.deep?.points, props.deep?.pointKind]);
  useEffect(() => {
    if (readyRef.current && deepRef.current && props.deep?.active) deepRef.current.setPlace(props.deep.place);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.deep?.active, props.deep?.place?.name, props.deep?.place?.reconstructed?.join(",")]);
  useEffect(() => {
    const v = viewerRef.current;
    if (readyRef.current && v && !v.isDestroyed()) v.scene.splitPosition = props.splitPosition;
  }, [props.splitPosition]);
  useEffect(() => {
    if (readyRef.current && props.focus) flyTo(props.focus);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.focus?.token]);
  useEffect(() => {
    if (!readyRef.current) return;
    for (const spec of props.prefetch) getProvider(spec).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.prefetch.map((s) => s.key).join("|")]);

  return <div ref={containerRef} className="nx-globe absolute inset-0" data-testid="globe" />;
}
