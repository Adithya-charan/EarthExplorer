import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StoryView } from "./StoryView";
import { TrendView } from "./TrendView";
import { DatasetSelector } from "@/components/data/DatasetSelector";
import { primaryStatusHelp } from "@/lib/format";
import { datasetList, demoSummary, makeAnalysis, metadata, provenance } from "@/test/fixtures";
import { atlasFixture, makeOverview, makeStory, regionsFixture, snapshotFixture } from "@/test/storyFixtures";
import { mockFetch } from "@/test/mockApi";
import { renderInShell, renderView } from "@/test/render";
import type { DatasetInfo, DatasetSummary, DiagnosticsResponse, MetadataResponse, Provenance } from "@/lib/types";

vi.mock("@/components/story/PlacesMap", () => ({ PlacesMap: () => <div data-testid="places-map-stub" /> }));
vi.mock("@/components/story/StoryMap", () => ({ StoryMap: () => <div data-testid="story-map-stub" /> }));

const BANNER = "SYNTHETIC DEMO — NOT NASA OBSERVATIONS";

const observedInfo: DatasetInfo = {
  data_class: "observed_global",
  label: "Observed global data",
  data_source: "NASA GES DISC GPM IMERG V07 via Giovanni",
  spatial_scope: "Global area average. Not regional.",
  temporal_coverage: "1998-01 to 2025-09, monthly, 333 months",
  unit: "mm/hr",
  unit_note: "Not written inside the Giovanni CSV.",
  limitations: ["No regional conclusion can be drawn."],
  source_files: ["GPM_IMERG_V07_Global_Monthly_Precipitation_1998-2025.csv"],
  regional_analysis_allowed: false,
  checks: [],
};
const demoInfo: DatasetInfo = {
  ...observedInfo,
  data_class: "synthetic_regional_demo",
  label: BANNER,
  data_source: BANNER,
  spatial_scope: "Named demo regions (Amazon, Central Africa, India); synthetic labels.",
  limitations: ["Synthetic: artificial values."],
  regional_analysis_allowed: true,
};

const observed: DatasetSummary = {
  ...demoSummary,
  id: "gpm-imerg-global-observed",
  name: "Observed global data — GPM IMERG V07",
  status: "observed_global",
  is_synthetic: false,
  n_regions: 1,
  notice: "Observed global data: global area-averaged series, not regional.",
  info: observedInfo,
};
const regionalDemo: DatasetSummary = {
  ...demoSummary,
  id: "gpm-imerg-regional-synthetic-demo",
  name: "Synthetic regional demo data",
  status: "synthetic_regional_demo",
  notice: `${BANNER}. Regional-shaped series made for software testing.`,
  info: demoInfo,
};

const list = (datasets: DatasetSummary[], default_dataset_id: string) => ({
  ...datasetList,
  datasets,
  default_dataset_id,
  package_issues: [],
});

const observedProv: Provenance = { ...provenance, dataset_id: observed.id, dataset_name: observed.name, status: "observed_global", is_synthetic: false, synthetic_row_fraction: 0, notice: observed.notice };
const demoProv: Provenance = { ...provenance, dataset_id: regionalDemo.id, status: "synthetic_regional_demo", notice: regionalDemo.notice };

const metaFor = (ds: DatasetSummary, prov: Provenance): MetadataResponse => ({ ...metadata, provenance: prov, dataset: ds });

const diagnostics: DiagnosticsResponse = {
  provenance: observedProv,
  variable: "Index A",
  region: "Alpha",
  unit: "mm/hr",
  missingness: {
    first_month: "1998-01-01",
    last_month: "2025-09-01",
    expected_months: 333,
    present_rows: 333,
    valid_values: 333,
    missing_values: 0,
    absent_months: [],
    longest_gap_months: 0,
    coverage_fraction: 1,
    note: "Absent or missing months are reported as they are.",
  },
  month_of_year: Array.from({ length: 12 }, (_, i) => ({ month: i + 1, n: 28, mean: 0.11, median: 0.11, std: 0.005, minimum: 0.1, maximum: 0.12 })),
  autocorrelation: { evaluated: true, reason_not_evaluated: null, n: 333, contiguous_months: true, detrended: { evaluated: true, reason_not_evaluated: null, residual_basis: "OLS-detrended residuals", lag1: 0.39, durbin_watson: 1.2, ljung_box_lags: 10, ljung_box_p: 0.001, flagged: true, effective_n_ar1: 148.6, approximate: false, correction_applied: false, correction_method: null, note: null }, detrended_and_deseasonalized: null, note: "Strong positive lag-1 autocorrelation means consecutive months are not independent." },
  random_error: {
    available: true,
    reason_unavailable: null,
    dates_aligned: true,
    n_aligned: 333,
    mean_random_error: 0.0275,
    mean_precipitation: 0.115,
    mean_error_to_value_ratio: 0.2387,
    unit: "mm/hr",
    usable_as_confidence_interval: false,
    note: "It is not a confidence interval and is not used as a statistical weight.",
  },
  assumptions: ["Everything here is computed from the rows of the selected series."],
};

describe("observed global vs synthetic regional demo", () => {
  it("lists the two data classes in separate selector groups", async () => {
    mockFetch({
      "GET /api/datasets": () => ({ body: list([demoSummary, observed, regionalDemo], observed.id) }),
      "GET /api/regions": () => ({ body: regionsFixture }),
      "GET /api/overview": () => ({ body: makeOverview({ provenance: observedProv, banner: null }) }),
      "GET /api/atlas": () => ({ body: atlasFixture }),
      "GET /api/snapshot": () => ({ body: snapshotFixture }),
      "GET /api/geography/boundaries": () => ({ body: { type: "FeatureCollection", features: [], source: { note: "" } } }),
      "POST /api/story": () => ({ body: makeStory({ provenance: observedProv, banner: null }) }),
      "GET /api/metadata": () => ({ body: metaFor(observed, observedProv) }),
    });
    renderView(<DatasetSelector />);
    const select = await screen.findByRole("combobox");
    const groups = Array.from(select.querySelectorAll("optgroup")).map((g) => g.label);
    expect(groups).toEqual([
      "Observed global data",
      "Synthetic regional demo data — NOT NASA OBSERVATIONS",
      "Bundled synthetic demo data",
    ]);
    const observedGroup = select.querySelector('optgroup[label="Observed global data"]')!;
    expect(within(observedGroup as HTMLElement).getAllByRole("option")).toHaveLength(1);
    expect(select).toHaveValue(observed.id); // observed data is the default, never the synthetic set
  });

  it("shows source, scope, coverage, unit, class and limitations for observed global data", async () => {
    mockFetch({
      "GET /api/datasets": () => ({ body: list([observed], observed.id) }),
      "GET /api/regions": () => ({ body: regionsFixture }),
      "GET /api/overview": () => ({ body: makeOverview({ provenance: observedProv, banner: null }) }),
      "GET /api/atlas": () => ({ body: atlasFixture }),
      "GET /api/snapshot": () => ({ body: snapshotFixture }),
      "GET /api/geography/boundaries": () => ({ body: { type: "FeatureCollection", features: [], source: { note: "" } } }),
      "POST /api/story": () => ({ body: makeStory({ provenance: observedProv, banner: null }) }),
      "GET /api/metadata": () => ({ body: metaFor(observed, observedProv) }),
    });
    renderView(<StoryView />);
    const card = await screen.findByTestId("dataset-info");
    expect(card).toHaveAttribute("data-data-class", "observed_global");
    for (const text of [/Global area average\. Not regional/, /1998-01 to 2025-09/, /mm\/hr/, /GES DISC GPM IMERG V07/, /Observed \(NASA GPM IMERG V07, global average\)/]) {
      expect(within(card).getAllByText(text).length).toBeGreaterThan(0);
    }
    for (const banner of await screen.findAllByTestId("observed-global-banner")) expect(banner).toHaveTextContent(/global area-averaged/);
    expect(screen.queryByTestId("synthetic-banner")).not.toBeInTheDocument();
  });

  it("keeps the synthetic label visible on the page, the header and the info card", async () => {
    mockFetch({
      "GET /api/datasets": () => ({ body: list([regionalDemo], regionalDemo.id) }),
      "GET /api/regions": () => ({ body: regionsFixture }),
      "GET /api/overview": () => ({ body: makeOverview({ provenance: demoProv, banner: BANNER }) }),
      "GET /api/atlas": () => ({ body: atlasFixture }),
      "GET /api/snapshot": () => ({ body: snapshotFixture }),
      "GET /api/geography/boundaries": () => ({ body: { type: "FeatureCollection", features: [], source: { note: "" } } }),
      "POST /api/story": () => ({ body: makeStory({ provenance: demoProv, banner: "SYNTHETIC DEMO — NOT NASA OBSERVATIONS" }) }),
      "GET /api/metadata": () => ({ body: metaFor(regionalDemo, demoProv) }),
    });
    renderInShell(<StoryView />);
    await screen.findByTestId("dataset-info");
    expect(screen.getByTestId("synthetic-strip")).toHaveTextContent(BANNER);
    for (const banner of await screen.findAllByTestId("synthetic-banner")) expect(banner).toHaveTextContent(BANNER);
    expect(within(screen.getByTestId("dataset-info")).getAllByText(BANNER).length).toBeGreaterThan(0);
    expect(screen.getByTestId("dataset-status")).toHaveTextContent(BANNER);
  });

  it("states on the overview that real regional analysis is disabled and surfaces package problems", async () => {
    mockFetch({
      "GET /api/datasets": () => ({
        body: { ...list([regionalDemo], regionalDemo.id), package_issues: [{ code: "observed_unavailable", severity: "error", message: "The observed global precipitation series could not be loaded; nothing was substituted." }] },
      }),
      "GET /api/regions": () => ({ body: regionsFixture }),
      "GET /api/overview": () => ({ body: makeOverview({ provenance: demoProv, banner: BANNER }) }),
      "GET /api/atlas": () => ({ body: atlasFixture }),
      "GET /api/snapshot": () => ({ body: snapshotFixture }),
      "GET /api/geography/boundaries": () => ({ body: { type: "FeatureCollection", features: [], source: { note: "" } } }),
      "POST /api/story": () => ({ body: makeStory({ provenance: demoProv, banner: "SYNTHETIC DEMO — NOT NASA OBSERVATIONS" }) }),
      "GET /api/metadata": () => ({ body: metaFor(regionalDemo, demoProv) }),
    });
    renderView(<StoryView />);
    expect(await screen.findByTestId("regional-disabled")).toHaveTextContent(/No regional NASA observations have been supplied/);
    expect(screen.getByTestId("package-issues")).toHaveTextContent(/nothing was substituted/);
  });

  it("shows runtime diagnostics with the random-error caveat on the trend page", async () => {
    mockFetch({
      "GET /api/datasets": () => ({ body: list([observed], observed.id) }),
      "GET /api/regions": () => ({ body: regionsFixture }),
      "GET /api/overview": () => ({ body: makeOverview({ provenance: observedProv, banner: null }) }),
      "GET /api/atlas": () => ({ body: atlasFixture }),
      "GET /api/snapshot": () => ({ body: snapshotFixture }),
      "GET /api/geography/boundaries": () => ({ body: { type: "FeatureCollection", features: [], source: { note: "" } } }),
      "POST /api/story": () => ({ body: makeStory({ provenance: observedProv, banner: null }) }),
      "GET /api/metadata": () => ({ body: metaFor(observed, observedProv) }),
      "POST /api/analyze": () => ({ body: makeAnalysis("Alpha", { provenance: observedProv }) }),
      "GET /api/diagnostics": () => ({ body: diagnostics }),
    });
    renderView(<TrendView />);
    const panel = await screen.findByTestId("diagnostics", undefined, { timeout: 8000 });
    expect(within(panel).getByTestId("diag-missingness")).toHaveTextContent(/333 valid value\(s\) of 333 expected months/);
    expect(within(panel).getByTestId("diag-moy")).toBeInTheDocument();
    expect(within(panel).getByTestId("diag-autocorr")).toHaveTextContent(/lag-1 0\.39.*effective n ≈ 149/);
    expect(within(panel).getByTestId("diag-random-error")).toHaveTextContent(/match the value series exactly/);
    expect(within(panel).getByText(/not a confidence interval/)).toBeInTheDocument();
    expect(screen.getByTestId("chart-observed-tag")).toHaveTextContent(/Observed global data/);
  });
});

describe("autocorrelation status wording", () => {
  const ac = { evaluated: true, flagged: true as boolean | null, lag1: 0.43, reason_not_evaluated: null };

  it("says autocorrelation was assessed but not corrected on the seasonal path", () => {
    const t = primaryStatusHelp("exploratory_uncorrected", { autocorrelation: ac, primary: { test_name: "Seasonal Mann-Kendall (Hirsch et al. 1982)" } });
    expect(t).toMatch(/was assessed and is significant \(lag-1 0\.43\)/);
    expect(t).toMatch(/Hamed–Rao correction is not available for the seasonal analysis path/);
    expect(t).not.toMatch(/could not be assessed/);
  });

  it("keeps 'could not be assessed' only when diagnostics did not run", () => {
    const t = primaryStatusHelp("exploratory_uncorrected", { autocorrelation: { ...ac, evaluated: false, flagged: null, lag1: null, reason_not_evaluated: "too few values" }, primary: { test_name: "Mann-Kendall" } });
    expect(t).toMatch(/could not be assessed \(too few values\)/);
  });

  it("uses the generic non-seasonal wording otherwise", () => {
    const t = primaryStatusHelp("exploratory_uncorrected", { autocorrelation: ac, primary: { test_name: "Mann-Kendall" } });
    expect(t).toMatch(/no valid correction was available for this series/);
  });
});
