import { describe, expect, it } from "vitest";
import { analysisToCsv, comparisonToCsv, csvCell, safeFilePart } from "./csv";
import { fmtNum, fmtP, fmtPct, fmtSigned } from "./format";
import { EMPTY_MAPPING, MAX_UPLOAD_BYTES, missingRequired, validateUploadFile } from "./upload";
import { makeAnalysis, makeComparison, provenance } from "@/test/fixtures";

describe("number formatting", () => {
  it("formats p-values without implying exactly zero", () => {
    expect(fmtP(0.0000001)).toBe("< 0.001");
    expect(fmtP(0.0432)).toBe("0.043");
    expect(fmtP(null)).toBe("n/a");
  });

  it("shows n/a for missing numbers rather than 0 or NaN", () => {
    expect(fmtNum(null)).toBe("n/a");
    expect(fmtNum(Number.NaN)).toBe("n/a");
    expect(fmtSigned(undefined)).toBe("n/a");
    expect(fmtPct(null)).toBe("n/a");
  });

  it("signs positive numbers and keeps significant digits", () => {
    expect(fmtSigned(2.5)).toBe("+2.5");
    expect(fmtSigned(-0.123456, 3)).toBe("-0.123");
    expect(fmtNum(0)).toBe("0");
  });
});

describe("CSV export", () => {
  it("neutralises spreadsheet formula injection in text cells", () => {
    expect(csvCell("=HYPERLINK(\"http://x\")", true)).toMatch(/^"'=/);
    expect(csvCell("+1+1", true)).toBe("'+1+1");
    expect(csvCell("@cmd", true)).toBe("'@cmd");
    expect(csvCell(-3.5)).toBe("-3.5"); // numbers are never prefixed
  });

  it("quotes cells containing commas, quotes or newlines", () => {
    expect(csvCell("a,b", true)).toBe('"a,b"');
    expect(csvCell('say "hi"', true)).toBe('"say ""hi"""');
  });

  it("carries the synthetic label and data source in analysis exports", () => {
    const csv = analysisToCsv(makeAnalysis("Alpha"));
    expect(csv).toContain("is_synthetic: true");
    expect(csv).toContain("status: synthetic_demo");
    expect(csv).toContain("SYNTHETIC DEMO DATA");
    expect(csv.split("\n").some((l) => l.startsWith("date,region,variable,value,unit"))).toBe(true);
    // every data row repeats the source flag
    const dataRows = csv.trim().split("\n").filter((l) => /^\d{4}-\d{2}-\d{2},/.test(l));
    expect(dataRows).toHaveLength(24);
    expect(dataRows.every((l) => l.endsWith("true"))).toBe(true);
  });

  it("leaves missing values empty instead of writing 0", () => {
    const csv = analysisToCsv(makeAnalysis("Alpha"));
    expect(csv).toContain("2020-06-01,Alpha,Index A,,"); // index 5 has a null value
  });

  it("exports comparisons with provenance and adjusted p-values", () => {
    const csv = comparisonToCsv(makeComparison(["Alpha", "Beta"]));
    expect(csv).toContain("p_value_bh_adjusted");
    expect(csv).toContain(`is_synthetic: ${provenance.is_synthetic}`);
    expect(csv).toContain("Alpha");
    expect(csv).toContain("Beta");
  });

  it("builds safe file names", () => {
    expect(safeFilePart("../../etc/passwd")).toBe("etc_passwd");
    expect(safeFilePart("Index A / Beta")).toBe("Index_A_Beta");
    expect(safeFilePart("")).toBe("export");
  });
});

describe("upload validation", () => {
  it("accepts a normal CSV", () => {
    expect(validateUploadFile({ name: "data.csv", size: 1000 })).toBeNull();
    expect(validateUploadFile({ name: "DATA.CSV", size: 1000 })).toBeNull();
  });

  it("rejects non-CSV formats and says why", () => {
    expect(validateUploadFile({ name: "granule.nc", size: 1000 })).toMatch(/Only \.csv files/);
    expect(validateUploadFile({ name: "granule.hdf", size: 1000 })).toMatch(/NetCDF, HDF/);
    expect(validateUploadFile({ name: "noext", size: 1000 })).toMatch(/no extension/);
  });

  it("rejects empty and oversized files", () => {
    expect(validateUploadFile({ name: "a.csv", size: 0 })).toMatch(/empty/);
    expect(validateUploadFile({ name: "a.csv", size: MAX_UPLOAD_BYTES + 1 })).toMatch(/over the 25 MB limit/);
  });
});

describe("mapping completeness", () => {
  it("lists required fields that have neither a column nor a declared value", () => {
    expect(missingRequired(EMPTY_MAPPING)).toEqual([
      "date",
      "value",
      "region",
      "variable",
      "unit",
      "data source",
      "synthetic or real declaration",
    ]);
  });

  it("requires an explicit synthetic/real declaration, and accepts either answer or a flag column", () => {
    const base = { ...EMPTY_MAPPING, date: "d", value: "v", defaults: { region: "R", variable: "V", unit: "u", data_source: "s" } };
    expect(missingRequired(base)).toEqual(["synthetic or real declaration"]);
    expect(missingRequired({ ...base, defaults: { ...base.defaults, is_synthetic: false } })).toEqual([]); // "no" is an answer
    expect(missingRequired({ ...base, defaults: { ...base.defaults, is_synthetic: true } })).toEqual([]);
    expect(missingRequired({ ...base, is_synthetic: "flag_col" })).toEqual([]);
  });

  it("accepts declared constants in place of columns", () => {
    const m = {
      ...EMPTY_MAPPING,
      date: "d",
      value: "v",
      defaults: { region: "R", variable: "V", unit: "u", data_source: "s", is_synthetic: false },
    };
    expect(missingRequired(m)).toEqual([]);
  });
});

describe("csv export header", () => {
  it("carries dataset_sha256 and the API response's generated_at, without making a new timestamp", async () => {
    const { analysisToCsv } = await import("./csv");
    const { makeAnalysis, provenance } = await import("@/test/fixtures");
    const stamp = "2026-01-02T03:04:05+00:00";
    const a = makeAnalysis("Alpha", { provenance: { ...provenance, dataset_checksum: "ab".repeat(32), generated_at: stamp } });
    const line = analysisToCsv(a).split("\n")[1];
    expect(line).toContain(`dataset_sha256: ${"ab".repeat(32)}`);
    expect(line).toContain(`generated_at: ${stamp}`);
  });
});
