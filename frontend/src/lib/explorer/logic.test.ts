import { describe, expect, it } from "vitest";
import { bboxRadiusM, fmtDate, nearestIndex, observationsInPeriod, planLayers, stepIndex, timelinePositions, unionBBox } from "./logic";
import type { ChangeSummary, ObservationInfo } from "./types";

const obs = (date: string): ObservationInfo => ({ date, quality: "good", valid_fraction: 1, usable: true, water_share: 0.5, sensor: null });
const BBOX: [number, number, number, number] = [77.6, 12.9, 77.7, 13.0];

const summary = {
  outcome: "change_detected",
  analysis_id: "abc",
  first_observation: { date: "2005-01-01", quality: "good", valid_fraction: 1, layer_url: "" },
  last_observation: { date: "2015-12-01", quality: "good", valid_fraction: 1, layer_url: "" },
  layers: { difference_png: "/api/explorer/analysis/abc/layers/difference.png" },
} as unknown as ChangeSummary;

const base = { summary, datasetId: "ds", bbox: BBOX, latestDate: "2025-12-01", cursorDate: "2010-05-01", baShowAfter: false, temporal: "monthly" };

describe("explorer logic", () => {
  it("formats dates by temporal resolution", () => {
    expect(fmtDate("2012-09-01", "monthly")).toBe("Sep 2012");
    expect(fmtDate("2012-09-01", "yearly")).toBe("2012");
  });

  it("places observations by date so gaps stay visible and never snaps to a missing date", () => {
    const dates = ["2000-01-01", "2000-02-01", "2001-01-01"];
    const pos = timelinePositions(dates);
    expect(pos[0]).toBe(0);
    expect(pos[2]).toBe(1);
    expect(pos[1]).toBeLessThan(0.15);
    expect(nearestIndex(pos, 0.5)).toBe(1); // the cursor lands on an existing observation
    expect(timelinePositions(["2000-01-01"])).toEqual([0.5]);
    expect(timelinePositions([])).toEqual([]);
  });

  it("steps and clamps the cursor", () => {
    expect(stepIndex(0, 5, -1)).toBe(0);
    expect(stepIndex(4, 5, 1)).toBe(4);
    expect(stepIndex(4, 5, 1, true)).toBe(0);
    expect(stepIndex(2, 5, 1)).toBe(3);
  });

  it("keeps only observations inside the period", () => {
    const all = [obs("1999-01-01"), obs("2005-06-01"), obs("2010-01-01"), obs("2020-01-01")];
    expect(observationsInPeriod(all, 2000, 2015).map((o) => o.date)).toEqual(["2005-06-01", "2010-01-01"]);
  });

  it("chooses real layers for every map mode", () => {
    expect(planLayers({ ...base, mode: "latest" }).primary?.url).toContain("/observations/2025-12-01/layer.png");
    expect(planLayers({ ...base, mode: "history" }).primary?.url).toContain("/observations/2010-05-01/layer.png");
    expect(planLayers({ ...base, mode: "beforeafter" }).primary?.url).toContain("2005-01-01");
    expect(planLayers({ ...base, mode: "beforeafter", baShowAfter: true }).primary?.url).toContain("2015-12-01");
    const swipe = planLayers({ ...base, mode: "swipe" });
    expect(swipe.split).toBe(true);
    expect([swipe.primary?.side, swipe.secondary?.side]).toEqual(["left", "right"]);
    const hot = planLayers({ ...base, mode: "hotspots" });
    expect(hot.hotspots).toBe(true);
    expect(hot.legend).toBe("diff");
    expect(hot.primary?.url).toContain("difference.png");
    expect(planLayers({ ...base, mode: "difference" }).hotspots).toBe(false);
  });

  it("draws no analysis layer when there is no analysis", () => {
    const none = { ...summary, outcome: "insufficient_data", analysis_id: null } as unknown as ChangeSummary;
    expect(planLayers({ ...base, summary: none, mode: "difference" }).primary).toBeNull();
    expect(planLayers({ ...base, datasetId: null, mode: "latest" }).primary).toBeNull();
  });

  it("frames hotspots", () => {
    expect(unionBBox([[0, 0, 1, 1], [2, -1, 3, 0.5]])).toEqual([0, -1, 3, 1]);
    expect(unionBBox([])).toBeNull();
    expect(bboxRadiusM([77.6, 12.9, 77.61, 12.91])).toBeGreaterThan(500);
  });
});
