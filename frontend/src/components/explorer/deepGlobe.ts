/**
 * Cesium drawing for Deep-Time Earth. Everything here is a reconstruction drawn from the API; nothing is a satellite
 * observation. Vector layers are built as batched ground primitives (one primitive per layer) so a frame with several
 * thousand polygons stays responsive, and the previous frame is only removed once the next one is ready (no flicker).
 */
import type { PointCollection } from "@/lib/explorer/deeptime";

type Cesium = typeof import("cesium");
type Viewer = import("cesium").Viewer;

export interface DeepVectorSpec {
  /** Unique per frame and layer; used for caching the parsed GeoJSON. */
  key: string;
  url: string;
  fill?: string;
  fillAlpha?: number;
  stroke?: string;
  strokeAlpha?: number;
  strokeWidth?: number;
  /** Keep only features whose properties pass this test. */
  filter?: (p: Record<string, unknown>) => boolean;
}

interface Geo {
  features: { properties: Record<string, unknown>; geometry: { type: string; coordinates: unknown } | null }[];
}

export interface PickedDeep {
  kind: "fossil" | "formation";
  properties: Record<string, unknown>;
}

/**
 * A flat [lon, lat, lon, lat, ...] list for Cesium from a GeoJSON ring: the closing point (equal to the first) and any
 * consecutive duplicates are dropped, because a zero-length edge makes Cesium's ground geometry normalise a zero vector.
 * Returns null for a ring with fewer than three distinct points.
 */
export function cleanRing(ring: number[][]): number[] | null {
  const pts: number[][] = [];
  for (const p of ring) {
    const last = pts[pts.length - 1];
    if (!Number.isFinite(p[0]) || !Number.isFinite(p[1])) continue;
    if (last && Math.abs(last[0] - p[0]) < 1e-6 && Math.abs(last[1] - p[1]) < 1e-6) continue;
    pts.push([p[0], Math.max(-89.99, Math.min(89.99, p[1]))]);
  }
  while (pts.length > 1 && Math.abs(pts[0][0] - pts[pts.length - 1][0]) < 1e-6 && Math.abs(pts[0][1] - pts[pts.length - 1][1]) < 1e-6) pts.pop();
  return pts.length >= 3 ? pts.flat() : null;
}

export class DeepScene {
  private cache = new Map<string, Promise<Geo>>();
  private prims: unknown[] = [];
  private seq = 0;
  private points: import("cesium").PointPrimitiveCollection | null = null;
  private markers: import("cesium").Entity[] = [];
  private baseLayers: { layer: import("cesium").ImageryLayer; was: boolean }[] = [];
  private baseColor: import("cesium").Color | null = null;
  private bg: import("cesium").Color | null = null;

  constructor(private C: Cesium, private viewer: Viewer, private onBusy: (b: boolean) => void) {}

  // ------------------------------------------------------------------------------------ base map
  /** Hide the modern imagery (it would show today's continents) and use a plain ocean colour while in Deep-Time Earth. */
  setActive(active: boolean): void {
    const { C, viewer } = this;
    if (viewer.isDestroyed()) return;
    const layers = viewer.imageryLayers;
    if (active) {
      if (this.baseLayers.length === 0) {
        for (let i = 0; i < layers.length; i++) {
          const l = layers.get(i);
          this.baseLayers.push({ layer: l, was: l.show });
        }
      }
      for (const b of this.baseLayers) b.layer.show = false;
      this.baseColor = viewer.scene.globe.baseColor.clone();
      this.bg = viewer.scene.backgroundColor.clone();
      viewer.scene.globe.baseColor = C.Color.fromCssColorString("#0d3b66");
      viewer.scene.backgroundColor = C.Color.fromCssColorString("#050b1c");
    } else {
      for (const b of this.baseLayers) if (!b.layer.isDestroyed()) b.layer.show = b.was;
      this.baseLayers = [];
      if (this.baseColor) viewer.scene.globe.baseColor = this.baseColor;
      if (this.bg) viewer.scene.backgroundColor = this.bg;
      this.clear();
    }
  }

  // ------------------------------------------------------------------------------------ vectors
  private load(url: string): Promise<Geo> {
    let p = this.cache.get(url);
    if (!p) {
      p = fetch(url).then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json() as Promise<Geo>;
      });
      p.catch(() => this.cache.delete(url));
      this.cache.set(url, p);
      if (this.cache.size > 70) this.cache.delete(this.cache.keys().next().value as string);
    }
    return p;
  }

  async sync(specs: DeepVectorSpec[]): Promise<void> {
    const { C, viewer } = this;
    const mine = ++this.seq;
    this.onBusy(true);
    try {
      const geos = await Promise.all(specs.map((s) => this.load(s.url).catch(() => null)));
      if (mine !== this.seq || viewer.isDestroyed()) return;
      const fresh: unknown[] = [];
      specs.forEach((s, i) => {
        const g = geos[i];
        if (!g) return;
        const polys: number[][][][] = [];
        for (const f of g.features) {
          if (!f.geometry || (s.filter && !s.filter(f.properties))) continue;
          if (f.geometry.type === "Polygon") polys.push(f.geometry.coordinates as number[][][]);
          else if (f.geometry.type === "MultiPolygon") polys.push(...(f.geometry.coordinates as number[][][][]));
        }
        if (!polys.length) return;
        if (s.fill) {
          const color = C.Color.fromCssColorString(s.fill).withAlpha(s.fillAlpha ?? 0.6);
          const instances: import("cesium").GeometryInstance[] = [];
          for (const poly of polys) {
            const outer = cleanRing(poly[0]);
            if (!outer) continue;
            const holes = poly.slice(1).map(cleanRing).filter((h): h is number[] => h != null).map((h) => new C.PolygonHierarchy(C.Cartesian3.fromDegreesArray(h)));
            instances.push(
              new C.GeometryInstance({
                geometry: new C.PolygonGeometry({ polygonHierarchy: new C.PolygonHierarchy(C.Cartesian3.fromDegreesArray(outer), holes), vertexFormat: C.PerInstanceColorAppearance.VERTEX_FORMAT }),
                attributes: { color: C.ColorGeometryInstanceAttribute.fromColor(color) },
              }),
            );
          }
          if (instances.length) fresh.push(new C.GroundPrimitive({ geometryInstances: instances, appearance: new C.PerInstanceColorAppearance({ translucent: true, closed: true }), classificationType: C.ClassificationType.TERRAIN, asynchronous: true }));
        }
        if (s.stroke) {
          const color = C.Color.fromCssColorString(s.stroke).withAlpha(s.strokeAlpha ?? 0.9);
          const lines: import("cesium").GeometryInstance[] = [];
          for (const poly of polys) {
            const ring = cleanRing(poly[0]);
            if (!ring) continue;
            lines.push(new C.GeometryInstance({ geometry: new C.GroundPolylineGeometry({ positions: C.Cartesian3.fromDegreesArray(ring), width: s.strokeWidth ?? 1.5, loop: true }) }));
          }
          if (lines.length) fresh.push(new C.GroundPolylinePrimitive({ geometryInstances: lines, appearance: new C.PolylineMaterialAppearance({ material: C.Material.fromType("Color", { color }) }), asynchronous: true }));
        }
      });
      // Swap: add the new frame, then drop the old one.
      const old = this.prims;
      for (const p of fresh) viewer.scene.groundPrimitives.add(p as never);
      this.prims = fresh;
      for (const p of old) {
        try {
          viewer.scene.groundPrimitives.remove(p as never);
        } catch {
          /* already gone */
        }
      }
    } finally {
      if (mine === this.seq) this.onBusy(false);
    }
  }

  // ------------------------------------------------------------------------------------ points
  setPoints(fc: PointCollection<Record<string, unknown>> | null, kind: PickedDeep["kind"]): void {
    const { C, viewer } = this;
    if (viewer.isDestroyed()) return;
    if (this.points) {
      viewer.scene.primitives.remove(this.points);
      this.points = null;
    }
    if (!fc || !fc.features.length) return;
    const col = new C.PointPrimitiveCollection();
    const color = C.Color.fromCssColorString(kind === "fossil" ? "#fb923c" : "#c084fc");
    for (const f of fc.features) {
      col.add({
        position: C.Cartesian3.fromDegrees(f.geometry.coordinates[0], f.geometry.coordinates[1], 2000),
        pixelSize: 9,
        color,
        outlineColor: C.Color.WHITE,
        outlineWidth: 1.5,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        id: { kind, properties: f.properties } satisfies PickedDeep,
      });
    }
    viewer.scene.primitives.add(col);
    this.points = col;
  }

  // ------------------------------------------------------------------------------------ place markers
  setPlace(place: { name: string; reconstructed: [number, number] | null; modern: [number, number] } | null): void {
    const { C, viewer } = this;
    if (viewer.isDestroyed()) return;
    for (const e of this.markers) viewer.entities.remove(e);
    this.markers = [];
    if (!place) return;
    const label = (text: string, fill: string) => ({
      text,
      font: "600 13px Inter, system-ui, sans-serif",
      fillColor: C.Color.fromCssColorString(fill),
      outlineColor: C.Color.fromCssColorString("#030816"),
      outlineWidth: 3,
      style: C.LabelStyle.FILL_AND_OUTLINE,
      pixelOffset: new C.Cartesian2(0, -22),
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    });
    if (place.reconstructed) {
      this.markers.push(
        viewer.entities.add({
          position: C.Cartesian3.fromDegrees(place.reconstructed[1], place.reconstructed[0]),
          point: { pixelSize: 12, color: C.Color.fromCssColorString("#22d3ee"), outlineColor: C.Color.WHITE, outlineWidth: 2, disableDepthTestDistance: Number.POSITIVE_INFINITY },
          label: label(`${place.name} (plate position then)`, "#a5f3fc"),
        }),
      );
    }
  }

  clear(): void {
    this.seq++;
    const { viewer } = this;
    if (viewer.isDestroyed()) return;
    for (const p of this.prims) {
      try {
        viewer.scene.groundPrimitives.remove(p as never);
      } catch {
        /* ignore */
      }
    }
    this.prims = [];
    this.setPoints(null, "fossil");
    this.setPlace(null);
  }
}
