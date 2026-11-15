import { describe, expect, it } from "vitest";
import { csvLine, metadataCsv, observationsCsv, seriesCsv } from "./export";
import type { DatasetStats } from "./analytics";
import type { DatasetInfo } from "./types";

const stats = { dataset_id: "d", name: "D", designation: "official_derived", public_label: null, method: "Pixel counts", observations: [{ date: "2000-01-01", quality: "good", valid_fraction: 1, footprint_ha: 100, valid_ha: 100, nodata_pct: 0, class_area_ha: { Water: 10.1234, "Land, dry": 89.8766 } }], variables: { water: { label: "Water", classes: 1, primary: true, series: [{ date: "2000-01-01", area_ha: 10.1234, share_of_valid_pct: 10.1 }] } } } as DatasetStats;
const info = { id: "d", name: "D", description: 'Has "quotes", commas', source: "JRC", product: "P", format: "GeoTIFF", crs: "EPSG:4326", resolution_m: 30, temporal_resolution: "yearly", bbox: [77, 12, 78, 13], coverage: { start: "2000-01-01", end: "2020-01-01" }, observation_count: 2, usable_count: 2, classes: { "1": "Water" }, issues: [], public_label: "Satellite Observations" } as unknown as DatasetInfo;

describe("export", () => {
  it("quotes fields safely", () => {
    expect(csvLine(["a", 'b"c', "d,e", null, 1])).toBe('a,"b""c","d,e",,1');
  });
  it("writes one row per observation and class", () => {
    const rows = observationsCsv(stats).trim().split("\r\n");
    expect(rows).toHaveLength(3);
    expect(rows[1]).toBe("d,2000-01-01,Water,10.123,1,0,good,100");
    expect(rows[2]).toContain('"Land, dry"');
  });
  it("writes the series and the metadata record", () => {
    expect(seriesCsv(stats).trim().split("\r\n")[1]).toBe("d,water,2000-01-01,10.123,10.1");
    const m = metadataCsv(info, stats);
    expect(m).toContain("Data designation,Satellite Observations");
    expect(m).toContain('"Has ""quotes"", commas"');
    expect(m).toContain("Centre (lat, lon)");
  });
});
