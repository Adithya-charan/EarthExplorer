import { describe, expect, it } from "vitest";
import { LABELLED_AGES, MODE_LABELS, fmtLatLon, formatAge, formatMa, nearestAge, periodColor, stepAge, type DeepManifest, type DeepLayer } from "./deeptime";
import { cleanRing } from "@/components/explorer/deepGlobe";
import { defaultVisible, vectorSpecs } from "@/components/explorer/useDeepTime";

const AGES = [0, 0.001, 0.01, 0.1, 1, 5, 10, 20, 30, 40, 50, 55, 66, 75, 90, 100, 120, 140, 150, 180, 200, 230, 250];

describe("age formatting", () => {
  it("writes ages the way a reader says them", () => {
    expect(formatAge(0)).toBe("Present day");
    expect(formatAge(66)).toBe("66 million years ago");
    expect(formatAge(0.01)).toBe("10,000 years ago");
    expect(formatAge(0.001)).toBe("1,000 years ago");
    expect(formatMa(0)).toBe("0 Ma");
    expect(formatMa(0.01)).toBe("10 ka");
    expect(formatMa(66)).toBe("66 Ma");
  });
  it("formats positions with hemispheres and never invents a missing one", () => {
    expect(fmtLatLon([-35.5, 53.1])).toBe("35.5°S, 53.1°E");
    expect(fmtLatLon([12, -70])).toBe("12.0°N, 70.0°W");
    expect(fmtLatLon(null)).toBe("not available");
  });
});

describe("stepping through geological time", () => {
  it("finds the nearest supported age and never wraps", () => {
    expect(nearestAge(AGES, 64)).toBe(66);
    expect(stepAge(AGES, 66, -1)).toBe(55);
    expect(stepAge(AGES, 66, 1)).toBe(75);
    expect(stepAge(AGES, 0, -1)).toBe(0);
    expect(stepAge(AGES, 250, 1)).toBe(250);
  });
  it("keeps every requested age selectable and labels the key ones", () => {
    for (const a of LABELLED_AGES) expect(AGES).toContain(a);
  });
});

describe("neutral labelling", () => {
  it("uses the required era names and does not call reconstructions satellite data", () => {
    expect(MODE_LABELS).toEqual({ today: "Earth Today", historical: "Historical Earth", deep: "Deep-Time Earth" });
  });
  it("takes the period colour from the ICS-derived time scale", () => {
    const m = { timescale: { periods: [{ name: "Cretaceous", t_age: 66, b_age: 145, color: "#7fc64e" }, { name: "Quaternary", t_age: 0, b_age: 2.58, color: "#f9f97f" }], epochs: [], eras: [] } } as unknown as DeepManifest;
    expect(periodColor(m, 100)).toBe("#7fc64e");
    expect(periodColor(m, 1)).toBe("#f9f97f");
    expect(periodColor(null, 1)).toBe("#4b5563");
  });
});

describe("cleanRing", () => {
  it("drops the closing point and consecutive duplicates (a zero-length edge breaks Cesium)", () => {
    expect(cleanRing([[0, 0], [1, 0], [1, 0], [1, 1], [0, 0]])).toEqual([0, 0, 1, 0, 1, 1]);
  });
  it("rejects degenerate rings and non-finite coordinates", () => {
    expect(cleanRing([[0, 0], [1, 1], [0, 0]])).toBeNull();
    expect(cleanRing([[0, 0], [NaN, 1], [1, 1], [2, 2]])).toEqual([0, 0, 1, 1, 2, 2]);
  });
  it("keeps latitudes off the poles", () => {
    const r = cleanRing([[0, 90], [10, 90], [10, 80]]);
    expect(r?.[1]).toBeLessThan(90);
  });
});

describe("vector layer specs", () => {
  const layers: DeepLayer[] = ["coastlines", "plates", "continents", "landmass", "shallow_marine", "india_outline_earthbyte"].map((name) => ({ name, label: name, kind: "model reconstruction", url: `/x/${name}` }));
  it("shows present-day continent and coastline shapes only where no paleogeography exists", () => {
    expect(defaultVisible("continents", true)).toBe(false);
    expect(defaultVisible("coastlines", true)).toBe(false);
    expect(defaultVisible("continents", false)).toBe(true);
    expect(defaultVisible("landmass", true)).toBe(true);
  });
  it("splits the Indian plate out from the other plates and draws land above sea", () => {
    const specs = vectorSpecs(layers, "66|earthbyte", {}, true);
    const keys = specs.map((s) => s.key);
    expect(keys).toContain("66|earthbyte:plates:india");
    expect(keys.indexOf("66|earthbyte:shallow_marine")).toBeLessThan(keys.indexOf("66|earthbyte:landmass"));
    expect(keys).not.toContain("66|earthbyte:continents");
    const india = specs.find((s) => s.key.endsWith(":india"))!;
    expect(india.filter?.({ is_indian_plate: true })).toBe(true);
    expect(india.filter?.({ is_indian_plate: false })).toBe(false);
  });
  it("honours the layer toggles", () => {
    const specs = vectorSpecs(layers, "k", { landmass: false, continents: true }, true);
    const keys = specs.map((s) => s.key);
    expect(keys).not.toContain("k:landmass");
    expect(keys).toContain("k:continents");
  });
});
