import { describe, expect, it } from "vitest";
import { changeMetrics, decimalYear, fitTrend, indexSeries, primaryVariable, type StatVariable } from "./analytics";

const pt = (date: string, area_ha: number, share = 10) => ({ date, area_ha, share_of_valid_pct: share });

describe("decimalYear", () => {
  it("places mid-year dates after the year start", () => {
    expect(decimalYear("2000-01-01")).toBe(2000);
    expect(decimalYear("2010-07-01")).toBeCloseTo(2010.5, 1);
  });
});

describe("fitTrend", () => {
  it("returns null for fewer than two points or identical x", () => {
    expect(fitTrend([{ x: 1, y: 1 }])).toBeNull();
    expect(fitTrend([{ x: 1, y: 1 }, { x: 1, y: 2 }])).toBeNull();
  });
  it("recovers an exact line", () => {
    const f = fitTrend([0, 1, 2, 3].map((x) => ({ x, y: 5 + 2 * x })))!;
    expect(f.slope).toBeCloseTo(2);
    expect(f.intercept).toBeCloseTo(5);
    expect(f.r2).toBeCloseTo(1);
    expect(f.theilSen).toBeCloseTo(2);
  });
  it("gives no robust slope with only two points", () => {
    expect(fitTrend([{ x: 0, y: 0 }, { x: 1, y: 3 }])!.theilSen).toBeNull();
  });
  it("Theil-Sen resists one outlier", () => {
    const f = fitTrend([{ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 2, y: 2 }, { x: 3, y: 3 }, { x: 4, y: 40 }])!;
    expect(f.theilSen).toBeCloseTo(1, 0);
    expect(f.slope).toBeGreaterThan(5);
  });
});

describe("changeMetrics", () => {
  it("is null for a single snapshot", () => {
    expect(changeMetrics([pt("2021-01-01", 100)])).toBeNull();
  });
  it("computes net, rate and compound growth", () => {
    const m = changeMetrics([pt("2000-01-01", 100, 10), pt("2010-01-01", 150, 15), pt("2020-01-01", 200, 20)])!;
    expect(m.netHa).toBe(100);
    expect(m.netPct).toBe(100);
    expect(m.years).toBe(20);
    expect(m.haPerYear).toBe(5);
    expect(m.cagrPct).toBeCloseTo(3.53, 1);
    expect(m.shareChangePts).toBe(10);
  });
  it("sorts unordered input and handles a zero start", () => {
    const m = changeMetrics([pt("2010-01-01", 5), pt("2000-01-01", 0)])!;
    expect(m.first.date).toBe("2000-01-01");
    expect(m.netPct).toBeNull();
    expect(m.cagrPct).toBeNull();
  });
});

describe("indexSeries / primaryVariable", () => {
  const vars: Record<string, StatVariable> = {
    a: { label: "A", classes: 2, primary: false, series: [pt("2000-01-01", 50), pt("2010-01-01", 100)] },
    b: { label: "B", classes: 2, primary: true, series: [pt("2000-01-01", 10), pt("2010-01-01", 5)] },
    c: { label: "C", classes: 2, primary: false, series: [pt("2000-01-01", 10)] },
  };
  it("scales each variable to 100 at its start and drops single snapshots", () => {
    const { rows, keys } = indexSeries(vars);
    expect(keys).toEqual(["a", "b"]);
    expect(rows[0].a).toBe(100);
    expect(rows[1].a).toBe(200);
    expect(rows[1].b).toBe(50);
  });
  it("prefers the primary variable", () => {
    expect(primaryVariable({ variables: vars } as never)![0]).toBe("b");
  });
});
