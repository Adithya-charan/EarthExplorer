"""Canonical data model definition.

Every dataset, regardless of its source format, is normalized to this schema
before analysis. See ``docs/DATA_SCHEMA.md`` for the human-readable version.
"""

from __future__ import annotations

from app.schemas import OPTIONAL_CANONICAL_FIELDS

REQUIRED_FIELDS: tuple[str, ...] = (
    "date",
    "region",
    "variable",
    "value",
    "unit",
    "data_source",
    "is_synthetic",
)

OPTIONAL_FIELDS: tuple[str, ...] = OPTIONAL_CANONICAL_FIELDS

# Traceability columns: the value exactly as read from the source and an explicit
# note for any value-changing step (unit conversion, averaging of duplicate
# timestamps). No unit conversion is ever performed automatically, so the note is
# empty unless a duplicate-resolution policy altered the value.
TRACE_FIELDS: tuple[str, ...] = ("original_value", "transformation_note")

# Tokens (case-insensitive) that mean "no value recorded". Anything else that is
# not a finite number is reported as an invalid value, never silently zeroed.
MISSING_TOKENS: frozenset[str] = frozenset({"", "na", "n/a", "nan", "null", "none", "-", "--"})

TRUE_TOKENS: frozenset[str] = frozenset({"true", "t", "yes", "y", "1"})
FALSE_TOKENS: frozenset[str] = frozenset({"false", "f", "no", "n", "0"})

# Values commonly used as missing-value codes. They are NOT treated as missing
# automatically (that would be a silent guess); the quality report warns instead.
SENTINEL_VALUES: tuple[float, ...] = (-9999.0, -999.0, 9999.0, 99999.0, -99999.0, 999.9, -999.9, 1e20, 1e30, 9.96921e36)

# Synonyms used ONLY to propose a mapping for the user to review.
COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": ("date", "datetime", "timestamp", "time", "obs_date", "observation_date", "year"),
    "region": ("region", "area", "location", "site", "station", "zone", "basin"),
    "variable": ("variable", "var", "parameter", "measure", "metric", "indicator", "quantity"),
    "value": ("value", "val", "measurement", "observation", "obs", "reading", "result"),
    "unit": ("unit", "units", "uom"),
    "data_source": ("data_source", "source", "provider", "origin"),
    "is_synthetic": ("is_synthetic", "synthetic", "simulated"),
}

OPTIONAL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "dataset_id": ("dataset_id",),
    "dataset_name": ("dataset_name", "dataset"),
    "mission": ("mission",),
    "instrument": ("instrument", "sensor"),
    "product": ("product",),
    "quality_flag": ("quality_flag", "qa", "qc", "flag", "quality"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon", "lng", "long"),
    "spatial_geometry": ("spatial_geometry", "geometry", "wkt"),
    "spatial_resolution": ("spatial_resolution",),
    "temporal_resolution": ("temporal_resolution",),
    "original_variable": ("original_variable",),
    "original_unit": ("original_unit",),
    "source_file": ("source_file",),
}

CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(text: object) -> object:
    """Neutralize spreadsheet-formula injection in exported *text* cells."""
    if isinstance(text, str) and text.startswith(CSV_FORMULA_PREFIXES):
        return "'" + text
    return text
