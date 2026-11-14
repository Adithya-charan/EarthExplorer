"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap, GeoJSONSource, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { GeoJSONFeatureCollection } from "@/lib/earth/types";
import type { SnapshotResponse } from "@/lib/types";
import { DRY, WET, anomalyColor, bboxPolygon, heightFor } from "@/lib/story";

const EMPTY = { type: "FeatureCollection", features: [] };
const HALF = 0.55; // half-width of a marker tile, in degrees
const Z_MONTH = 2.5; // full colour at ±2.5 SD for a single month
const Z_YEAR = 0.8; // yearly means vary much less than single months, so full colour comes sooner
const HEIGHT_SCALE = 0.4; // tiles stay shorter than the 3D story map's columns so neighbours do not hide each other

const BASE_STYLE = {
  version: 8,
  projection: { type: "globe" },
  sources: { land: { type: "geojson", data: EMPTY }, places: { type: "geojson", data: EMPTY } },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#0b2a4a" } },
    { id: "land", type: "fill", source: "land", paint: { "fill-color": "#27352d" } },
    { id: "border", type: "line", source: "land", paint: { "line-color": "#6b7f74", "line-width": 0.6 } },
    {
      id: "tiles",
      type: "fill-extrusion",
      source: "places",
      paint: { "fill-extrusion-color": ["get", "color"], "fill-extrusion-height": ["get", "height"], "fill-extrusion-opacity": 0.95 },
    },
  ],
} as unknown as StyleSpecification;

/** One marker tile per located region, coloured by how far from usual and raised by value. Regions without a value are not drawn. */
export function placeFeatures(s: SnapshotResponse, valueMax: number) {
  const features = s.points
    .filter((p) => p.value !== null)
    .map((p) => ({
      type: "Feature" as const,
      properties: { region: p.region, color: anomalyColor(p.z, s.month === 0 ? Z_YEAR : Z_MONTH), height: heightFor(p.value, valueMax) * HEIGHT_SCALE },
      geometry: bboxPolygon([p.lon - HALF, p.lat - HALF, p.lon + HALF, p.lat + HALF]),
    }));
  return { type: "FeatureCollection" as const, features };
}

export function PlacesMap({ snapshot, boundaries, valueMax }: { snapshot: SnapshotResponse | null; boundaries: GeoJSONFeatureCollection | null; valueMax: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);
  const fitted = useRef(false);
  const features = useMemo(() => (snapshot ? placeFeatures(snapshot, valueMax) : null), [snapshot, valueMax]);

  useEffect(() => {
    let disposed = false;
    let map: MapLibreMap | undefined;
    (async () => {
      if (!ref.current) return;
      try {
        const ml = await import("maplibre-gl");
        ml.setWorkerUrl("/vendor/maplibre/maplibre-gl-worker.mjs");
        if (disposed || !ref.current) return;
        map = new ml.Map({ container: ref.current, style: BASE_STYLE, center: [82, 21], zoom: 3.2, pitch: 40, bearing: -8, attributionControl: { compact: true }, maxPitch: 75 });
        map.addControl(new ml.NavigationControl({ visualizePitch: true }), "bottom-right");
        map.on("load", () => {
          if (!disposed) setReady(true);
        });
        mapRef.current = map;
      } catch (err) {
        if (!disposed) setFatal(err instanceof Error ? err.message : "WebGL is not available");
      }
    })();
    return () => {
      disposed = true;
      map?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("land") as GeoJSONSource | undefined)?.setData((boundaries ?? EMPTY) as never);
  }, [boundaries, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    // While the next frame loads, keep showing the last one instead of flashing empty.
    if (features) (map.getSource("places") as GeoJSONSource | undefined)?.setData(features as never);
    if (!fitted.current && snapshot && snapshot.points.length) {
      fitted.current = true;
      const lons = snapshot.points.map((p) => p.lon);
      const lats = snapshot.points.map((p) => p.lat);
      const spanLon = Math.max(...lons) - Math.min(...lons) + 6;
      const spanLat = Math.max(...lats) - Math.min(...lats) + 6;
      const width = map.getContainer().clientWidth || 700;
      const zoom = Math.max(1.5, Math.min(6, Math.log2((width * 360) / (Math.max(spanLon, spanLat * 1.4) * 512))));
      map.jumpTo({ center: [(Math.max(...lons) + Math.min(...lons)) / 2, (Math.max(...lats) + Math.min(...lats)) / 2 - 1], zoom, pitch: 40, bearing: -8 });
    }
  }, [features, ready, snapshot]);

  if (fatal) {
    return (
      <div role="alert" className="flex h-full min-h-[320px] items-center justify-center rounded-lg border border-line bg-surface-muted p-6 text-center text-sm text-ink-soft">
        The 3D map could not start ({fatal}). The list and charts still work.
      </div>
    );
  }
  return (
    <div className="relative h-full min-h-[380px] overflow-hidden rounded-lg border border-line" data-testid="places-map">
      <div ref={ref} className="h-full w-full" role="img" aria-label="3D map with one column per region. Height shows the value, colour the difference from usual." />
      {snapshot?.banner ? (
        <p role="note" className="absolute left-2 top-2 rounded bg-warn-soft px-2 py-1 text-xs font-semibold text-warn">
          {snapshot.banner}
        </p>
      ) : null}
      <div className="absolute bottom-2 left-2 max-w-[85%] rounded bg-black/70 px-2 py-1 text-[11px] text-white">
        <span style={{ color: WET }}>■</span> above usual · <span style={{ color: DRY }}>■</span> below usual · height = value
        <br />
        Tiles sit at each region&apos;s approximate centre; they are not boundaries.
      </div>
    </div>
  );
}
