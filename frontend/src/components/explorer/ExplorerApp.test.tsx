import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";
import { ExplorerApp } from "./ExplorerApp";
import { mockFetch, requestBodies } from "@/test/mockApi";
import { renderView } from "@/test/render";
import type { ChangeSummary, DatasetInfo, SessionResponse } from "@/lib/explorer/types";

// WebGL is not available in jsdom: the globe is replaced by a stub that reports its flights as finished.
vi.mock("next/dynamic", () => ({
  default: () =>
    function FakeGlobe(p: { focus: { token: number } | null; primary: { key: string } | null; onFlightEnd: (t: number) => void }) {
      useEffect(() => {
        if (p.focus) p.onFlightEnd(p.focus.token);
      }, [p]);
      return <div data-testid="globe-stub" data-layer={p.primary?.key ?? ""} />;
    },
}));

const BBOX: [number, number, number, number] = [77.6, 12.9, 77.7, 13.0];
const dataset: DatasetInfo = {
  id: "bell", name: "Bellandur Lake (illustrative)", description: "", is_synthetic: true, simulated_label: "Illustrative Dataset: a generated demonstration layer, not satellite imagery.", variables: [{ key: "water", label: "water", class: 2, primary: true }], designation: "illustrative", public_label: "Illustrative Dataset", provenance: {}, source: "Generator", product: "", format: "", crs: "EPSG:4326",
  resolution_m: 30, temporal_resolution: "monthly", bbox: BBOX, coverage: { start: "2000-01-01", end: "2025-12-01" }, observation_count: 3, usable_count: 3, classes: {}, real_dataset_targets: [], issues: [],
};
const loc = { id: "d:1", name: "Bellandur Lake", display_name: "Bellandur Lake, Bengaluru", lat: 12.95, lon: 77.65, kind: "water body", source: "x", bbox: BBOX, zoom_altitude_m: 14000, level: "water body", hierarchy: ["India", "Karnataka"], boundary_status: "approximate_bbox" };
const latest = { label: "Latest available observation", date: "2025-12-01", location: "Bellandur Lake", source: "Generator", spatial_resolution_m: 30, quality: "good" as const, valid_fraction: 0.97, temporal_resolution: "monthly", historical_coverage: dataset.coverage, is_synthetic: true, simulated_label: "Illustrative Dataset: a generated demonstration layer, not satellite imagery.", note: "Not live or real-time." };
const period = { requested: { start_year: 2000, end_year: 2025 }, supported: dataset.coverage, effective: { start_year: 2000, end_year: 2025 }, status: "ok" as const, messages: [] };
const ready: SessionResponse = { status: "ready", message: "ok", location: loc, alternatives: [], examples: [], datasets: [dataset], dataset, period, latest, insufficient: null, nearby_datasets: [], is_synthetic: true, simulated_label: "Illustrative Dataset: a generated demonstration layer, not satellite imagery." };

const hotspot = { id: "h1", rank: 1, kind: "loss" as const, area_ha: 33.4, geometry_area_ha: 33.1, share_of_change_pct: 60, centroid: { lon: 77.67, lat: 12.93 }, bbox: [77.66, 12.92, 77.68, 12.94] as [number, number, number, number], region: "south-eastern", description: "south-eastern shore: 33.4 ha of water lost" };
const changed = {
  outcome: "change_detected", headline: "Change detected: 55.3 ha lost.", analysis_id: "aid", dataset, location_name: "Bellandur Lake", period,
  first_observation: { date: "2000-01-01", quality: "good", valid_fraction: 1, layer_url: "" }, last_observation: { date: "2025-12-01", quality: "good", valid_fraction: 1, layer_url: "" },
  observations_used: {}, areas: { analysed_ha: 900, net_ha: -44.6, pct_net_change: -11.8, lost_ha: 55.3, gained_ha: 10.7 }, most_affected: { region: "south-eastern", kind: "loss", area_ha: 33.4, description: "south-eastern shore: 33.4 ha of water lost", hotspot_id: "h1", centroid: hotspot.centroid },
  hotspots: [hotspot], progression: [{ year: 2000, water_ha: 380, cumulative_loss_ha: 0, cumulative_gain_ha: 0, observations: 8 }, { year: 2025, water_ha: 335, cumulative_loss_ha: 55, cumulative_gain_ha: 10, observations: 8 }],
  trend: { direction: "decreasing", slope_ha_per_year: -2.4, p_value: 0, method: "x", years: 2 }, quality: { mean_valid_fraction: 0.95 }, confidence: "high", confidence_reasons: ["ok"], limitations: ["Illustrative Dataset: generated demonstration layer."], variable: { key: "water", label: "water", class: 2, primary: true }, what_was_analysed: "same-season composites",
  insufficient: null, thresholds: {}, bbox: BBOX, layers: { difference_png: "/api/explorer/analysis/aid/layers/difference.png" }, is_synthetic: true, simulated_label: "Illustrative Dataset: a generated demonstration layer, not satellite imagery.",
} as unknown as ChangeSummary;
const observations = ["2000-01-01", "2010-06-01", "2025-12-01"].map((date) => ({ date, quality: "good" as const, valid_fraction: 0.95, usable: true, water_share: 0.4, sensor: null }));

const routes = (session: SessionResponse, summary: ChangeSummary | null) => ({
  "GET /api/explorer/datasets": () => ({ body: [dataset] }),
  "POST /api/explorer/session": () => ({ body: session }),
  "POST /api/explorer/analysis/detect-change": () => ({ body: summary }),
  "GET /api/explorer/datasets/bell/observations": () => ({ body: observations }),
  "GET /api/explorer/analysis/aid/hotspots": () => ({ body: { type: "FeatureCollection", features: [] } }),
  "POST /api/explorer/analysis/aid/explain": () => ({ body: { text: "Illustrative Dataset. 55.3 ha were lost.", source: "deterministic", model: null, notice: "No AI key is configured.", tools_used: [] } }),
  "POST /api/explorer/ai/chat": () => ({ body: { answer: "Hotspots: south-eastern shore.", source: "deterministic", model: null, notice: null, tools_used: [] } }),
});

async function search(text: string) {
  const user = userEvent.setup();
  await user.type(screen.getByRole("combobox", { name: /place name/i }), text);
  await user.click(screen.getByRole("button", { name: "Explore" }));
  return user;
}

describe("Earth Time Machine", () => {
  it("shows examples, instructions and which datasets exist before any search", async () => {
    mockFetch(routes(ready, changed));
    renderView(<ExplorerApp />);
    expect(screen.getByRole("button", { name: "Hyderabad" })).toBeInTheDocument();
    expect(screen.getByText(/drag to turn the globe/i)).toBeInTheDocument();
    expect(await screen.findByTestId("availability")).toHaveTextContent("Bellandur Lake 2000–2025 (Illustrative Dataset)");
  });

  it("outcome A: shows the change, the latest observation, hotspots, timeline and an honest explanation", async () => {
    const fetchMock = mockFetch(routes(ready, changed));
    renderView(<ExplorerApp />);
    await search("Bellandur Lake");
    expect(await screen.findByTestId("banner-change_detected")).toHaveTextContent("Change detected");
    expect(requestBodies(fetchMock, "/api/explorer/analysis/detect-change")[0]).toMatchObject({ dataset_id: "bell", start_year: 2000, end_year: 2025 });
    const latestCard = screen.getByTestId("latest-card");
    expect(latestCard).toHaveTextContent("Latest available observation");
    expect(latestCard).toHaveTextContent("Not live or real-time");
    expect(screen.getAllByText(/Illustrative Dataset/i).length).toBeGreaterThan(0);
    expect(screen.getByTestId("globe-stub")).toHaveAttribute("data-layer", expect.stringContaining("diff:aid"));
    expect(within(screen.getByTestId("summary-stats")).getByText("55.3 ha")).toBeInTheDocument();
    expect(screen.getByTestId("most-affected")).toHaveTextContent("south-eastern");
    expect(await screen.findByTestId("explanation-source")).toHaveTextContent("Generated from the measurements");
    expect(screen.getAllByTestId("tick")).toHaveLength(3);
    expect(screen.getByTestId("hotspot-nav")).toHaveTextContent("1 hotspot");
  });

  it("scrubbing the timeline switches to the historical observation on the map", async () => {
    mockFetch(routes(ready, changed));
    renderView(<ExplorerApp />);
    await search("Bellandur Lake");
    await screen.findByTestId("timeline");
    fireEvent.keyDown(screen.getByTestId("timeline-track"), { key: "Home" });
    expect(screen.getByTestId("globe-stub")).toHaveAttribute("data-layer", "obs:2000-01-01");
    expect(screen.getByTestId("timeline-readout")).toHaveTextContent("Jan 2000");
    expect(screen.getByTestId("map-caption")).toHaveTextContent("Historical observation");
    await userEvent.setup().click(screen.getByRole("button", { name: "Next observation" }));
    expect(screen.getByTestId("globe-stub")).toHaveAttribute("data-layer", "obs:2010-06-01");
  });

  it("outcome B explains what was analysed and offers to explore anyway", async () => {
    const calm = { ...changed, outcome: "no_clear_change", headline: "No clear change in water extent.", hotspots: [], most_affected: null } as ChangeSummary;
    mockFetch(routes(ready, calm));
    renderView(<ExplorerApp />);
    const user = await search("Bellandur Lake");
    const banner = await screen.findByTestId("banner-no_clear_change");
    expect(banner).toHaveTextContent("same-season composites");
    await user.click(within(banner).getByRole("button", { name: /explore the observations anyway/i }));
    expect(screen.getByTestId("globe-stub")).toHaveAttribute("data-layer", expect.stringContaining("diff:aid"));
  });

  it("outcome C says what is missing, never claims 'no change', and suggests a supported period", async () => {
    const sparse = {
      ...changed, outcome: "insufficient_data", headline: "Insufficient data to assess change for this period.", analysis_id: null, hotspots: [], most_affected: null, progression: [],
      insufficient: { code: "no_usable_observations", reason: "There is no usable observation in 2014.", missing: ["usable observations in 2014 (only 38% valid)"], available_dates: ["2016", "2019"], suggested_period: { start_year: 2016, end_year: 2019 } },
    } as unknown as ChangeSummary;
    mockFetch(routes(ready, sparse));
    renderView(<ExplorerApp />);
    await search("Chilika");
    const banner = await screen.findByTestId("banner-insufficient_data");
    expect(banner).toHaveTextContent("only 38% valid");
    expect(banner).toHaveTextContent("not a finding of “no change”");
    expect(banner).toHaveTextContent("2016, 2019");
    expect(within(banner).getByRole("button", { name: /2016–2019/ })).toBeInTheDocument();
    expect(screen.queryByText("No clear change")).not.toBeInTheDocument();
  });

  it("an unknown place gives guidance and examples instead of an error", async () => {
    mockFetch(routes({ ...ready, status: "not_found", message: 'No place called "zzz" could be found.', location: null, dataset: null, datasets: [], latest: null, period: null, examples: ["Mumbai"] }, null));
    renderView(<ExplorerApp />);
    await search("zzz");
    expect(await screen.findByTestId("banner-not-found")).toHaveTextContent("No place called");
    expect(screen.queryByTestId("timeline")).not.toBeInTheDocument();
  });

  it("a place with no dataset is shown on the globe but never analysed", async () => {
    const none = { ...ready, status: "no_dataset", dataset: null, datasets: [], latest: null, period: null, insufficient: { code: "no_dataset", reason: "No loaded dataset covers Mumbai.", missing: ["a dataset whose footprint contains this location"], available_dates: [], suggested_period: null }, message: "Found Mumbai, but no dataset covers it." } as SessionResponse;
    const fetchMock = mockFetch(routes(none, null));
    renderView(<ExplorerApp />);
    await search("Mumbai");
    expect(await screen.findByTestId("banner-insufficient_data")).toHaveTextContent("No loaded dataset covers Mumbai");
    expect(requestBodies(fetchMock, "/api/explorer/analysis/detect-change")).toHaveLength(0);
    expect(screen.queryByTestId("timeline")).not.toBeInTheDocument();
  });

  it("rejects a start year that is not before the end year", async () => {
    mockFetch(routes(ready, changed));
    renderView(<ExplorerApp />);
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2020" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2010" } });
    expect(screen.getByRole("alert")).toHaveTextContent("start year must be earlier");
    expect(screen.getByRole("button", { name: "Explore" })).toBeDisabled();
  });

  it("shows a clear, retryable error when the API is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    renderView(<ExplorerApp />);
    await search("Bellandur");
    expect(await screen.findByTestId("error-banner")).toHaveTextContent(/Cannot reach the NASAX API/);
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
  it("Back and Forward return to earlier places without a page reload", async () => {
    const fetchMock = mockFetch(routes(ready, changed));
    renderView(<ExplorerApp />);
    const user = await search("Bellandur Lake");
    await screen.findByTestId("banner-change_detected");
    const back = screen.getByRole("button", { name: /back to the previous location/i });
    const fwd = screen.getByRole("button", { name: /forward to the next location/i });
    expect(back).toBeDisabled();
    const box = screen.getByRole("combobox", { name: /place name/i });
    await user.clear(box);
    await user.type(box, "Hyderabad");
    await user.click(screen.getByRole("button", { name: "Explore" }));
    await screen.findByTestId("banner-change_detected");
    expect(back).toBeEnabled();
    await user.click(back);
    await screen.findByTestId("banner-change_detected");
    expect(requestBodies(fetchMock, "/api/explorer/session").at(-1)).toMatchObject({ location_id: "d:1" });
    expect(fwd).toBeEnabled();
    expect(back).toBeDisabled();
  });

  it("a typed command works like a spoken one", async () => {
    mockFetch(routes(ready, changed));
    renderView(<ExplorerApp />);
    const user = await search("Bellandur Lake");
    await screen.findByTestId("banner-change_detected");
    const box = screen.getByRole("combobox", { name: /place name/i });
    await user.clear(box);
    await user.type(box, "show the latest observation");
    await user.click(screen.getByRole("button", { name: "Explore" }));
    expect(await screen.findByTestId("voice-note")).toHaveTextContent("latest available observation");
  });
});
