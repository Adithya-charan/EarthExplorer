# Data schema

Every dataset, whatever its source format, is converted to one **canonical long-format table** before it is
analysed. One row is one observation of one variable, in one region, at one time. The definition lives in
`backend/app/services/ingestion/schema.py` and `backend/app/schemas.py`.

> The bundled demo file is **synthetic**. Nothing in this document describes a NASA product: the real dataset
> has not been supplied, so no NASA-specific fields, units or conventions are assumed.

## Canonical columns

### Required

| Column | Type | Meaning and rules |
| --- | --- | --- |
| `date` | datetime | When the value applies. ISO 8601 is read directly. Plain dates (`2020-03-01`) are kept as dates; timestamps keep their time. Rows whose date cannot be read are **dropped and counted**, never guessed. |
| `region` | text | A label for where the value applies. It is a **label only**: it is never converted into coordinates or boundaries. |
| `variable` | text | The quantity measured. Different units for the same variable are reported, never converted. |
| `value` | number or missing | Finite number, or missing. Missing is kept as missing (never `0`, never interpolated). Text that is not a number is an *invalid value*: counted, reported, and treated as missing. |
| `unit` | text | The unit as supplied. **Never guessed and never converted.** Must come from a column or be declared explicitly by the person uploading. |
| `data_source` | text | Where the data came from, as stated by the file or the uploader. Travels with every row and every export. |
| `is_synthetic` | boolean | `true` for synthetic or test data. Must be given explicitly (a column, or a yes/no declaration). **Provenance is never guessed.** |

### Optional

These are included only if the source has them. The app lists which are present and reports the rest as absent
(Data Explorer -> *Not in this dataset*). Nothing is inferred.

`dataset_id`, `dataset_name`, `mission`, `instrument`, `product`, `quality_flag`, `latitude`, `longitude`,
`spatial_geometry`, `spatial_resolution`, `temporal_resolution`, `original_variable`, `original_unit`, `source_file`

- `latitude` must be within -90..90 and `longitude` within -180..180. Out-of-range values are reported
  (`invalid_latitude`, `invalid_longitude`) and not used. A map is offered only when real coordinates exist.
- The app does **not** know whether coordinates describe a point, a grid-cell centre or a regional centroid, and says so.

### Traceability (added on import)

| Column | Meaning |
| --- | --- |
| `original_value` | The value exactly as read from the file, before any change. |
| `transformation_note` | Empty unless a step changed the value. No unit conversion is ever performed, so the only change today is averaging duplicates when the user chose that policy. |

## Reading a CSV

1. **Structure.** The file must be text (a NUL byte means it is rejected as binary), non-empty, and every row must
   have the same number of fields as the header; otherwise the import stops and names the offending line.
2. **Encoding.** UTF-8 (with or without BOM). If that fails the file is decoded as Windows-1252 and a warning says so.
3. **Delimiter.** Detected among `,` `;` tab and `|`.
4. **Column mapping.** `POST /api/profile` *suggests* a mapping from common column names (`date`, `timestamp`,
   `region`, `site`, `variable`, `parameter`, `value`, `reading`, `unit`, `source`, `lat`, `lon`, ...). It is only a
   suggestion: the user reviews and changes it, and anything the file does not contain must be declared.
5. **Missing-value tokens.** Empty, `NA`, `N/A`, `NaN`, `null`, `None`, `-`, `--` (case-insensitive) mean "no value".
6. **Sentinel codes.** Values such as `-9999`, `-999`, `9999`, `1e20`, `9.96921e36` are **not** silently treated as
   missing (that would be a guess). The quality report warns (`possible_missing_value_codes`) so the user can decide.
7. **Booleans** (`is_synthetic`): `true/t/yes/y/1` and `false/f/no/n/0`, case-insensitive. Anything else is reported
   (`invalid_is_synthetic`).
8. **Dates.** ISO 8601 first. A second pass accepts only text that is structurally a date (numeric `d/m/y` or digits
   with a month name). Bare numbers or words are never turned into dates. A `date_format` (strptime pattern) can be
   given. Slash dates such as `03/04/2020` are **ambiguous** (day/month or month/day), so the import requires an
   explicit confirmation.

### Duplicates

Rows with the same `date`, `region`, `variable` are duplicates.

| Situation | Result |
| --- | --- |
| Identical values | Collapsed to one row (`duplicates_identical`, informational). |
| Different values, policy `error` (default) | Import blocked (`duplicate_conflict`). |
| Different units | Always blocked (`duplicate_unit_conflict`). |
| Different values, policy `mean` / `first` / `last` | Resolved as chosen, flagged `duplicates_resolved`, and the user must confirm. For `mean`, `transformation_note` records the change. |

### Quality report

Returned by `POST /api/upload` (use `dry_run=true` to validate without importing). It counts source rows, rows
kept and dropped, invalid dates/values/labels, missing values and duplicates, lists variables, regions, units per
variable and the date range, and carries `issues` (each `error`, `warning` or `info`), `ambiguities`,
`can_import` and `requires_confirmation`.

Issue codes: `malformed_csv`, `encoding`, `invalid_dates`, `invalid_values`, `missing_labels`, `blank_data_source`,
`invalid_is_synthetic`, `invalid_latitude`, `invalid_longitude`, `missing_values`, `duplicates_identical`,
`duplicate_conflict`, `duplicate_unit_conflict`, `duplicates_resolved`, `no_valid_rows`, `mixed_units_in_series`,
`units_differ_across_regions`, `possible_missing_value_codes`, `series_without_values`, `short_series`, and
mapping errors for missing required fields.

An **error** blocks import. A **warning** or **ambiguity** is shown and, where it changes the data, must be confirmed.
`mixed_units_in_series` (one variable, one region, more than one unit) is an error because no conversion is performed.

## Limits

| Limit | Default | Setting |
| --- | --- | --- |
| Upload size | 25 MB (HTTP 413 above it) | `EARTHTREND_MAX_UPLOAD_MB` |
| Rows per file | 2,000,000 | `EARTHTREND_MAX_ROWS` |
| Datasets held | 25 | `EARTHTREND_MAX_DATASETS` |
| Formats | `.csv` only (HTTP 415 otherwise) | adapter registry |

File names are display metadata only: they are sanitised, and uploads are stored under server-generated IDs, so a
user-supplied name never becomes a path.

## Dataset status

| Status | Meaning |
| --- | --- |
| `synthetic_demo` | The bundled generated file. Read-only; cannot be deleted. |
| `uploaded` | A user-uploaded CSV. Provenance is declared by the uploader and **not verified**. |
| `nasa_verified` | Reserved for the real dataset after it has been profiled and mapped by a maintainer. **No code path produces this status today**, and an upload can never reach it. |

A dataset or selection that contains any `is_synthetic = true` row is labelled synthetic in the UI, in the API
`provenance` block and in CSV exports.

## Stored uploads

Each import writes `<id>.csv` (the normalised canonical table) and `<id>.json` (metadata) to
`backend/data/uploads/`. Files are loaded again on start-up. Delete a dataset in the UI (or `DELETE /api/datasets/{id}`)
to remove both files.

## Exports

`GET /api/observations?format=csv` and the buttons in the UI produce CSV with leading `#` comment lines giving the
dataset, its status, `is_synthetic`, the data source and any notice, followed by the canonical columns (including
`data_source` and `is_synthetic`). Text cells that start with `=`, `+`, `-`, `@`, tab or carriage return are prefixed
with `'` so spreadsheet programs do not execute them.

## Example (synthetic)

Two rows copied from `backend/data/earth_science_trend_demo.csv`:

```csv
date,region,variable,value,unit,data_source,is_synthetic
2000-01-01,Region Alpha,Synthetic Index A,10.9467,synthetic unit A,Synthetic demo data (generated by backend/scripts/generate_demo_data.py),true
2011-06-01,Region Gamma,Synthetic Index A,,synthetic unit A,Synthetic demo data (generated by backend/scripts/generate_demo_data.py),true
```

The second row's value is blank on purpose (the generator leaves a 12-month block empty in that series): it is a
missing observation and stays missing.
