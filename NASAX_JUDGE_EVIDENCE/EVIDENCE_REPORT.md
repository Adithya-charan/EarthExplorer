# NASAX evidence report

Generated 2026-11-15T04:09:43+00:00.

## What is official
- 5 dataset(s) derived from official files: Bellandur and east Bengaluru (GHSL built-up), Bellandur Lake (JRC surface water), Hyderabad metropolitan area (GHSL built-up), Hyderabad lakes (JRC surface water), Sundarbans (ESA WorldCover 2021). Label in the app: **Satellite Observations**.
- Official sources registered: 17 (9 VERIFIED_DOWNLOADED, 3 VERIFIED_METADATA_ONLY, 5 ACCESS_REQUIRES_AUTHENTICATION). Checksums are in `02_OFFICIAL_SOURCES/source_registry.json`.
- Boundaries: geoBoundaries ADM1 and ADM2 (36 states and union territories, 735 districts) plus lake outlines derived from JRC water occurrence and the Sundarbans mangrove from ESA WorldCover.

## What is illustrative
- 4 generated dataset(s): Bellandur Lake, Bengaluru (illustrative), Dhauliganga catchment, Uttarakhand (illustrative), Hyderabad metropolitan area (illustrative), Sundarbans, West Bengal (illustrative). Label in the app: **Illustrative Dataset**. They are demonstrations calibrated to real totals where official data exist, not satellite imagery. The Himalayas region is entirely illustrative.
- City, locality and landmark outlines are approximate areas (marked as such); they are not authoritative boundaries.

## What was not obtained
- No Landsat, Sentinel-2 or Bhuvan scenes were downloaded. Sources needing an account are recorded as ACCESS_REQUIRES_AUTHENTICATION; portal-only sources as VERIFIED_METADATA_ONLY.
- WorldCover 2021 is a single date, so it supports no change analysis (the app says so).

## Validation
521 automated checks: 521 passed, 0 warnings, 0 failed (`06_METHODOLOGY/validation_report.pdf`).

## How to reproduce
```
python scripts/generate_india_atlas.py --all
python scripts/generate_previews.py
python scripts/validate_datasets.py
python scripts/generate_evidence.py
```
