// Test fixtures only; the numbers are arbitrary and exist to exercise the UI.
import type { AtlasResponse, ChatResponse, OverviewResponse, RegionsResponse, SnapshotResponse, StoryResponse } from "@/lib/types";
import { provenance } from "./fixtures";

export const regionsFixture: RegionsResponse = {
  provenance,
  dataset_id: "synthetic-demo",
  default_variable: "Index A",
  regions: [
    {
      region: "Alpha",
      variables: ["Index A"],
      start: "2020-01-01",
      end: "2021-12-01",
      geo: { kind: "approximate_extent", bbox: [68, 6, 97, 37], center: [82, 21], note: "Approximate display extent." },
    },
    {
      region: "Beta",
      variables: ["Index A"],
      start: "2020-01-01",
      end: "2021-12-01",
      geo: { kind: "none", bbox: null, center: null, note: "No coordinates." },
    },
  ],
};

export function makeStory(overrides: Partial<StoryResponse> = {}): StoryResponse {
  const months = ["2021-01-01", "2021-02-01", "2021-03-01"].map((date, i) => ({
    date,
    value: 1 + i,
    climatology: 1.5,
    anomaly: i - 0.5,
    anomaly_z: i - 0.5,
    unusual: i === 2,
  }));
  return {
    provenance,
    dataset_id: "synthetic-demo",
    region: "Alpha",
    variable: "Index A",
    unit: "index units",
    period: { start: "2021-01-01", end: "2021-03-01", label: "Jan–Mar 2021", n_months_expected: 3, n_valid: 3, n_missing: 0 },
    geo: regionsFixture.regions[0].geo,
    stats: null,
    months,
    sentences: [
      { kind: "observation", text: "Across Jan–Mar 2021 Index A in Alpha averaged 2 index units.", evidence: "mean of 3 monthly values = 2" },
      { kind: "limitation", text: "This dataset cannot explain why the change happened.", evidence: "no other usable variables" },
    ],
    why: { cause_established: false, statement: "This dataset cannot explain why the change happened.", co_varying: [] },
    banner: "SYNTHETIC DEMO DATA — NOT REAL OBSERVATIONS",
    caveats: [],
    ...overrides,
  };
}

export const chatFixture = (story: StoryResponse): ChatResponse => ({
  reply: "Here is what the data shows for Alpha. I have opened it on the 3D map.",
  understood: { place: "Alpha", period: "Jan 2021 – Mar 2021" },
  action: { type: "show_story", region: story.region, regions: [], variable: "Index A", start: "2021-01-01", end: "2021-03-01" },
  story,
  suggestions: ["Compare Alpha and Beta from 2020 to 2021"],
});

// Whole-record fixtures: three years, one of them with only 6 valid months. Numbers are arbitrary.
export function makeOverview(overrides: Partial<OverviewResponse> = {}): OverviewResponse {
  const years = [2019, 2020, 2021];
  const z = [0.8, -1.2, 0.1];
  const values = years.map((_, yi) => Array.from({ length: 12 }, (_, m) => (yi === 1 && m >= 6 ? null : 10 + m + yi)));
  return {
    provenance,
    dataset_id: "synthetic-demo",
    region: "Alpha",
    variable: "Index A",
    unit: "mm/month",
    banner: null,
    first_year: 2019,
    last_year: 2021,
    years: years.map((year, i) => ({
      year,
      n_months: i === 1 ? 6 : 12,
      mean_value: i === 1 ? null : 15 + i,
      mean_anomaly: i === 1 ? null : z[i] * 10,
      mean_z: i === 1 ? null : z[i],
    })),
    matrix_values: values,
    matrix_z: values.map((row, yi) => row.map((v) => (v === null ? null : z[yi]))),
    climatology: Array.from({ length: 12 }, (_, m) => ({ month: m + 1, mean: 11 + m, std: 1.5, n: 3 })),
    decades: [{ decade: 2010, mean_anomaly: 4, n_years: 5 }],
    wettest_months: [{ date: "2019-07-01", value: 20, anomaly: 8, z: 2.2 }],
    driest_months: [{ date: "2021-02-01", value: 2, anomaly: -9, z: -2.4 }],
    wettest_years: [{ year: 2019, mean_anomaly: 8, mean_z: 0.8 }],
    driest_years: [{ year: 2021, mean_anomaly: -1, mean_z: -0.9 }],
    trend: { slope_per_decade: -2.5, p_value: 0.04, n_years: 25, note: "Descriptive." },
    sentences: [{ kind: "observation", text: "The record for Alpha runs from 2019 to 2021.", evidence: "n=30" }],
    caveats: ["1 of 3 years have fewer than 12 valid months."],
    ...overrides,
  };
}

export const atlasFixture: AtlasResponse = {
  provenance,
  dataset_id: "synthetic-demo",
  variable: "Index A",
  unit: "mm/month",
  banner: null,
  years: [2019, 2020, 2021],
  regions: [
    { region: "Alpha", mean_value: 15, trend_z_per_decade: -0.2, z: [0.8, null, 0.1] },
    { region: "Beta", mean_value: 9, trend_z_per_decade: 0.4, z: [-0.3, 0.2, 0.9] },
  ],
  note: "Each cell is a yearly mean standardised anomaly.",
};

export const snapshotFixture: SnapshotResponse = {
  provenance,
  dataset_id: "synthetic-demo",
  variable: "Index A",
  unit: "mm/month",
  banner: null,
  year: 2021,
  month: 0,
  label: "2021",
  points: [
    { region: "Alpha", lon: 77, lat: 12, value: 15, usual: 14, anomaly: 1, z: 0.1 },
    { region: "Beta", lon: 85, lat: 22, value: 9, usual: 8, anomaly: 1, z: 0.9 },
  ],
  unlocated: [],
  value_max: 15,
  sentences: [{ kind: "observation", text: "In 2021, 2 of 2 regions were above usual.", evidence: "count of regions with z>0 = 2 of 2" }],
  note: "Positions are approximate.",
};
