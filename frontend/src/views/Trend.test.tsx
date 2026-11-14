import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TrendView } from "./TrendView";
import { datasetList, makeAnalysis, metadata } from "@/test/fixtures";
import { mockFetch, requestBodies } from "@/test/mockApi";
import { renderView } from "@/test/render";
import type { AnalyzeRequest } from "@/lib/types";

const routes = {
  "GET /api/datasets": () => ({ body: datasetList }),
  "GET /api/metadata": () => ({ body: metadata }),
  "POST /api/analyze": (_url: URL, init?: RequestInit) => ({
    body: makeAnalysis((JSON.parse(String(init?.body)) as AnalyzeRequest).region),
  }),
};

describe("Trend Analysis", () => {
  it("runs an analysis on load and shows the headline result with uncertainty", async () => {
    mockFetch(routes);
    renderView(<TrendView />);

    expect(await screen.findByTestId("trend-results")).toBeInTheDocument();
    expect(screen.getByTestId("trend-label")).toHaveTextContent("Increasing trend");
    expect(screen.getByTestId("slope-value")).toHaveTextContent("+6");
    expect(screen.getByTestId("p-value")).toHaveTextContent("< 0.001");
    expect(screen.getAllByText(/index units per year/).length).toBeGreaterThanOrEqual(1); // slope is never shown without its unit
    expect(screen.getByText(/95% interval/)).toBeInTheDocument();
    expect(screen.getByText(/1 missing of 24 rows/)).toBeInTheDocument();
  });

  it("labels synthetic data on the results page and in the chart", async () => {
    mockFetch(routes);
    renderView(<TrendView />);
    await screen.findByTestId("trend-results");

    expect(screen.getByTestId("synthetic-banner")).toHaveTextContent(/synthetic/i);
    expect(screen.getByRole("figure", { name: /Synthetic demo data/ })).toBeInTheDocument();
    expect(screen.getByTestId("trend-chart")).toBeInTheDocument();
  });

  it("shows every computed method, cautions and rule-based explanation", async () => {
    mockFetch(routes);
    renderView(<TrendView />);
    await screen.findByTestId("trend-results");

    const table = screen.getByTestId("stats-table");
    expect(within(table).getByText("OLS linear regression")).toBeInTheDocument();
    expect(within(table).getByText("Mann-Kendall test")).toBeInTheDocument();
    expect(within(table).getByText("Sen's slope")).toBeInTheDocument();
    expect(screen.getByTestId("warnings")).toHaveTextContent(/under two years/);
    expect(screen.getByTestId("explanation")).toHaveTextContent("Index A in Alpha shows an increasing trend");
    expect(screen.getByText(/No AI service is used/)).toBeInTheDocument();
    expect(screen.getByText(/does not identify causes/)).toBeInTheDocument();
  });

  it("re-runs the analysis with the new region when a filter changes", async () => {
    const fetchMock = mockFetch(routes);
    const user = userEvent.setup();
    renderView(<TrendView />);
    await screen.findByTestId("trend-results");

    await user.selectOptions(screen.getByLabelText("Region"), "Beta");

    await screen.findByText(/Index A in Beta shows an increasing trend/);
    const bodies = requestBodies(fetchMock, "/api/analyze") as AnalyzeRequest[];
    expect(bodies[0].region).toBe("Alpha");
    expect(bodies.at(-1)?.region).toBe("Beta");
    expect(bodies.at(-1)?.dataset_id).toBe("synthetic-demo");
  });

  it("sends aggregation, seasonality and alpha choices to the API", async () => {
    const fetchMock = mockFetch(routes);
    const user = userEvent.setup();
    renderView(<TrendView />);
    await screen.findByTestId("trend-results");

    await user.selectOptions(screen.getByLabelText("Aggregation"), "annual");
    await user.selectOptions(screen.getByLabelText("Seasonality"), "none");
    await user.selectOptions(screen.getByLabelText(/Significance level/), "0.01");

    await screen.findByTestId("trend-results");
    const last = (requestBodies(fetchMock, "/api/analyze") as AnalyzeRequest[]).at(-1)!;
    expect(last).toMatchObject({ aggregation: "annual", seasonality: "none", alpha: 0.01 });
  });

  it("sends the date window after the user stops typing", async () => {
    const fetchMock = mockFetch(routes);
    renderView(<TrendView />);
    await screen.findByTestId("trend-results");

    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2021-01-01" } });

    await screen.findByTestId("trend-results");
    await waitFor(() => {
      const last = (requestBodies(fetchMock, "/api/analyze") as AnalyzeRequest[]).at(-1)!;
      expect(last.start).toBe("2021-01-01");
    });
  });

  it("does not call the API for an inverted date range and says why", async () => {
    const fetchMock = mockFetch(routes);
    renderView(<TrendView />);
    await screen.findByTestId("trend-results");
    const before = requestBodies(fetchMock, "/api/analyze").length;

    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2021-06-01" } });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2020-06-01" } });

    expect((await screen.findAllByText(/start date must be on or before the end date/i)).length).toBeGreaterThan(0);
    await new Promise((r) => setTimeout(r, 450)); // longer than the debounce
    expect(requestBodies(fetchMock, "/api/analyze").length).toBe(before);
  });

  it("shows a loading state while the analysis runs", async () => {
    mockFetch({ ...routes, "POST /api/analyze": () => new Promise(() => {}) as never });
    renderView(<TrendView />);
    await screen.findByLabelText("Variable");
    expect((await screen.findAllByTestId("loading-state")).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("trend-results")).not.toBeInTheDocument();
  });

  it("shows the server's message with a retry when the analysis fails", async () => {
    let fail = true;
    mockFetch({
      ...routes,
      "POST /api/analyze": (_u: URL, init?: RequestInit) =>
        fail
          ? { status: 422, body: { error: { code: "unknown_region", message: "Region 'Alpha' was not found." } } }
          : { body: makeAnalysis((JSON.parse(String(init?.body)) as AnalyzeRequest).region) },
    });
    const user = userEvent.setup();
    renderView(<TrendView />);

    const error = await screen.findByTestId("error-state");
    expect(error).toHaveTextContent("Region 'Alpha' was not found.");
    expect(error).toHaveTextContent("unknown_region");

    fail = false;
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByTestId("trend-results")).toBeInTheDocument();
  });

  it("says plainly when there is not enough data for a trend, instead of inventing one", async () => {
    mockFetch({
      ...routes,
      "POST /api/analyze": () => ({
        body: makeAnalysis("Alpha", {
          linear_regression: null,
          mann_kendall: null,
          sens_slope: null,
          explanation: null,
          primary: {
            available: false,
            status: "insufficient_data",
            trend: "insufficient_data",
            estimated_direction: "unknown",
            test_name: null,
            p_value: null,
            alpha: 0.05,
            significant: null,
            slope_per_year: null,
            slope_ci_low: null,
            slope_ci_high: null,
            slope_method: null,
            unit: "index units",
            slope_unit: "index units per year",
            total_change_over_period: null,
            reason: "Only 4 valid observations; at least 8 are needed.",
          },
        }),
      }),
    });
    renderView(<TrendView />);

    expect(await screen.findByText("No trend estimate")).toBeInTheDocument();
    expect(screen.getByText(/at least 8 are needed/)).toBeInTheDocument();
    expect(screen.getByTestId("trend-label")).toHaveTextContent("Insufficient data");
    expect(screen.queryByTestId("slope-value")).not.toBeInTheDocument();
    expect(screen.getByText(/No tests were computed/)).toBeInTheDocument();
  });

  it("can reveal the plotted values as an accessible table", async () => {
    mockFetch(routes);
    const user = userEvent.setup();
    renderView(<TrendView />);
    await screen.findByTestId("trend-results");

    await user.click(screen.getByRole("button", { name: /show data table/i }));
    const table = screen.getByRole("table", { name: /values plotted in the chart/i });
    expect(within(table).getAllByRole("row")).toHaveLength(25); // header + 24 points
    expect(within(table).getByText("missing")).toBeInTheDocument(); // the null point is not hidden or zeroed
  });
});
