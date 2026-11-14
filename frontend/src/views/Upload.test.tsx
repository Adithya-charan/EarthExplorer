import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { UploadView } from "./UploadView";
import { datasetList, demoSummary, profile, quality } from "@/test/fixtures";
import { mockFetch } from "@/test/mockApi";
import { renderView } from "@/test/render";
import type { ColumnMapping, DatasetListResponse, QualityReport } from "@/lib/types";

const baseRoutes = {
  "GET /api/datasets": () => ({ body: datasetList }),
  "GET /api/metadata": () => ({ status: 404, body: { error: { code: "not_found", message: "n/a" } } }),
};

// userEvent normally drops files that do not match the input's `accept`; the browser would still
// let a user drag one in, so turn that filter off to exercise our own validation.
const setup = () => userEvent.setup({ applyAccept: false });

const fileInput = () => screen.getByLabelText(/choose csv file/i, { selector: "input" }) as HTMLInputElement;

describe("Upload Dataset: client-side validation", () => {
  it("rejects non-CSV files with a clear message and does not call the API", async () => {
    const fetchMock = mockFetch(baseRoutes);
    renderView(<UploadView />);
    await setup().upload(fileInput(), new File(["x"], "granule.nc"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Only \.csv files are supported/);
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/api/profile"))).toBe(false);
  });

  it("rejects an empty file", async () => {
    mockFetch(baseRoutes);
    renderView(<UploadView />);
    await setup().upload(fileInput(), new File([], "empty.csv"));
    expect(await screen.findByRole("alert")).toHaveTextContent("This file is empty.");
  });

  it("rejects a file over the size limit", async () => {
    mockFetch(baseRoutes);
    renderView(<UploadView />);
    const big = new File(["x"], "big.csv");
    Object.defineProperty(big, "size", { value: 30 * 1024 * 1024 });
    await setup().upload(fileInput(), big);
    expect(await screen.findByRole("alert")).toHaveTextContent(/over the 25 MB limit/);
  });

  it("states the support limits up front", async () => {
    mockFetch(baseRoutes);
    renderView(<UploadView />);
    expect(screen.getByText(/HDF5 and GeoTIFF are not read/)).toBeInTheDocument();
    expect(screen.getByText(/never treated as NASA-verified/)).toBeInTheDocument();
  });
});

describe("Upload Dataset: server feedback", () => {
  it("shows the server's rejection message when profiling fails", async () => {
    mockFetch({
      ...baseRoutes,
      "POST /api/profile": () => ({
        status: 422,
        body: { error: { code: "malformed_csv", message: "Row 3 has 5 fields but the header has 4." } },
      }),
    });
    renderView(<UploadView />);
    await setup().upload(fileInput(), new File(["a,b\n1,2"], "bad.csv"));
    const error = await screen.findByTestId("error-state");
    expect(error).toHaveTextContent("Row 3 has 5 fields");
    expect(error).toHaveTextContent("malformed_csv");
    expect(screen.getByLabelText(/choose csv file/i, { selector: "input" })).toBeInTheDocument(); // can retry
  });
});

describe("Upload Dataset: mapping, validation and import", () => {
  function importedList(): DatasetListResponse {
    const uploaded = { ...demoSummary, id: "upload-1", name: "sample", status: "uploaded" as const, is_synthetic: false };
    return { ...datasetList, datasets: [demoSummary, uploaded], default_dataset_id: "synthetic-demo" };
  }

  it("previews the file, requires explicit unit and source, then validates and imports", async () => {
    let imported = false;
    const posted: { dry_run?: string; confirmed?: string; mapping?: ColumnMapping }[] = [];
    mockFetch({
      "GET /api/datasets": () => ({ body: imported ? importedList() : datasetList }),
      "GET /api/metadata": () => ({ status: 404, body: { error: { code: "not_found", message: "n/a" } } }),
      "POST /api/profile": () => ({ body: profile }),
      "POST /api/upload": (_u: URL, init?: RequestInit) => {
        const form = init?.body as FormData;
        posted.push({
          dry_run: String(form.get("dry_run")),
          confirmed: String(form.get("confirmed")),
          mapping: JSON.parse(String(form.get("mapping"))) as ColumnMapping,
        });
        if (form.get("dry_run") === "true") return { body: { imported: false, dry_run: true, quality, dataset: null, message: "ok" } };
        imported = true;
        return {
          body: {
            imported: true,
            dry_run: false,
            quality,
            dataset: importedList().datasets[1],
            message: "Imported 2 rows.",
          },
        };
      },
    });
    const user = setup();
    renderView(<UploadView />);
    await user.upload(fileInput(), new File(["when,place,what,reading\n2020-01-01,North,Index,1.5"], "sample.csv"));

    // Preview and suggested mapping
    const preview = await screen.findByTestId("upload-preview");
    expect(within(preview).getAllByText("North", { selector: "td" })).toHaveLength(2); // both preview rows
    expect(screen.getByLabelText("Date (required)")).toHaveValue("when");
    expect(screen.getByText(/No unit column was found/)).toBeInTheDocument();

    // Unit and source are never guessed, so validation is blocked until the user declares them
    expect(screen.getByTestId("mapping-missing")).toHaveTextContent("unit, data source, synthetic or real declaration");
    const validate = screen.getByRole("button", { name: "Validate file" });
    expect(validate).toBeDisabled();

    await user.type(screen.getByLabelText(/declare one unit/i), "u");
    await user.type(screen.getByLabelText(/declare one data source/i), "Provided by the uploader");
    // Provenance is a required, explicit choice: leaving it unanswered keeps validation blocked
    expect(validate).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: /No, measured or externally sourced data/ }));
    expect(screen.queryByTestId("mapping-missing")).not.toBeInTheDocument();
    expect(validate).toBeEnabled();

    // Dry run
    await user.click(validate);
    const report = await screen.findByTestId("quality-report");
    expect(report).toHaveTextContent("This file can be imported");
    expect(posted[0]).toMatchObject({ dry_run: "true", confirmed: "false" });
    expect(posted[0].mapping?.defaults).toMatchObject({
      unit: "u",
      data_source: "Provided by the uploader",
      is_synthetic: false,
    });

    // Import
    await user.click(screen.getByRole("button", { name: "Import dataset" }));
    expect(await screen.findByTestId("import-success")).toHaveTextContent(/Imported 2 rows\. It is now the selected dataset/);
    expect(posted[1]).toMatchObject({ dry_run: "false" });

    // The new dataset appears in the uploaded list, labelled as an unverified upload
    await waitFor(() => expect(screen.getByText("sample")).toBeInTheDocument());
    expect(screen.getAllByTestId("dataset-status").some((el) => /Uploaded dataset/.test(el.textContent ?? ""))).toBe(true);
  });

  it("blocks import until ambiguous mappings are explicitly confirmed", async () => {
    const ambiguous: QualityReport = {
      ...quality,
      ambiguities: ["Dates like 03/04/2020 could be day/month or month/day; day-first was assumed."],
      requires_confirmation: true,
    };
    mockFetch({
      ...baseRoutes,
      "POST /api/profile": () => ({
        body: {
          ...profile,
          suggested_mapping: { ...profile.suggested_mapping, defaults: { unit: "u", data_source: "src", is_synthetic: false } },
        },
      }),
      "POST /api/upload": () => ({ body: { imported: false, dry_run: true, quality: ambiguous, dataset: null, message: "ok" } }),
    });
    const user = setup();
    renderView(<UploadView />);
    await user.upload(fileInput(), new File(["a"], "sample.csv"));
    await user.click(await screen.findByRole("button", { name: "Validate file" }));

    expect(await screen.findByText(/day\/month or month\/day/)).toBeInTheDocument();
    const importButton = screen.getByRole("button", { name: "Import dataset" });
    expect(importButton).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /confirm this mapping is correct/i }));
    expect(importButton).toBeEnabled();
  });

  it("explains errors from validation and offers no import", async () => {
    const failing: QualityReport = {
      ...quality,
      can_import: false,
      n_invalid_dates: 2,
      issues: [{ severity: "error", code: "invalid_dates", message: "2 rows have unreadable dates.", count: 2, examples: ["tomorrow"] }],
    };
    mockFetch({
      ...baseRoutes,
      "POST /api/profile": () => ({
        body: {
          ...profile,
          suggested_mapping: { ...profile.suggested_mapping, defaults: { unit: "u", data_source: "src", is_synthetic: false } },
        },
      }),
      "POST /api/upload": () => ({ body: { imported: false, dry_run: true, quality: failing, dataset: null, message: "no" } }),
    });
    const user = setup();
    renderView(<UploadView />);
    await user.upload(fileInput(), new File(["a"], "sample.csv"));
    await user.click(await screen.findByRole("button", { name: "Validate file" }));

    const report = await screen.findByTestId("quality-report");
    expect(report).toHaveTextContent("This file cannot be imported yet");
    expect(report).toHaveTextContent("2 rows have unreadable dates.");
    expect(report).toHaveTextContent("Error"); // severity is stated in text, not only colour
    expect(screen.queryByRole("button", { name: "Import dataset" })).not.toBeInTheDocument();
  });
});
