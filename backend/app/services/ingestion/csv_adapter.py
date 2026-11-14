"""CSV adapter: inspect, profile, map and validate a delimited text file."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.config import get_settings
from app.errors import AppError
from app.schemas import (
    ColumnMapping,
    ColumnProfile,
    MappingDefaults,
    QualityIssue,
    QualityReport,
    SourceInspection,
    SourceProfile,
)

from .base import DatasetAdapter, DataSource, LoadResult, safe_filename
from .schema import (
    COLUMN_SYNONYMS,
    FALSE_TOKENS,
    MISSING_TOKENS,
    OPTIONAL_FIELDS,
    OPTIONAL_SYNONYMS,
    REQUIRED_FIELDS,
    SENTINEL_VALUES,
    TRUE_TOKENS,
)

SLASH_DATE = re.compile(r"^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}$")
KEY = ["variable", "region", "date"]
UNSPECIFIED_SOURCE = "unspecified (not provided in source)"


@dataclass
class RawTable:
    df: pd.DataFrame  # every cell is a string; nothing has been interpreted yet
    encoding: str
    delimiter: str
    warnings: list[str]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _examples(series: pd.Series, k: int = 5) -> list[str]:
    return [str(x)[:80] for x in pd.unique(series.head(2000))[:k]]


class CSVAdapter(DatasetAdapter):
    format_name = "csv"

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def _decode(self, content: bytes) -> tuple[str, str, list[str]]:
        if b"\x00" in content[:65536]:
            raise AppError(400, "not_a_text_file", "The file looks binary, not like a CSV text file.")
        try:
            return content.decode("utf-8-sig"), "utf-8", []
        except UnicodeDecodeError:
            return (
                content.decode("cp1252", errors="replace"),
                "windows-1252 (fallback)",
                ["The file is not valid UTF-8, so it was decoded as Windows-1252. Check any non-ASCII characters."],
            )

    def _read_raw(self, source: DataSource) -> RawTable:
        if not source.content.strip():
            raise AppError(400, "empty_file", "The file is empty.")
        text, encoding, warnings = self._decode(source.content)
        try:
            delimiter = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
        # Strict structure check first: pandas would silently reinterpret rows with extra fields.
        try:
            reader = csv.reader(io.StringIO(text), delimiter=delimiter)
            width = len(next(reader, []))
            for line_no, row in enumerate(reader, start=2):
                if row and len(row) != width:
                    raise AppError(
                        400,
                        "malformed_csv",
                        f"The file could not be parsed as CSV: row {line_no} has {len(row)} fields but the header has {width}.",
                    )
        except csv.Error as exc:
            raise AppError(400, "malformed_csv", f"The file could not be parsed as CSV: {str(exc)[:150]}") from exc
        try:
            df = pd.read_csv(
                io.StringIO(text),
                sep=delimiter,
                dtype=str,
                keep_default_na=False,
                na_filter=False,
                on_bad_lines="error",
            )
        except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
            first_line = str(exc).splitlines()[0][:200] if str(exc) else "parse error"
            raise AppError(400, "malformed_csv", f"The file could not be parsed as CSV: {first_line}") from exc

        df.columns = [str(c).strip() for c in df.columns]
        if len(df.columns) == 0:
            raise AppError(400, "no_columns", "The file has no header row.")
        if len(df) == 0:
            raise AppError(400, "no_rows", "The file has a header but no data rows.")
        if len(df) > get_settings().max_rows:
            raise AppError(
                413, "too_many_rows", f"The file has more than {get_settings().max_rows:,} rows, which is the configured limit."
            )
        dupes = [c for c in df.columns if re.search(r"\.\d+$", c) and c.rsplit(".", 1)[0] in df.columns]
        if dupes:
            warnings.append(f"Duplicate column names were found and renamed by the parser: {', '.join(dupes)}.")
        return RawTable(df, encoding, delimiter, warnings)

    # ------------------------------------------------------------------
    # Adapter interface
    # ------------------------------------------------------------------
    def inspect(self, source: DataSource) -> SourceInspection:
        raw = self._read_raw(source)
        return self._inspection(source, raw)

    def _inspection(self, source: DataSource, raw: RawTable) -> SourceInspection:
        return SourceInspection(
            filename=safe_filename(source.filename),
            format=self.format_name,
            encoding=raw.encoding,
            delimiter=raw.delimiter,
            n_rows=len(raw.df),
            n_columns=len(raw.df.columns),
            columns=list(raw.df.columns),
            preview=raw.df.head(10).to_dict("records"),
        )

    def profile(self, source: DataSource) -> SourceProfile:
        raw = self._read_raw(source)
        base = self._inspection(source, raw)
        profiles = [self._profile_column(c, raw.df[c]) for c in raw.df.columns]
        mapping, notes = self.suggest_mapping(list(raw.df.columns))
        return SourceProfile(
            **base.model_dump(),
            column_profiles=profiles,
            suggested_mapping=mapping,
            mapping_notes=notes,
            mapping_complete=not self._mapping_errors(mapping, list(raw.df.columns)),
            warnings=raw.warnings,
        )

    def _profile_column(self, name: str, s: pd.Series) -> ColumnProfile:
        stripped = s.str.strip()
        non_empty = stripped[stripped != ""]
        base = dict(name=name, n_non_empty=len(non_empty), n_missing=len(s) - len(non_empty))
        if non_empty.empty:
            return ColumnProfile(**base, inferred_type="empty", n_unique=0, examples=[])
        sample = non_empty.head(5000)
        lower = sample.str.lower()
        if pd.to_numeric(sample, errors="coerce").notna().mean() >= 0.95:
            kind = "numeric"
        elif lower.isin(TRUE_TOKENS | FALSE_TOKENS).all():
            kind = "boolean"
        elif (
            pd.to_datetime(sample, format="ISO8601", errors="coerce", utc=True).notna().mean() >= 0.95
            or sample.str.match(SLASH_DATE).mean() >= 0.95
        ):
            kind = "datetime"
        else:
            kind = "text"
        return ColumnProfile(**base, inferred_type=kind, n_unique=int(non_empty.nunique()), examples=_examples(non_empty, 3))

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------
    def suggest_mapping(self, columns: list[str]) -> tuple[ColumnMapping, list[str]]:
        """Propose a mapping from column names. This is a *suggestion only*; the user must confirm it."""
        by_norm = {_norm(c): c for c in columns}
        used: set[str] = set()
        notes: list[str] = []
        picked: dict[str, str] = {}
        for field, synonyms in COLUMN_SYNONYMS.items():
            for syn in synonyms:
                col = by_norm.get(syn)
                if col and col not in used:
                    picked[field] = col
                    used.add(col)
                    if field == "date" and syn == "year":
                        notes.append("Only a 'year' column was found; it would be read as January 1 of each year (annual data).")
                    break
        optional: dict[str, str] = {}
        for field, synonyms in OPTIONAL_SYNONYMS.items():
            for syn in synonyms:
                col = by_norm.get(syn)
                if col and col not in used:
                    optional[field] = col
                    used.add(col)
                    break
        mapping = ColumnMapping(**picked, optional=optional)
        for field in REQUIRED_FIELDS:
            if getattr(mapping, field) is None:
                notes.append(f"No column was recognised for '{field}'. Map a column, or declare a value explicitly.")
        return mapping, notes

    def _mapping_errors(self, mapping: ColumnMapping, columns: list[str]) -> list[QualityIssue]:
        errors: list[QualityIssue] = []

        def err(code: str, message: str) -> None:
            errors.append(QualityIssue(severity="error", code=code, message=message))

        d = mapping.defaults
        if not mapping.date:
            err("mapping_date", "A date column is required. Dates cannot be declared as a constant.")
        if not mapping.value:
            err("mapping_value", "A value column is required.")
        for field in ("region", "variable", "unit", "data_source"):
            if not getattr(mapping, field) and not (getattr(d, field) or "").strip():
                hint = " Units are never guessed - declare the unit explicitly." if field == "unit" else ""
                err("mapping_" + field, f"'{field}' needs a source column or an explicitly declared value.{hint}")
        if not mapping.is_synthetic and d.is_synthetic is None:
            err(
                "mapping_is_synthetic",
                "State whether the data is synthetic: map an is_synthetic column or declare true/false. "
                "The app does not guess provenance.",
            )
        referenced = [getattr(mapping, f) for f in REQUIRED_FIELDS if getattr(mapping, f)] + list(mapping.optional.values())
        for col in referenced:
            if col not in columns:
                err("mapping_unknown_column", f"Mapped column '{col}' does not exist in the file.")
        return errors

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _parse_dates(self, s: pd.Series, fmt: str | None) -> tuple[pd.Series, bool]:
        """Return (naive datetimes with NaT for failures, ambiguous_flag)."""
        if fmt:
            try:
                return pd.to_datetime(s, format=fmt, errors="coerce"), False
            except (ValueError, TypeError) as exc:
                raise AppError(422, "bad_date_format", f"The date format '{fmt}' is not valid: {exc}") from exc
        parsed = pd.to_datetime(s, format="ISO8601", errors="coerce", utc=True)
        # Second chance only for text that is structurally a date (numeric d/m/y or digits + a month
        # name). Bare numbers or words are never coerced into dates.
        rest = (
            parsed.isna()
            & (s != "")
            & (s.str.match(SLASH_DATE) | s.str.contains(r"[A-Za-z]{3,}.*\d|\d.*[A-Za-z]{3,}", regex=True))
        )
        ambiguous = False
        if rest.any():
            second = pd.to_datetime(s[rest], errors="coerce", utc=True)
            parsed = parsed.copy()
            parsed[rest] = second
            ambiguous = bool(s[rest].str.match(SLASH_DATE).any())
        return parsed.dt.tz_convert(None), ambiguous

    def _label(self, raw: pd.DataFrame, column: str | None, default: str | None) -> pd.Series:
        if column:
            return raw[column].str.strip()
        return pd.Series(default.strip() if default else "", index=raw.index, dtype="object")

    def load(self, source: DataSource, mapping: ColumnMapping) -> LoadResult:
        raw_t = self._read_raw(source)
        raw = raw_t.df
        n_src = len(raw)
        issues: list[QualityIssue] = [
            QualityIssue(severity="warning", code="encoding", message=w) for w in raw_t.warnings
        ]
        ambiguities: list[str] = []

        blocking = self._mapping_errors(mapping, list(raw.columns))
        if blocking:
            return LoadResult(None, self._blocked_report(n_src, blocking + issues, mapping), [])

        # ---- date ----
        d_raw = raw[mapping.date].str.strip()
        dates, ambiguous_dates = self._parse_dates(d_raw, mapping.date_format)
        bad_date = dates.isna()
        if ambiguous_dates:
            ambiguities.append(
                "Some dates look like DD/MM/YYYY or MM/DD/YYYY. Without an explicit date format they were read month-first; "
                "confirm this or supply a date format."
            )

        # ---- value ----
        v_raw = raw[mapping.value].str.strip()
        missing_tok = v_raw.str.lower().isin(MISSING_TOKENS)
        num = pd.to_numeric(v_raw.where(~missing_tok), errors="coerce").astype("float64")
        nonfinite = pd.Series(np.isinf(num.to_numpy()), index=num.index)
        bad_value = (~missing_tok & num.isna()) | nonfinite
        num = num.mask(nonfinite)

        # ---- labels ----
        region = self._label(raw, mapping.region, mapping.defaults.region)
        variable = self._label(raw, mapping.variable, mapping.defaults.variable)
        unit = self._label(raw, mapping.unit, mapping.defaults.unit)
        source_label = self._label(raw, mapping.data_source, mapping.defaults.data_source)
        bad_label = (region == "") | (variable == "") | (unit == "")
        blank_source = source_label == ""
        if mapping.data_source and blank_source.any():
            n_blank = int(blank_source.sum())
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="blank_data_source",
                    message=f"{n_blank} rows have an empty data_source; they were labelled '{UNSPECIFIED_SOURCE}'.",
                    count=n_blank,
                )
            )
            source_label = source_label.mask(blank_source, UNSPECIFIED_SOURCE)

        # ---- is_synthetic ----
        if mapping.is_synthetic:
            t = raw[mapping.is_synthetic].str.strip().str.lower()
            is_true, is_false = t.isin(TRUE_TOKENS), t.isin(FALSE_TOKENS)
            bad_bool = ~(is_true | is_false)
            synthetic = is_true
        else:
            bad_bool = pd.Series(False, index=raw.index)
            synthetic = pd.Series(bool(mapping.defaults.is_synthetic), index=raw.index)

        # ---- assemble ----
        out: dict[str, pd.Series] = {
            "date": dates,
            "region": region,
            "variable": variable,
            "value": num,
            "unit": unit,
            "data_source": source_label,
            "is_synthetic": synthetic.astype(bool),
        }
        for field, col in mapping.optional.items():
            s = raw[col].str.strip()
            if field in ("latitude", "longitude"):
                numeric = pd.to_numeric(s.where(s != ""), errors="coerce").astype("float64")
                limit = 90.0 if field == "latitude" else 180.0
                bad_coord = (s != "") & (numeric.isna() | (numeric.abs() > limit))
                if bad_coord.any():
                    n_bad = int(bad_coord.sum())
                    issues.append(
                        QualityIssue(
                            severity="warning",
                            code=f"invalid_{field}",
                            message=f"{n_bad} {field} values are not numeric or are outside ±{limit:g}; they were left empty.",
                            count=n_bad,
                            examples=_examples(s[bad_coord]),
                        )
                    )
                    numeric = numeric.mask(bad_coord)
                out[field] = numeric
            else:
                out[field] = s.mask(s == "", None)
        df = pd.DataFrame(out)
        # Traceability: nothing is renamed or converted, so originals equal the normalized values.
        if "original_variable" not in df:
            df["original_variable"] = variable
        if "original_unit" not in df:
            df["original_unit"] = unit
        if "source_file" not in df:
            df["source_file"] = safe_filename(source.filename)
        df["original_value"] = df["value"]
        df["transformation_note"] = pd.Series([None] * len(df), index=df.index, dtype="object")

        # ---- row-level validity ----
        n_bad_date, n_bad_value = int(bad_date.sum()), int(bad_value.sum())
        n_bad_label, n_bad_bool = int(bad_label.sum()), int(bad_bool.sum())
        if n_bad_date:
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="invalid_dates",
                    message=f"{n_bad_date} rows have a date that could not be parsed and were excluded.",
                    count=n_bad_date,
                    examples=_examples(d_raw[bad_date]),
                )
            )
        if n_bad_value:
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="invalid_values",
                    message=f"{n_bad_value} rows have a non-numeric value and were excluded (never replaced by zero).",
                    count=n_bad_value,
                    examples=_examples(v_raw[bad_value]),
                )
            )
        if n_bad_label:
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="missing_labels",
                    message=f"{n_bad_label} rows have an empty region, variable or unit and were excluded.",
                    count=n_bad_label,
                )
            )
        if n_bad_bool:
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="invalid_is_synthetic",
                    message=f"{n_bad_bool} rows have an is_synthetic value that is not true/false and were excluded.",
                    count=n_bad_bool,
                    examples=_examples(raw[mapping.is_synthetic][bad_bool]) if mapping.is_synthetic else [],
                )
            )
        keep = ~(bad_date | bad_value | bad_label | bad_bool)
        n_dropped = int((~keep).sum())
        if n_dropped:
            ambiguities.append(f"{n_dropped} source rows would be excluded because of invalid dates, values or labels.")
        df = df[keep].copy()

        # ---- duplicates ----
        df, n_ident, n_conf, dup_issues, dup_ambig = self._resolve_duplicates(df, mapping.duplicate_policy)
        issues.extend(dup_issues)
        ambiguities.extend(dup_ambig)

        df = df.sort_values(KEY, kind="stable").reset_index(drop=True)
        issues.extend(self.validate(df))

        n_missing = int(df["value"].isna().sum()) if len(df) else 0
        if n_missing:
            issues.append(
                QualityIssue(
                    severity="info",
                    code="missing_values",
                    message=f"{n_missing} rows have no value. They are kept as missing and are never filled or set to zero.",
                    count=n_missing,
                )
            )
        can_import = not any(i.severity == "error" for i in issues) and len(df) > 0
        report = QualityReport(
            n_source_rows=n_src,
            n_rows_retained=len(df),
            n_rows_dropped=n_dropped,
            n_invalid_dates=n_bad_date,
            n_invalid_values=n_bad_value,
            n_invalid_labels=n_bad_label + n_bad_bool,
            n_missing_values=n_missing,
            n_duplicate_identical=n_ident,
            n_duplicate_conflicting=n_conf,
            duplicate_policy=mapping.duplicate_policy,
            n_series=int(df.groupby(["variable", "region"]).ngroups) if len(df) else 0,
            variables=sorted(df["variable"].unique().tolist()) if len(df) else [],
            regions=sorted(df["region"].unique().tolist()) if len(df) else [],
            units_by_variable={k: sorted(v) for k, v in df.groupby("variable")["unit"].unique().items()} if len(df) else {},
            date_min=df["date"].min().date() if len(df) else None,
            date_max=df["date"].max().date() if len(df) else None,
            issues=issues,
            ambiguities=ambiguities,
            can_import=can_import,
            requires_confirmation=bool(ambiguities),
        )
        return LoadResult(df if can_import else None, report, [])

    # ------------------------------------------------------------------
    def _resolve_duplicates(
        self, df: pd.DataFrame, policy: str
    ) -> tuple[pd.DataFrame, int, int, list[QualityIssue], list[str]]:
        issues: list[QualityIssue] = []
        ambiguities: list[str] = []
        if not df.duplicated(KEY).any():
            return df, 0, 0, issues, ambiguities

        before = len(df)
        df = df.drop_duplicates(KEY + ["value", "unit"], keep="first")
        n_identical = before - len(df)
        if n_identical:
            issues.append(
                QualityIssue(
                    severity="info",
                    code="duplicates_identical",
                    message=f"{n_identical} exact duplicate rows (same variable, region, date, value and unit) were removed.",
                    count=n_identical,
                )
            )

        dup_mask = df.duplicated(KEY, keep=False)
        if not dup_mask.any():
            return df, n_identical, 0, issues, ambiguities

        sub = df[dup_mask]
        groups = sub.groupby(KEY, sort=False)
        n_conflicting = int((groups.size() - 1).sum())
        example_keys = [" | ".join(str(x.date()) if hasattr(x, "date") else str(x) for x in k) for k in list(groups.groups)[:5]]

        if (groups["unit"].nunique() > 1).any():
            issues.append(
                QualityIssue(
                    severity="error",
                    code="duplicate_unit_conflict",
                    message="Rows that share a variable, region and date also disagree on the unit. No automatic merge is possible.",
                    count=n_conflicting,
                    examples=example_keys,
                )
            )
            return df, n_identical, n_conflicting, issues, ambiguities

        if policy == "error":
            issues.append(
                QualityIssue(
                    severity="error",
                    code="duplicate_conflict",
                    message=(
                        f"{n_conflicting} extra rows share a variable, region and date with a different value. "
                        "Choose a duplicate policy (mean, first or last) to resolve them explicitly."
                    ),
                    count=n_conflicting,
                    examples=example_keys,
                )
            )
            return df, n_identical, n_conflicting, issues, ambiguities

        if policy in ("first", "last"):
            df = df.drop_duplicates(KEY, keep=policy)
        else:  # mean
            sizes = df.groupby(KEY, sort=False)["value"].transform("size")
            others = [c for c in df.columns if c not in KEY + ["value"]]
            df = df.assign(_n=sizes)
            agg = df.groupby(KEY, sort=False, as_index=False).agg({"value": "mean", "_n": "first", **{c: "first" for c in others}})
            agg["transformation_note"] = [
                f"mean of {int(n)} rows with duplicate timestamps" if n > 1 else None for n in agg["_n"]
            ]
            df = agg.drop(columns="_n")[[c for c in df.columns if c != "_n"]]
        issues.append(
            QualityIssue(
                severity="warning",
                code="duplicates_resolved",
                message=f"{n_conflicting} rows with conflicting duplicate timestamps were resolved with policy '{policy}'.",
                count=n_conflicting,
                examples=example_keys,
            )
        )
        ambiguities.append(f"{n_conflicting} conflicting duplicate rows were resolved with policy '{policy}'.")
        return df, n_identical, n_conflicting, issues, ambiguities

    # ------------------------------------------------------------------
    def validate(self, data: pd.DataFrame) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        if data.empty:
            return [QualityIssue(severity="error", code="no_valid_rows", message="No valid rows remain after validation.")]

        per_series_units = data.groupby(["variable", "region"], sort=False)["unit"].nunique()
        mixed = per_series_units[per_series_units > 1]
        if len(mixed):
            issues.append(
                QualityIssue(
                    severity="error",
                    code="mixed_units_in_series",
                    message=(
                        "Some variable/region series contain more than one unit. No unit conversion is performed, "
                        "so a single trend cannot be computed. Fix the units in the source or map them separately."
                    ),
                    count=len(mixed),
                    examples=[f"{v} / {r}" for v, r in list(mixed.index)[:5]],
                )
            )

        per_var_units = data.groupby("variable", sort=False)["unit"].nunique()
        diff = per_var_units[per_var_units > 1]
        if len(diff):
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="units_differ_across_regions",
                    message="The same variable is reported in different units for different regions. "
                    "Regional comparison will be blocked for these variables (no automatic conversion).",
                    count=len(diff),
                    examples=list(diff.index[:5]),
                )
            )

        for col in ("region", "variable"):
            labels = data[[col]].drop_duplicates()
            norm = labels[col].str.strip().str.casefold()
            collide = labels.groupby(norm)[col].nunique()
            collide = collide[collide > 1]
            if len(collide):
                issues.append(
                    QualityIssue(
                        severity="warning",
                        code=f"{col}_label_variants",
                        message=f"Some {col} labels differ only by case or spacing. They are NOT merged automatically.",
                        count=len(collide),
                        examples=list(collide.index[:5]),
                    )
                )

        vals = data["value"].dropna().to_numpy()
        if vals.size and np.isin(vals, SENTINEL_VALUES).any():
            n_sent = int(np.isin(vals, SENTINEL_VALUES).sum())
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="possible_missing_value_codes",
                    message=(
                        f"{n_sent} values equal common missing-value codes (e.g. -9999, -999, 9999). "
                        "They were NOT treated as missing. If they are fill values, clean the file and re-upload."
                    ),
                    count=n_sent,
                )
            )

        valid_counts = data.groupby(["variable", "region"], sort=False)["value"].agg(lambda s: int(s.notna().sum()))
        empty = valid_counts[valid_counts == 0]
        if len(empty):
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="series_without_values",
                    message="Some series contain no numeric values at all.",
                    count=len(empty),
                    examples=[f"{v} / {r}" for v, r in list(empty.index)[:5]],
                )
            )
        short = valid_counts[(valid_counts > 0) & (valid_counts < 10)]
        if len(short):
            issues.append(
                QualityIssue(
                    severity="info",
                    code="short_series",
                    message="Some series have fewer than 10 valid observations; trend tests will be unavailable or unreliable for them.",
                    count=len(short),
                )
            )
        return issues

    # ------------------------------------------------------------------
    def _blocked_report(self, n_src: int, issues: list[QualityIssue], mapping: ColumnMapping) -> QualityReport:
        return QualityReport(
            n_source_rows=n_src,
            n_rows_retained=0,
            n_rows_dropped=0,
            n_invalid_dates=0,
            n_invalid_values=0,
            n_invalid_labels=0,
            n_missing_values=0,
            n_duplicate_identical=0,
            n_duplicate_conflicting=0,
            duplicate_policy=mapping.duplicate_policy,
            n_series=0,
            variables=[],
            regions=[],
            units_by_variable={},
            date_min=None,
            date_max=None,
            issues=issues,
            ambiguities=[],
            can_import=False,
            requires_confirmation=False,
        )


def identity_mapping() -> ColumnMapping:
    """Mapping for files that already use the canonical column names."""
    return ColumnMapping(
        date="date",
        region="region",
        variable="variable",
        value="value",
        unit="unit",
        data_source="data_source",
        is_synthetic="is_synthetic",
        defaults=MappingDefaults(),
    )


__all__ = ["CSVAdapter", "identity_mapping", "OPTIONAL_FIELDS"]
