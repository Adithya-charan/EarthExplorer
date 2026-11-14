import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Chronicle } from "./Chronicle";
import { atlasFixture, makeOverview, snapshotFixture } from "@/test/storyFixtures";
import { datasetList } from "@/test/fixtures";
import { mockFetch } from "@/test/mockApi";
import { renderView } from "@/test/render";

// WebGL is not available in jsdom; the map itself is verified in a real browser.
vi.mock("@/components/story/PlacesMap", () => ({ PlacesMap: () => null }));

const routes = (over = makeOverview()) => ({
  "GET /api/datasets": () => ({ body: datasetList }),
  "GET /api/metadata": () => ({ status: 404, body: { error: { code: "x", message: "x" } } }),
  "GET /api/overview": () => ({ body: over }),
  "GET /api/atlas": () => ({ body: atlasFixture }),
  "GET /api/snapshot": () => ({ body: snapshotFixture }),
});

function setup(over = makeOverview()) {
  mockFetch(routes(over));
  const onPickPeriod = vi.fn();
  const onPickRegion = vi.fn();
  renderView(<Chronicle datasetId="synthetic-demo" region="Alpha" boundaries={null} onPickPeriod={onPickPeriod} onPickRegion={onPickRegion} />);
  return { onPickPeriod, onPickRegion };
}

describe("whole-record view", () => {
  it("shows the headline numbers and one stripe per year", async () => {
    setup();
    const hero = await screen.findByTestId("chronicle-hero");
    expect(hero).toHaveTextContent("Alpha");
    expect(hero).toHaveTextContent("2019–2021");
    expect(hero.querySelectorAll("svg rect")).toHaveLength(3);
    expect(hero).toHaveTextContent("Most above normal");
    expect(hero).toHaveTextContent("2019");
  });

  it("says plainly that a year with too few months has no yearly number", async () => {
    setup();
    const hero = await screen.findByTestId("chronicle-hero");
    fireEvent.mouseEnter(hero.querySelectorAll("svg rect")[1]);
    expect(screen.getByTestId("hero-readout")).toHaveTextContent("only 6 valid months, so no yearly number");
  });

  it("clicking a stripe explains that whole year", async () => {
    const { onPickPeriod } = setup();
    const hero = await screen.findByTestId("chronicle-hero");
    fireEvent.click(hero.querySelectorAll("svg rect")[0]);
    expect(onPickPeriod).toHaveBeenCalledWith("2019-01", "2019-12");
  });

  it("clicking a calendar cell explains that month; empty cells are labelled as not filled in", async () => {
    const { onPickPeriod } = setup();
    const cal = await screen.findByTestId("rain-calendar");
    const cells = Array.from(cal.querySelectorAll("rect"));
    fireEvent.click(cells[0 * 12 + 6]); // Jul 2019
    expect(onPickPeriod).toHaveBeenCalledWith("2019-07", "2019-07");
    fireEvent.mouseEnter(cells[1 * 12 + 8]); // Sep 2020 has no value
    expect(screen.getByTestId("calendar-readout")).toHaveTextContent("no value (left empty, not filled in)");
    fireEvent.click(cells[1 * 12 + 8]);
    expect(onPickPeriod).toHaveBeenLastCalledWith("2020-01", "2020-12"); // falls back to the year
  });

  it("lists the evidence behind each sentence and the caveats", async () => {
    setup();
    const list = await screen.findByTestId("chronicle-sentences");
    expect(within(list).getByText(/runs from 2019 to 2021/).closest("li")).toHaveAttribute("title", "Evidence: n=30");
    expect(screen.getByText(/fewer than 12 valid months/)).toBeInTheDocument();
  });

  it("opens another region from the all-regions view", async () => {
    const { onPickRegion } = setup();
    const atlas = await screen.findByTestId("atlas");
    fireEvent.click(within(atlas).getByRole("button", { name: "Open Beta" }));
    expect(onPickRegion).toHaveBeenCalledWith("Beta");
  });

  it("shows the map-in-motion summary with a label for the chosen year", async () => {
    setup();
    const card = await screen.findByTestId("snapshot");
    expect(await within(card).findByTestId("snapshot-label")).toHaveTextContent("2021");
    expect(await within(card).findByTestId("snapshot-sentences")).toHaveTextContent("2 of 2 regions were above usual");
  });

  it("labels synthetic data in the banner", async () => {
    setup(makeOverview({ banner: "SYNTHETIC DEMO — NOT NASA OBSERVATIONS" }));
    await screen.findByTestId("chronicle-hero");
    expect(screen.getAllByText(/SYNTHETIC DEMO|Synthetic demo/i).length).toBeGreaterThan(0);
  });
});
