import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StoryView } from "./StoryView";
import { MethodologyView } from "./MethodologyView";
import { datasetList, metadata } from "@/test/fixtures";
import { atlasFixture, chatFixture, makeOverview, makeStory, regionsFixture, snapshotFixture } from "@/test/storyFixtures";
import { mockFetch } from "@/test/mockApi";
import { renderInShell, renderView } from "@/test/render";

// WebGL is not available in jsdom; the map itself is verified in a real browser.
vi.mock("@/components/story/PlacesMap", () => ({ PlacesMap: () => <div data-testid="places-map-stub" /> }));
vi.mock("@/components/story/StoryMap", () => ({
  StoryMap: (p: { region: string; index: number }) => (
    <div data-testid="story-map-stub">
      {p.region}:{p.index}
    </div>
  ),
}));

const okRoutes = {
  "GET /api/datasets": () => ({ body: datasetList }),
  "GET /api/metadata": () => ({ body: metadata }),
  "GET /api/regions": () => ({ body: regionsFixture }),
  "GET /api/overview": () => ({ body: makeOverview() }),
  "GET /api/atlas": () => ({ body: atlasFixture }),
  "GET /api/snapshot": () => ({ body: snapshotFixture }),
  "GET /api/geography/boundaries": () => ({ body: { type: "FeatureCollection", features: [], source: { note: "" } } }),
  "POST /api/story": () => ({ body: makeStory() }),
};

describe("story page and shell", () => {
  it("shows navigation with only the kept pages and loads the summary for the first region", async () => {
    mockFetch(okRoutes);
    renderInShell(<StoryView />);
    expect(screen.getByRole("link", { name: "Skip to main content" })).toBeInTheDocument();
    for (const name of ["What happened?", "Trend Analysis", "Upload Dataset", "Methodology / About"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    for (const gone of ["Overview", "Regional Comparison", "Data Explorer", "Earth Explorer"]) {
      expect(screen.queryByRole("link", { name: gone })).not.toBeInTheDocument();
    }
    const list = await screen.findByTestId("story-sentences");
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByTestId("story-map-stub")).toHaveTextContent("Alpha:0");
  });

  it("labels synthetic data and keeps the NASA status visible", async () => {
    mockFetch(okRoutes);
    renderInShell(<StoryView />);
    await screen.findByTestId("story-sentences");
    expect(screen.getAllByText(/SYNTHETIC DEMO/i).length).toBeGreaterThan(0);
    expect(screen.getByTestId("nasa-status")).toHaveTextContent(/not been provided or integrated/i);
  });

  it("moves the map month with the slider and says plainly when a month has no value", async () => {
    mockFetch({
      ...okRoutes,
      "POST /api/story": () => {
        const s = makeStory();
        s.months[1] = { ...s.months[1], value: null, anomaly: null, anomaly_z: null, unusual: false };
        return { body: s };
      },
    });
    renderView(<StoryView />);
    await screen.findByTestId("story-sentences");
    const slider = screen.getByRole("slider", { name: /month shown on the map/i });
    fireEvent.change(slider, { target: { value: "1" } });
    expect(screen.getByTestId("story-map-stub")).toHaveTextContent("Alpha:1");
    expect(screen.getByTestId("map-readout")).toHaveTextContent(/nothing is drawn or filled in/);
  });

  it("shows an error state, not stale text, when the summary cannot be built", async () => {
    mockFetch({
      ...okRoutes,
      "POST /api/story": () => ({ status: 422, body: { error: { code: "no_rows_in_range", message: "No valid observations." } } }),
    });
    renderView(<StoryView />);
    expect(await screen.findByTestId("error-state")).toHaveTextContent("No valid observations.");
    expect(screen.queryByTestId("story-sentences")).not.toBeInTheDocument();
  });

  it("chat answers drive the page: a story question changes the region and period", async () => {
    const fetchMock = mockFetch({
      ...okRoutes,
      "POST /api/chat": () => ({ body: chatFixture(makeStory({ region: "Beta" })) }),
    });
    const user = userEvent.setup();
    renderView(<StoryView />);
    await screen.findByTestId("story-sentences");
    await user.type(screen.getByLabelText("Your question"), "what happened in Beta in early 2021");
    await user.click(screen.getByRole("button", { name: /ask/i }));
    expect(await screen.findByText(/Understood:/)).toHaveTextContent("place: Alpha");
    await vi.waitFor(() => {
      const storyCalls = fetchMock.mock.calls.filter(([u]) => new URL(String(u)).pathname === "/api/story");
      expect(JSON.parse(String(storyCalls.at(-1)![1]!.body)).region).toBe("Beta");
    });
  });

  it("shows loading skeletons before data arrives", () => {
    mockFetch({ "GET /api/datasets": () => new Promise(() => {}) as never });
    renderView(<StoryView />);
    expect(screen.getAllByTestId("loading-state").length).toBeGreaterThan(0);
  });

  it("shows a clear error with a working retry when the API is unreachable", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);
    renderView(<StoryView />);
    const error = await screen.findByTestId("error-state");
    expect(error).toHaveTextContent(/Cannot reach the EarthTrend API/);
    const calls = fetchMock.mock.calls.length;
    await userEvent.setup().click(screen.getByRole("button", { name: /try again/i }));
    await screen.findByTestId("error-state");
    expect(fetchMock.mock.calls.length).toBeGreaterThan(calls);
  });

  it("shows an empty state with a way forward when no dataset exists", async () => {
    mockFetch({ "GET /api/datasets": () => ({ body: { ...datasetList, datasets: [], default_dataset_id: null } }) });
    renderView(<StoryView />);
    expect(await screen.findByTestId("empty-state")).toHaveTextContent(/No dataset is loaded/);
    expect(screen.getByRole("link", { name: "Upload a dataset" })).toHaveAttribute("href", "/upload");
  });
});

describe("methodology page", () => {
  it("renders sections and references from the API", async () => {
    mockFetch({
      "GET /api/methodology": () => ({
        body: {
          sections: [{ id: "scope", title: "Scope and limits", body: ["Trends are not causes."] }],
          references: [{ citation: "Mann (1945)", url: null }],
          defaults: { alpha: 0.05 },
        },
      }),
    });
    renderView(<MethodologyView />);
    expect(await screen.findByText("Scope and limits")).toBeInTheDocument();
    expect(screen.getByText("Trends are not causes.")).toBeInTheDocument();
    expect(screen.getByText("Mann (1945)")).toBeInTheDocument();
    expect(screen.getByText(/not been scientifically validated/i)).toBeInTheDocument();
  });

  it("shows an error state if the methodology cannot be loaded", async () => {
    mockFetch({
      "GET /api/methodology": () => ({ status: 500, body: { error: { code: "internal_error", message: "Boom" } } }),
    });
    renderView(<MethodologyView />);
    expect(await screen.findByTestId("error-state")).toHaveTextContent("Boom");
  });
});
