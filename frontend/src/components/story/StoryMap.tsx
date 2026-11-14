"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap, GeoJSONSource, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { GeoJSONFeatureCollection } from "@/lib/earth/types";
import type { GeoInfo, GridFrame, MonthPoint } from "@/lib/types";
import { DRY, WET, anomalyColor, bboxPolygon, canLocate, gridFeatures, heightFor, maxAbsAnomaly, maxValue } from "@/lib/story";

interface Props {
  region: string;
  geo: GeoInfo;
  months: MonthPoint[];
  index: number;
  boundaries: GeoJSONFeatureCollection | null;
  banner: string | null;
  frame?: GridFrame | null;
}

const EMPTY = { type: "FeatureCollection", features: [] };

const BASE_STYLE = {
  version: 8,
  projection: { type: "globe" },
  sources: {
    land: { type: "geojson", data: EMPTY },
    region: { type: "geojson", data: EMPTY },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#0b2a4a" } },
    { id: "land", type: "fill", source: "land", paint: { "fill-color": "#27352d" } },
    { id: "border", type: "line", source: "land", paint: { "line-color": "#6b7f74", "line-width": 0.6 } },
    {
      id: "region-column",
      type: "fill-extrusion",
      source: "region",
      paint: { "fill-extrusion-color": ["get", "color"], "fill-extrusion-height": ["get", "height"], "fill-extrusion-opacity": 0.92 },
    },
    { id: "region-outline", type: "line", source: "region", paint: { "line-color": "#ffffff", "line-width": 1.5 } },
  ],
} as unknown as StyleSpecification;

/** The region polygon: the matching country outline if one exists, otherwise the approximate extent. */
function regionGeometry(region: string, geo: GeoInfo, boundaries: GeoJSONFeatureCollection | null) {
  const hit = boundaries?.features.find(
    (f) => String((f.properties as { name?: string } | null)?.name ?? "").toLowerCase() === region.toLowerCase(),
  );
  if (hit?.geometry) return { geometry: hit.geometry as unknown, outline: "country" as const };
  if (geo.bbox) return { geometry: bboxPolygon(geo.bbox) as unknown, outline: "extent" as const };
  return null;
}

export function StoryMap({ region, geo, months, index, boundaries, banner, frame = null }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);
  const shape = useMemo(() => regionGeometry(region, geo, boundaries), [region, geo, boundaries]);
  const maxAbs = useMemo(() => maxAbsAnomaly(months), [months]);
  const maxVal = useMemo(() => maxValue(months), [months]);
  const current = months[Math.min(index, months.length - 1)];

  useEffect(() => {
    let disposed = false;
    let map: MapLibreMap | undefined;
    (async () => {
      if (!ref.current) return;
      try {
        const ml = await import("maplibre-gl");
        ml.setWorkerUrl("/vendor/maplibre/maplibre-gl-worker.mjs");
        if (disposed || !ref.current) return;
        map = new ml.Map({
          container: ref.current,
          style: BASE_STYLE,
          center: [0, 20],
          zoom: 1.2,
          attributionControl: { compact: true },
          maxPitch: 70,
        });
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

  // Country outlines arrive after the first paint.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("land") as GeoJSONSource | undefined)?.setData((boundaries ?? EMPTY) as never);
  }, [boundaries, ready]);

  // Colour and height for the selected month.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const src = map.getSource("region") as GeoJSONSource | undefined;
    if (!src) return;
    if (frame) {
      src.setData(gridFeatures(frame) as never);
      return;
    }
    if (!shape || !current) {
      src.setData(EMPTY as never);
      return;
    }
    src.setData({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { color: anomalyColor(current.anomaly, maxAbs), height: heightFor(current.value, maxVal) },
          geometry: shape.geometry,
        },
      ],
    } as never);
  }, [shape, current, maxAbs, maxVal, ready, frame]);

  // Fly to the region when it changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !geo.bbox) return;
    const [w, s, e, n] = geo.bbox;
    map.fitBounds([[w, s], [e, n]], { padding: 60, pitch: 40, bearing: -10, duration: 1200, maxZoom: 6 });
  }, [region, geo.bbox, ready]);

  if (fatal) {
    return (
      <div
        role="alert"
        className="flex h-full min-h-[320px] items-center justify-center rounded-lg border border-line bg-surface-muted p-6 text-center text-sm text-ink-soft"
      >
        The 3D map could not start ({fatal}). The summary and chart still work.
      </div>
    );
  }
  return (
    <div className="relative h-full min-h-[360px] overflow-hidden rounded-lg border border-line" data-testid="story-map">
      <div
        ref={ref}
        className="h-full w-full"
        role="img"
        aria-label={`3D map of ${region}. Column height shows the value; colour shows the difference from the usual value for that month.`}
      />
      {banner ? (
        <p role="note" className="absolute left-2 top-2 rounded bg-warn-soft px-2 py-1 text-xs font-semibold text-warn">
          {banner}
        </p>
      ) : null}
      {!canLocate(geo) ? (
        <p className="absolute inset-x-4 bottom-12 rounded bg-black/70 p-2 text-xs text-white">
          This dataset is a single area average with no place geometry, so there is nothing to draw on the map. The numbers are in the summary and chart.
        </p>
      ) : (
        <div className="absolute bottom-2 left-2 rounded bg-black/70 px-2 py-1 text-[11px] text-white">
          <span style={{ color: WET }}>■</span> above usual · <span style={{ color: DRY }}>■</span> below usual · height = value
          <br />
          {frame
            ? `Each cell is a grid cell from the uploaded file; empty cells have no value.${frame.display_note ? " " + frame.display_note : ""}`
            : shape?.outline === "extent"
            ? "Outline is an approximate extent; colour covers the whole region."
            : "Colour covers the whole country; this dataset has no per-place values."}
        </div>
      )}
    </div>
  );
}
