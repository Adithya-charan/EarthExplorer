import { describe, expect, it } from "vitest";
import { anomalyColor, gridFeatures, heightFor } from "./story";
import { provenance } from "@/test/fixtures";
import type { GridFrame } from "./types";

const frame = (over: Partial<GridFrame> = {}): GridFrame => ({
  provenance,
  dataset_id: "x",
  variable: "p",
  unit: "mm/hr",
  date: "2020-01-01",
  lat: [10, 11],
  lon: [70, 71, 72],
  values: [[1, null, 3], [2, 2, 2]],
  anomaly: [[0.5, null, -0.5], [0, 0.2, -0.2]],
  value_min: 1,
  value_max: 3,
  anomaly_abs_max: 0.5,
  display_note: null,
  note: "",
  ...over,
});

describe("story map helpers", () => {
  it("draws one polygon per valid cell and never invents a cell for a missing value", () => {
    const f = gridFeatures(frame());
    expect(f.features).toHaveLength(5);
  });

  it("sizes cells from the neighbouring coordinates", () => {
    const g = gridFeatures(frame()).features[0].geometry.coordinates[0];
    expect(g[0]).toEqual([69.5, 9.5]);
    expect(g[2]).toEqual([70.5, 10.5]);
  });

  it("colours by direction of the anomaly and falls back to neutral grey without data", () => {
    expect(anomalyColor(1, 1)).toBe("rgb(0,114,178)");
    expect(anomalyColor(-1, 1)).toBe("rgb(213,94,0)");
    expect(anomalyColor(null, 1)).toBe("#8a97a6");
    expect(anomalyColor(0.3, 0)).toBe("#8a97a6");
  });

  it("uses value colouring when the grid has no anomaly baseline", () => {
    const f = gridFeatures(frame({ anomaly: null, anomaly_abs_max: null }));
    expect(f.features).toHaveLength(5);
    expect(heightFor(null, 3)).toBe(0);
  });
});
