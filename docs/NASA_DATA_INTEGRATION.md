# Integrating the NASA Earth science dataset

**Current state: the NASA dataset has not been supplied, so no NASA data is integrated.** The app runs on a
clearly labelled **synthetic** demo CSV and on user-uploaded CSV files. Nothing in the code, the UI or the
documentation describes a NASA mission, instrument, product, unit, grid or coordinate system, because none of those
facts are known. This document lists what is needed from the dataset owner, the steps to add it, and exactly which
files change.

> Do not describe any output as "NASA data" or "validated" until every step in section 3 is done and a domain
> expert has reviewed the results (section 4).

---

## 1. Information needed before any code is written

Please provide the following. Anything that cannot be provided should be said so explicitly; the app will then
report that field as absent rather than guess.

### 1.1 The file(s)

- [ ] The actual file(s), or a representative sample (a few time steps and a few regions is enough to start).
- [ ] File format and extension (CSV, NetCDF `.nc`, HDF5 `.h5` / HDF4 `.hdf`, GeoTIFF, other) and how many files make up
      the dataset (one file, one per year, one per granule, ...).
- [ ] Approximate total size and the number of time steps, variables and locations/cells.
- [ ] If the data are in a **tabular** form already: the column meanings, in particular whether it is "long" (one row per
      observation) or "wide" (one column per variable or per region).

### 1.2 Provenance and licence

- [ ] Product / dataset short name and **version**, processing **level**, and **DOI** or landing page.
- [ ] Mission(s) and instrument(s) (as stated by the provider; do not infer from the file name).
- [ ] Recommended **citation** and **licence / data-use terms** (needed before the data are shown or redistributed).
- [ ] Who verified the file is the genuine product, and how (checksum, download URL, date retrieved).

### 1.3 Variables

For **each** variable that should be analysed:

- [ ] Name in the file, human-readable name, and definition.
- [ ] **Unit** exactly as the provider states it (and whether any conversion is intended, and if so the exact
      documented formula).
- [ ] **Fill / missing-value codes** (for example a numeric sentinel in the attributes) and any valid range.
- [ ] **Scale factor / offset**, if the stored values are packed integers.
- [ ] **Quality flags**: which field, what each code means, and which codes should be excluded from trend analysis.
- [ ] Whether the variable is already an **anomaly** (relative to which baseline period?), a **mean**, a **sum**, or a
      **count**.

### 1.4 Time

- [ ] Name of the time coordinate and its **units and calendar** (for example "days since ...", Gregorian, 360-day).
- [ ] Temporal resolution (daily / 8-day / monthly / annual) and whether time stamps mark the start, middle or end of the
      period.
- [ ] Whether values are composites or averages over a window, and how gaps are represented.
- [ ] The documented known discontinuities (instrument or algorithm changes, reprocessing) that matter for trends.

### 1.5 Space and regions

- [ ] Whether the data are **gridded**, swath, station/point, or already regional.
- [ ] Coordinate variables (names, units), **grid resolution**, and the **coordinate reference system**.
- [ ] Whether latitude/longitude refer to a point, a cell centre or a regional centroid.
- [ ] **How the "regions" in the analysis are defined.** The app uses a text `region` label. If regions have to be built
      from a grid, the owner must supply or approve the region boundaries/masks and the aggregation rule (plain mean?
      **area-weighted** mean? median?). The app never invents this.

### 1.6 Expected results (for testing)

- [ ] Any published or independently computed trend values for this product (series, period, slope, unit, method). They
      are used as golden values in tests, and they are the only honest way to check the pipeline.
- [ ] Which statistical choices are expected or required by the domain (for example a particular seasonal method,
      deseasonalisation, baseline, significance level).

---

## 2. What exists today

| Piece | Where | Status |
| --- | --- | --- |
| Canonical long-format schema | `backend/app/services/ingestion/schema.py`, `backend/app/schemas.py`, [DATA_SCHEMA.md](DATA_SCHEMA.md) | Implemented |
| `DatasetAdapter` contract (`inspect`, `profile`, `load`, `validate`) | `backend/app/services/ingestion/base.py` | Implemented |
| CSV adapter (long format only) | `backend/app/services/ingestion/csv_adapter.py` | Implemented, tested |
| Adapter registry (extension -> adapter) | `backend/app/services/ingestion/registry.py` | Only `.csv`; any other extension returns HTTP 415 |
| NetCDF / HDF / GeoTIFF adapters | - | **Not implemented.** The app does not claim to read these formats. |
| Dataset status `nasa_verified` | `backend/app/schemas.py`, `backend/app/services/store.py` | Defined, **never produced**. Uploads can only be `uploaded`. |
| Spatial awareness | `backend/app/services/metadata.py`, `SpatialPanel` | A coordinate scatter appears only when real `latitude`/`longitude` columns exist. No basemap, no spatial statistics. |

---

## 3. Procedure once the data and the information in section 1 are available

1. **Inspect the file with the provider's own tools first** (for example `ncdump -h`, `h5dump -H`, `gdalinfo`, or the
   provider's documentation) and write down the variables, dimensions, units, attributes and fill values. Compare
   them with the information supplied in section 1. Resolve every discrepancy with the data owner before coding.
2. **Decide the canonical mapping on paper.** For each canonical column in [DATA_SCHEMA.md](DATA_SCHEMA.md) write
   where its value comes from (a variable, an attribute, a coordinate, a declared constant). Required columns that
   cannot be filled from the file must be declared explicitly, not guessed.
3. **Write a new adapter** in `backend/app/services/ingestion/` (for example `netcdf_adapter.py`) that subclasses
   `DatasetAdapter` and implements `inspect`, `profile`, `load` and `validate`.
   - Add the format library to `backend/requirements.txt` (for example `xarray` and `netCDF4` or `h5netcdf` for
     NetCDF, `h5py` for HDF5, `rasterio` for GeoTIFF) and re-run the tests.
   - Convert documented **fill values to missing** (never to `0`), apply any documented scale factor / offset, and
     apply the documented quality-flag exclusions. Report how many values were affected in the `QualityReport`.
   - Decode the time coordinate with the documented units and calendar; never assume a calendar.
   - If the data are gridded and regions must be built, implement the **explicit, documented** aggregation that the
     owner approved, and record it in `transformation_note`. Keep `original_value` / `original_unit` wherever a
     value or unit is changed.
   - Do **not** convert units unless the provider documents the exact conversion and the owner asks for it; if so,
     set `original_unit` and describe the formula in `transformation_note`.
   - Large grids: read lazily and aggregate before building the long table. The in-memory store is sized for the
     limits in [DATA_SCHEMA.md](DATA_SCHEMA.md); a full-resolution global grid will not fit.
4. **Register the adapter** in `backend/app/services/ingestion/registry.py` (`ADAPTERS`), and update the 415 message
   there so it names the formats that are really supported.
5. **Add a maintainer-only registration path for the verified dataset.** Today `classify_status(is_demo,
   verified_nasa=False)` in `backend/app/services/store.py` can produce `nasa_verified`, but nothing passes
   `verified_nasa=True`, and start-up (`_load_uploads`) always labels stored files `uploaded`. Add a deliberate,
   non-public mechanism (for example a configuration entry or a script that the maintainer runs after step 1),
   and make sure that:
   - an HTTP upload can never obtain this status;
   - the record carries the real `data_source`, DOI/citation and licence in its metadata and in every export header;
   - `is_synthetic` is `false` only for rows that really come from the product.
6. **Replace the placeholder wording** that currently says the NASA dataset is pending (see section 5), and make the
   remaining text come from the API instead of being hard-coded.
7. **Write tests with golden values** (section 1.6): a small fixture file in the real format, expected canonical rows,
   expected quality-report counts, and published or independently computed trend results. Keep a test that uploads
   cannot become `nasa_verified`.
8. **Run everything**: `python -m pytest` in `backend/`, then `npx tsc --noEmit`, `npx eslint`, `npx vitest run` and
   `npm run build` in `frontend/`. Report the actual results.
9. **Get a domain-expert review** (section 4) before the app is described as validated.

---

## 4. Review before claiming validation

The statistical methods are implemented and unit-tested against reference libraries, but have **not** been validated on
any real product ([METHODOLOGY.md](METHODOLOGY.md)). Before presenting results from the real dataset, a domain expert
should confirm at least:

- that the variable definitions, units, fill-value and quality-flag handling are right;
- that regional aggregation (and any area weighting) is scientifically appropriate;
- that the time handling (calendar, period, composites) is right and that known instrument/algorithm discontinuities
  have been considered;
- that the headline statistics and the wording of the explanations are appropriate for the product, and that the
  seasonal and autocorrelation choices fit the data's behaviour.

---

## 5. Files and modules that will change

### Backend

| File | Why it changes |
| --- | --- |
| `backend/app/services/ingestion/<new>_adapter.py` | **New.** The adapter for the real format. |
| `backend/app/services/ingestion/registry.py` | Register the adapter; update the 415 message. |
| `backend/app/services/ingestion/base.py` | Docstring only (mentions that only CSV exists); the contract may need an extension if the real format needs extra inputs. |
| `backend/app/services/ingestion/schema.py` | Only if new optional canonical fields are needed (add them there and in `backend/app/schemas.py`). |
| `backend/app/services/store.py` | Maintainer registration path for a `nasa_verified` record; start-up loading; `NASA_PENDING` / `NASA_INTEGRATED` messages; `DatasetRecord.notice` (currently returns no notice for `nasa_verified`); `classify_status`. |
| `backend/app/services/provenance.py` | Notice, citation and licence for `nasa_verified` records (it currently handles `synthetic_demo` and `uploaded`). |
| `backend/app/services/metadata.py` | CSV export header (add citation/licence); spatial description if the real grid changes what is known. |
| `backend/app/routers/datasets.py` | Uses `NASA_PENDING` / `NASA_INTEGRATED` for `nasa_dataset` in `GET /api/datasets`. |
| `backend/app/schemas.py` | Only if new response fields (citation, licence, DOI) are added. |
| `backend/app/services/methodology.py` (about line 117) | Text "Until the NASA dataset is supplied ..." must be reworded. |
| `backend/app/main.py` (docstring, about line 22) | Wording. |
| `backend/requirements.txt` | Format library (`xarray`, `netCDF4`/`h5netcdf`, `h5py`, `rasterio`, ...). |
| `backend/tests/` | New adapter tests with golden values; keep the "uploads cannot be `nasa_verified`" test. |
| `backend/.env.example` and `backend/app/config.py` | Only if the registration path is configured by environment settings. |

### Frontend

| File | Why it changes |
| --- | --- |
| `frontend/src/components/shell/Sidebar.tsx` | Already reads `nasa_dataset.integrated` from the API; confirm the wording. |
| `frontend/src/views/OverviewView.tsx`, `UploadView.tsx`, `MethodologyView.tsx` | Copy that says no NASA data is integrated or that only CSV is accepted. |
| `frontend/src/components/charts/TimeSeriesChart.tsx`, `RegionalComparisonChart.tsx` | The `sourceLabel` fallback (`"NASA dataset"`) should show the real product name/version once known. |
| `frontend/src/components/data/DatasetStatus.tsx`, `frontend/src/lib/format.ts` | Labels for `nasa_verified` (already defined; add citation/licence if shown). |
| `frontend/src/lib/types.ts` | Only if new API fields are added. |
| `frontend/src/components/data/SpatialPanel.tsx` | Only if a real map/basemap is wanted; currently a coordinate scatter. |
| `frontend/src/test/fixtures.ts` and view tests | Add fixtures/tests for a `nasa_verified` dataset. |

### Documentation

`README.md` (status section, supported formats), [DATA_SCHEMA.md](DATA_SCHEMA.md) (new optional fields, statuses),
[METHODOLOGY.md](METHODOLOGY.md) (anything specific to the product, plus the validation status), and this file (turn
the checklist in section 1 into a record of what was supplied).

---

## 6. What the app will keep doing automatically

These behaviours are deliberate and should be kept when the real dataset is added:

- every response, chart and export carries its data-source label;
- missing values stay missing; nothing is interpolated, gap-filled or converted to `0`;
- units are never guessed or converted silently;
- a dataset is labelled synthetic if any row is flagged `is_synthetic`;
- explanations are rule-based, make no causal claims and never say "no trend exists".
