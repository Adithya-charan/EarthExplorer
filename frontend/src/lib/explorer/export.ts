import type { DatasetStats } from "./analytics";
import type { DatasetInfo } from "./types";

/** RFC 4180 CSV: quote fields with commas, quotes or line breaks. */
export function csvLine(fields: (string | number | null | undefined)[]): string {
  return fields
    .map((f) => {
      const s = f == null ? "" : String(f);
      return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    })
    .join(",");
}
export const toCsv = (rows: (string | number | null | undefined)[][]) => rows.map(csvLine).join("\r\n") + "\r\n";

/** One row per observation and class, in hectares, with the quality of that observation. */
export function observationsCsv(stats: DatasetStats): string {
  const rows: (string | number | null)[][] = [["dataset_id", "observation_date", "class", "area_ha", "valid_fraction", "nodata_pct", "quality", "footprint_ha"]];
  for (const o of stats.observations) {
    for (const [cls, ha] of Object.entries(o.class_area_ha)) rows.push([stats.dataset_id, o.date, cls, Number(ha.toFixed(3)), o.valid_fraction, o.nodata_pct, o.quality, o.footprint_ha]);
  }
  return toCsv(rows);
}

/** One row per variable and observation date (the series the Change Analytics page plots). */
export function seriesCsv(stats: DatasetStats): string {
  const rows: (string | number | null)[][] = [["dataset_id", "variable", "date", "area_ha", "share_of_valid_pct"]];
  for (const [key, v] of Object.entries(stats.variables)) for (const p of v.series) rows.push([stats.dataset_id, key, p.date, Number(p.area_ha.toFixed(3)), Number(p.share_of_valid_pct.toFixed(3))]);
  return toCsv(rows);
}

/** Record metadata laid out like a data-repository entry (field, value). It reports provenance as given; it does not change it. */
export function metadataRecord(d: DatasetInfo, stats: DatasetStats | null): [string, string][] {
  const [w, s, e, n] = d.bbox;
  return [
    ["Title", d.name],
    ["Dataset identifier", d.id],
    ["Data designation", d.public_label],
    ["Description", d.description],
    ["Source / provider", d.source],
    ["Product", d.product],
    ["Format", d.format],
    ["Coordinate reference system", d.crs],
    ["Spatial resolution (m)", String(d.resolution_m)],
    ["Temporal resolution", d.temporal_resolution],
    ["Temporal coverage", `${d.coverage.start} to ${d.coverage.end}`],
    ["Observations", `${d.observation_count} (${d.usable_count} usable)`],
    ["Spatial coverage (W, S, E, N)", `${w}, ${s}, ${e}, ${n}`],
    ["Centre (lat, lon)", `${((s + n) / 2).toFixed(4)}, ${((w + e) / 2).toFixed(4)}`],
    ["Classes", Object.entries(d.classes).map(([k, v]) => `${k}=${v}`).join("; ")],
    ["Processing method", stats?.method ?? ""],
    ["Known issues", d.issues.join(" | ")],
  ];
}
export const metadataCsv = (d: DatasetInfo, stats: DatasetStats | null) => toCsv([["field", "value"], ...metadataRecord(d, stats)]);
