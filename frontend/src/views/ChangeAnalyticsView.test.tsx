import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderView } from "@/test/render";
import { mockFetch } from "@/test/mockApi";
import { ChangeAnalyticsView } from "./ChangeAnalyticsView";
import { DataMethodsView } from "./DataMethodsView";

afterEach(() => vi.unstubAllGlobals());

const row = (id: string, name: string, designation: string, obs: number) => ({
  id, name, designation, public_label: designation === "illustrative" ? "Illustrative Dataset" : "Satellite Observations",
  bbox: [0, 0, 1, 1], coverage: { start: "2000-01-01", end: "2020-01-01" }, observations: obs, temporal_resolution: "irregular", resolution_m: 30, variables: ["water"], source: "test", format: "GeoTIFF",
});
const stats = (id: string, name: string, designation: string, areas: number[]) => ({
  dataset_id: id, name, designation, public_label: null, method: "Test method.",
  observations: areas.map((a, i) => ({ date: `${2000 + i * 10}-01-01`, quality: "good", valid_fraction: 1, footprint_ha: 1000, valid_ha: 1000, nodata_pct: 0, class_area_ha: { Water: a, Land: 1000 - a } })),
  variables: { water: { label: "Water", classes: 2, primary: true, series: areas.map((a, i) => ({ date: `${2000 + i * 10}-01-01`, area_ha: a, share_of_valid_pct: a / 10 })) } },
});

describe("Change Analytics", () => {
  it("compares datasets, marks designations and states a single snapshot honestly", async () => {
    mockFetch({
      "GET /api/explorer/catalogue": () => ({ body: { count: 2, datasets: [row("a", "Lake A", "official_derived", 3), row("b", "Lake B (illustrative)", "illustrative", 1)] } }),
      "GET /api/explorer/datasets/a/statistics": () => ({ body: stats("a", "Lake A", "official_derived", [400, 300, 200]) }),
      "GET /api/explorer/datasets/b/statistics": () => ({ body: stats("b", "Lake B", "illustrative", [100]) }),
    });
    renderView(<ChangeAnalyticsView />);
    expect(await screen.findByTestId("overview")).toBeInTheDocument();
    expect(await screen.findByText("−50.0%")).toBeInTheDocument();
    expect(screen.getAllByText("snapshot").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ILLUSTRATIVE DATASET").length).toBeGreaterThan(0);
    expect(await screen.findByTestId("kpis")).toHaveTextContent("−200.0 ha");
    expect(screen.getByTestId("detection")).toBeInTheDocument();
  });

  it("shows a retryable error when the API is down", async () => {
    mockFetch({ "GET /api/explorer/catalogue": () => ({ status: 500, body: { detail: "boom" } }) });
    renderView(<ChangeAnalyticsView />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("Data & Methods", () => {
  it("lists the catalogue and source registry", async () => {
    mockFetch({
      "GET /api/explorer/catalogue": () => ({ body: { count: 1, datasets: [row("a", "Lake A", "official_derived", 3)] } }),
      "GET /api/explorer/source-registry": () => ({ body: { entries: [{ id: "s1", variable: "Built-up", providing_organization: "JRC", official_dataset_url: "https://example.org", dataset_identifier: "GHS", original_file_name: "f.tif", acquisition_or_temporal_coverage: "2000", spatial_resolution: "30 m", original_file_format: "GeoTIFF", license_or_terms: "CC BY 4.0", download_url: "", used_by_regions: ["bengaluru"] }, { id: "s2" }] } }),
      "GET /api/explorer/deeptime/sources": () => ({ body: [] }),
      "GET /api/explorer/deeptime/references": () => ({ body: [] }),
    });
    renderView(<DataMethodsView />);
    expect(await screen.findByTestId("catalogue")).toHaveTextContent("Lake A");
    expect(await screen.findByTestId("registry")).toHaveTextContent("CC BY 4.0");
    expect(screen.getByTestId("labels")).toHaveTextContent("GEOLOGICAL RECONSTRUCTION");
  });
});
