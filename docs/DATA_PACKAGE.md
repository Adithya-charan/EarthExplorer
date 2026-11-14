# Packaged CSV datasets: observed global vs synthetic regional demo

The repository ships a `datasets/` folder (see `datasets/README_DATA_PROVENANCE.txt`). Its files belong to **two
different data classes**, which the app loads as two separate, read-only datasets and never mixes.

| | **Observed global data** | **Synthetic regional demo data** |
| --- | --- | --- |
| Dataset id | `gpm-imerg-global-observed` | `gpm-imerg-regional-synthetic-demo` |
| Status | `observed_global` | `synthetic_regional_demo` |
| Files | `datasets/observed_global/GPM_IMERG_V07_Global_Monthly_Precipitation_1998-2025.csv`, `…_RandomError_1998-2025.csv` | `datasets/synthetic_regional_demo/GPM_IMERG_V07_SYNTHETIC_DEMO_{India,Amazon,Central_Africa}_Monthly_1998-2025.csv` |
| Origin | NASA GES DISC GPM IMERG V07 (`GPM_3IMERGM_07`), Giovanni area-averaged time series | Made up for software testing |
| Spatial scope | One global area average (bounding box −179.95, −89.95, 179.95, 89.95). **Not regional.** | Region *labels* only, no geography |
| Variables | `precipitation`, `random_error`, both mm/hr | `precipitation`, `random_error`, labelled mm/hr |
| `is_synthetic` | `false` | `true` on every row |
| Regional analysis | **Disabled** (one global region; compare API cannot be used) | Allowed, as a demo |

Anything in `datasets/supporting/` is **not loaded**: those files are not part of the two classes above.

## Rules the app enforces

* The global series are never relabelled as India, Amazon or Central Africa; no map pin or regional conclusion is
  derived from them.
* The two classes are separate datasets, so no request can rank or compare across them. The dataset selector groups
  them separately; the observed set is the default.
* The synthetic set carries `SYNTHETIC DEMO — NOT NASA OBSERVATIONS` in its dataset name, `data_source`, API
  `provenance.notice`, the page banner, the header strip, the info card, the chart tag, tooltips, captions, and the
  header of every CSV export (server and client). Loading refuses any regional file whose `dataset_type` is not
  `SYNTHETIC_DEMO_NOT_NASA_OBSERVATION`.
* If a file is missing or fails validation, that record is not created, the reason is returned in
  `GET /api/datasets` → `package_issues` and shown on the Overview, and **nothing is substituted**.
* Precipitation stays a rate in **mm/hr**; nothing is converted or called a monthly accumulation.
* Random error is shown next to the values but is not a confidence interval and is never used as a weight. For the
  global file it is Giovanni's area average of per-cell random error, which is not the uncertainty of the area mean.

## Parsing and validation

`backend/app/services/ingestion/package_adapters.py`

* **Giovanni CSV**: `Key:,value` metadata block, a blank line, then `time, <variable>`. The unit is not in the file; it
  is looked up from the column name (`precipitation`, `randomError` → mm/hr) and the source of that unit is recorded. An
  unknown column is rejected (no guessed unit); a declared unit other than mm/hr is rejected. The declared fill
  value (−9999.9) becomes an explicit missing value and is counted. Checks: parseable dates, finite numbers,
  duplicate dates (error), unsorted rows (sorted, reported), non-month-start dates, missing months (reported, never
  filled), negative rates, and the requested end date versus the last available month (the export asked for up to
  2025-12-31 but the data end in 2025-09; nothing is added). The `utm_source=chatgpt.com` in the file's reproduction URL
  is left untouched in the source file.
* **Synthetic regional CSV**: required columns, exactly one region per file, the synthetic label on every row, finite
  non-negative numbers, dates as above. The `uncertainty_lower/upper_1sigma` columns are not loaded.
* `package_loader.py` checks that the random-error dates equal the precipitation dates exactly before loading the
  random-error series; otherwise it is left out and the mismatch is reported.

Validation results for the supplied files (333 monthly rows each, 1998-01 to 2025-09): no duplicates, no missing
months, no fill values, no invalid numbers; global precipitation 0.1027–0.1239 mm/hr, global random error
0.0245–0.0296 mm/hr; random-error dates identical to the precipitation dates.

## Calculations (all at request time from the loaded rows)

`POST /api/analyze` and `/api/compare` already provide OLS (with HAC), Mann–Kendall (original, seasonal and
Hamed–Rao), Sen's slope, confidence intervals and Benjamini–Hochberg adjustment (see `METHODOLOGY.md`).
`GET /api/diagnostics?dataset_id=&variable=&region=` adds:

* **Missingness**: expected vs present vs valid months, absent months, longest gap, coverage.
* **Month-of-year summary**: n, mean, median, standard deviation, min and max per calendar month.
* **Autocorrelation**: lag-1, Durbin–Watson and Ljung–Box on OLS-detrended residuals, and again after removing
  month-of-year means; a warning when months are missing (equal spacing is then approximate).
* **Random error** (precipitation only): date alignment, mean error, mean value and mean error-to-value ratio, with the
  caveat above.

Assumptions: observations are treated as equally spaced; month-of-year statistics describe the sample, not a
climatology with uncertainty; the long record spans the TRMM-to-GPM transition, so a trend can partly reflect changes
in the satellite constellation. No machine-learning model is trained or used.

## Tests

`backend/tests/test_package_datasets.py` (parsers, loader, separation, labelling, exports, diagnostics) and
`frontend/src/views/Package.test.tsx` (selector groups, info card, banners, disabled regional state, diagnostics).
Inline CSV strings in those tests are small hand-checkable **test fixtures**; they are never loaded by the app.
