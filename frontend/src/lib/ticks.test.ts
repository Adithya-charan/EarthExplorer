import { describe, expect, it } from "vitest";
import { toEpoch, yearLabel, yearTicks } from "./ticks";

const y = (year: number) => Date.UTC(year, 0, 1);

describe("toEpoch", () => {
  it("reads plain dates and zone-less date-times as UTC, independent of the machine's time zone", () => {
    expect(toEpoch("2020-01-01")).toBe(Date.UTC(2020, 0, 1));
    expect(toEpoch("2020-01-01T00:00:00")).toBe(Date.UTC(2020, 0, 1));
    expect(toEpoch("2020-06-15T12:30:00")).toBe(Date.UTC(2020, 5, 15, 12, 30));
  });

  it("respects an explicit zone when the API provides one", () => {
    expect(toEpoch("2020-01-01T00:00:00Z")).toBe(Date.UTC(2020, 0, 1));
    expect(toEpoch("2020-01-01T02:00:00+02:00")).toBe(Date.UTC(2020, 0, 1));
  });
});

describe("yearTicks", () => {
  it("places evenly spaced ticks on whole years", () => {
    const ticks = yearTicks(y(2000), y(2023));
    const years = ticks.map((t) => Number(yearLabel(t)));
    expect(years).toEqual([2000, 2005, 2010, 2015, 2020]);
    expect(ticks.every((t) => t >= y(2000) && t <= y(2023))).toBe(true);
  });

  it("uses a yearly step for short records", () => {
    expect(yearTicks(y(2020), y(2024)).map((t) => Number(yearLabel(t)))).toEqual([2020, 2021, 2022, 2023, 2024]);
  });

  it("never returns ticks outside the data range", () => {
    const min = Date.UTC(2000, 5, 15);
    const max = Date.UTC(2010, 5, 15);
    const ticks = yearTicks(min, max);
    expect(ticks.length).toBeGreaterThan(1);
    expect(ticks.every((t) => t >= min && t <= max)).toBe(true);
  });

  it("falls back to automatic ticks when the span is too short or invalid", () => {
    expect(yearTicks(Date.UTC(2020, 1, 1), Date.UTC(2020, 8, 1))).toEqual([]);
    expect(yearTicks(NaN, NaN)).toEqual([]);
    expect(yearTicks(y(2020), y(2020))).toEqual([]);
  });
});
