# GPM_3IMERGM v07: verified inspection report

Inspection only. No granule has been downloaded: NASA's data server redirects anonymous requests to Earthdata Login
(HTTP 303), and no credentials are configured. Everything below comes from public NASA CMR records and the GES DISC
product page, queried on 2026-11-13. The raw responses are kept in `backend/data/nasa_inspection/`
(`collection_umm.json`, `granules_umm.json`, `variables_umm.json`).

## Identity (CMR)

| Item | Value |
| --- | --- |
| CMR concept id | `C2723754851-GES_DISC` |
| Short name / version | `GPM_3IMERGM` / `07` (every granule file is labelled `V07B`) |
| Title | GPM IMERG Final Precipitation L3 1 month 0.1 degree x 0.1 degree V07 |
| DOI | `10.5067/GPM/IMERG/3B-MONTH/07` (matches the one you supplied) |
| Provider, level | GES_DISC, processing level 3 |
| Native format | HDF5 (`.HDF5` files; the CMR record says HDF5, not NetCDF) |
| Spatial extent | -180, -90, 180, 90, 0.1° grid (3600 x 1800) |
| Cloud hosted | yes (CMR flag) |
| Use constraints | EOSDIS data-use and citation guidance (GES DISC data guidelines) |

## Temporal coverage: the discrepancy is resolved for this collection

- Collection metadata: 1998-01-01 to 2025-09-30. The GES DISC summary page agrees (1998-01-01 to 2025-10-01).
- A granule query for this exact collection returns **333 granules**, from `...19980101...` to `...20250901...`.
- **333 expected months, 333 present: no missing months, no duplicate months.** Every granule starts on the first of a
  month and ends on the last day of that month.
- So January 1998 to May 2000 is present in this collection. I found no June 2000 start in any current source. It may
  come from an earlier version of the product, but I have not checked that.
- All 333 files are labelled `V07B`. Production times range from 2023-12-13 to 2026-02-01, so the archive has been
  reprocessed in batches. Record the production time with every file.
- Because the archive was extended while this report was written, re-query CMR immediately before any real download.

## Files, sizes, links

- File name pattern: `3B-MO.MS.MRG.3IMERG.YYYYMM01-S000000-E235959.MM.V07B.HDF5`.
- CMR sizes: min 16.4 MB, mean 17.85 MB, max 18.7 MB, **total about 5.94 GB** (the DISC page says 30 MB per file, which
  does not match CMR; I trust the per-granule CMR values and will confirm against real downloads).
- HTTPS link: `https://data.gesdisc.earthdata.nasa.gov/data/GPM_L3/GPM_3IMERGM.07/<YYYY>/<file>`.
  Also an `s3://gesdisc-cumulus-prod-protected/...` direct-access path (needs in-region AWS credentials) and an OPeNDAP
  URL on `opendap.earthdata.nasa.gov`.
- **CMR gives no checksums.** I can compute and record SHA-256 myself, but I cannot verify files against NASA-published
  hashes.

## Variables (CMR UMM-Var records; to be re-checked against a real file)

All are in the `Grid` group. Dimensions as CMR lists them: time (1), lon (3600), lat (1800).

| Variable | Description | Unit | Type | Fill value |
| --- | --- | --- | --- | --- |
| `Grid/precipitation` | Merged satellite-gauge precipitation estimate, Final Run | mm/hr | float32 | -9999.9 |
| `Grid/randomError` | Random error of the above | mm/hr | float32 | -9999.9 |
| `Grid/precipitationQualityIndex` | Quality index, Final Run | equivalent gauges per 2.5° box | float32 | -9999.9 |
| `Grid/probabilityLiquidPrecipitation` | Accumulation-weighted probability of liquid phase | percent | int16 | -9999 |
| `Grid/gaugeRelativeWeighting` | (no description) | percent | int16 | -9999 |
| `Grid/lat`, `Grid/lon` (+ `lat_bnds`, `lon_bnds`) | Cell centres and bounds | degrees_north / degrees_east | float32 | none |
| `Grid/time`, `Grid/time_bnds` | Time and its bounds | seconds since 1980-01-06 00:00:00 UTC | int32 | none |

- The dimension order and the 1800 x 3600 shape come from CMR metadata, not from a file. Check against a real granule.
- CMR lists no scale factor, offset or valid range. Whether the files carry such attributes is unknown until one is
  opened. The quality-index wording says nothing about thresholds; the product documentation PDF linked from CMR
  (`IMERGV06_QI.pdf`) will need reading before any filtering rule is written.
- Whether `precipitation` is a monthly mean rate is not stated in the CMR record. The unit is mm/hr, so it is a rate.
  I will read the file attributes and the ATBD before deriving any accumulation (mean rate x hours in the calendar
  month).

## Scientific cautions found in the metadata

- CMR links `IMERGV06_TRMMera-caveats.pdf`: the 1998 to early 2014 record comes from the TRMM era, with different
  satellite inputs. That matters for trends, so I will read it and surface it in the app's methodology text. Do not
  treat the full 1998-2025 record as one homogeneous instrument period.
- The abstract says high-latitude ocean estimates are adjusted to GPCP, so I will not label high-latitude and tropical
  estimates as equally accurate.
- The CMR collection "landing page" URL points to an unrelated product (`m2t3nvcld`). Do not use it as a source.

## Repository audit (what exists, what must change)

| Area | Today | Needed |
| --- | --- | --- |
| Adapter contract | `DatasetAdapter` in `backend/app/services/ingestion/base.py` takes whole files as in-memory `bytes` | A file-path/chunked interface and a gridded adapter |
| Format registry | `registry.py`, extension to adapter, `.csv` only (others return 415) | Register `.HDF5`/`.nc4`, kept separate from the HTTP upload path |
| Storage | In-memory store (`services/store.py`), uploads under `backend/data/uploads` | On-disk raw files, derived tables and a manifest, with a configurable root |
| Verified status | `nasa_verified` is defined but never produced | Set only after identity, DOI, collection id and file validation have passed |
| Schema | Long format: date, region, variable, value, unit, data_source, is_synthetic | Optional: product, version, granule id, lat/lon, quality, random error, original unit |
| Dependencies | `earthaccess`, `xarray`, `netCDF4`, `h5netcdf`, `h5py`, `dask`: **none installed** | See below |
| Credentials | No Earthdata credentials found (`EARTHDATA_*` unset, no `.netrc`) | Configure locally, never in chat |

## Storage and compute estimate

- Raw files: about 5.94 GB (333 files). **Drive C: has only 4.1 GB free**; D: (167 GB), E: (198 GB) and F: (157 GB) have
  room. The data root must be configurable and should not default to C:.
- A fully expanded long table is 6.48 million cells x 333 months = about 2.16 billion rows per variable, which cannot
  be held in memory or in the existing store. Plan: keep raw HDF5 untouched; derive area-weighted regional and global
  monthly series (small) and expose those to the analysis endpoints; read full-resolution cells only on demand, one
  file at a time.
- Area weighting: cos(latitude) weights, or exact cell areas from `lat_bnds`. Decision for you below.

## Dependencies I would add (each with a use)

- `earthaccess`: Earthdata Login, CMR granule search, resumable authenticated download.
- `xarray` + `h5netcdf` (or `netCDF4`): open the HDF5 granules lazily by group `Grid`.
- `dask`: only if lazy chunked reduction over many files turns out to be needed. Not adding it yet.
- No `rasterio`, `geopandas` or `h5py` (geopandas is already installed for the Earth Explorer).

## Decisions and inputs needed before downloading

1. Approve the plan above.
2. Create an Earthdata Login account and put the credentials in the environment of the shell that runs the backend
   (`EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD`, or an `EARTHDATA_TOKEN`). Never paste them in chat.
3. Choose the data directory (suggest `D:\nasa_data` or similar).
4. Which variables to import first: just `precipitation`, or also `randomError` and `precipitationQualityIndex`?
5. Which regions and which aggregation (global area-weighted, 60°S–60°N, named boxes/countries)? Confirm cos(lat)
   area weighting.
6. Period: the full verified 1998-01 to 2025-09, or start at the GPM-core era (2014) and treat the TRMM era separately?
7. Quality handling: first inspect real values; I will not apply any threshold without your approval and a documented
   justification.
8. Initial sample: download one granule only (about 18 MB) to validate parsing before anything larger?
