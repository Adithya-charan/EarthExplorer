import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { GridUploadCard } from "./GridUploadCard";
import { datasetList } from "@/test/fixtures";
import { mockFetch } from "@/test/mockApi";
import { renderView } from "@/test/render";

const file = new File([new Uint8Array([1, 2, 3])], "grid.nc");

describe("grid upload card", () => {
  it("imports a grid and states how the regional series is made", async () => {
    mockFetch({
      "GET /api/datasets": () => ({ body: datasetList }),
      "GET /api/metadata": () => ({ status: 404, body: { error: { code: "x", message: "x" } } }),
      "POST /api/upload-grid": () => ({
        body: { dataset_id: "upload-1", name: "g", variable: "precip", unit: "mm/hr", n_times: 48, n_lat: 3, n_lon: 4, date_start: "2018-01-01", date_end: "2021-12-01", n_missing_cells_pct: 1, message: "Imported a 3×4 grid." },
      }),
    });
    const user = userEvent.setup();
    renderView(<GridUploadCard />);
    expect(screen.getByRole("button", { name: /import grid/i })).toBeDisabled();
    await user.upload(screen.getByLabelText(/netcdf file/i), file);
    await user.click(screen.getByRole("button", { name: /import grid/i }));
    expect(await screen.findByTestId("grid-success")).toHaveTextContent(/Imported a 3×4 grid.*mm\/hr/);
    expect(screen.getByText(/area-weighted mean of the valid cells/)).toBeInTheDocument();
  });

  it("shows the server's reason when the file cannot be used", async () => {
    mockFetch({
      "GET /api/datasets": () => ({ body: datasetList }),
      "GET /api/metadata": () => ({ status: 404, body: { error: { code: "x", message: "x" } } }),
      "POST /api/upload-grid": () => ({ status: 422, body: { error: { code: "ambiguous_variable", message: "choose one: a, b." } } }),
    });
    const user = userEvent.setup();
    renderView(<GridUploadCard />);
    await user.upload(screen.getByLabelText(/netcdf file/i), file);
    await user.click(screen.getByRole("button", { name: /import grid/i }));
    expect(await screen.findByTestId("grid-error")).toHaveTextContent("choose one: a, b.");
  });
});
