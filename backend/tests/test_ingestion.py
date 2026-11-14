"""CSV parsing, mapping and validation."""

from __future__ import annotations

import numpy as np
import pytest

from app.errors import AppError
from app.schemas import ColumnMapping, MappingDefaults
from app.services.ingestion.base import DataSource, safe_filename
from app.services.ingestion.csv_adapter import CSVAdapter, identity_mapping
from app.services.ingestion.registry import adapter_for
from app.services.ingestion.schema import csv_safe

HEADER = "date,region,variable,value,unit,data_source,is_synthetic\n"
adapter = CSVAdapter()


def src(*lines: str, header: str = HEADER, name: str = "t.csv") -> DataSource:
    return DataSource(name, (header + "\n".join(lines) + "\n").encode("utf-8"))


def codes(report) -> set[str]:
    return {i.code for i in report.issues}


def good_rows(n: int = 12) -> list[str]:
    return [f"2020-{m:02d}-01,R1,V1,{m}.5,u,src,false" for m in range(1, n + 1)]


# ------------------------------------------------------------------ happy path
def test_valid_csv_loads_with_canonical_columns_and_traceability():
    res = adapter.load(src(*good_rows()), identity_mapping())
    assert res.report.can_import and res.data is not None
    df = res.data
    assert len(df) == 12 and res.report.n_series == 1
    for col in ("date", "region", "variable", "value", "unit", "data_source", "is_synthetic"):
        assert col in df.columns
    assert df["is_synthetic"].dtype == bool and not df["is_synthetic"].any()
    assert (df["original_value"] == df["value"]).all()  # no conversion is ever applied
    assert df["transformation_note"].isna().all()
    assert (df["original_unit"] == df["unit"]).all()
    assert df["source_file"].iloc[0] == "t.csv"
    assert not res.report.requires_confirmation


def test_optional_columns_are_preserved_when_mapped():
    header = HEADER.strip() + ",lat,lon,qa\n"
    s = src("2020-01-01,R1,V1,1,u,src,false,45.5,-120.25,good", "2020-02-01,R1,V1,2,u,src,false,,,bad", header=header)
    mapping = identity_mapping().model_copy(update={"optional": {"latitude": "lat", "longitude": "lon", "quality_flag": "qa"}})
    res = adapter.load(s, mapping)
    df = res.data
    assert df is not None
    assert df["latitude"].iloc[0] == 45.5 and df["longitude"].iloc[0] == -120.25
    assert np.isnan(df["latitude"].iloc[1])
    assert list(df["quality_flag"]) == ["good", "bad"]


def test_out_of_range_coordinates_are_reported_not_kept():
    header = HEADER.strip() + ",lat,lon\n"
    s = src("2020-01-01,R1,V1,1,u,src,false,95,10", "2020-02-01,R1,V1,2,u,src,false,10,10", header=header)
    mapping = identity_mapping().model_copy(update={"optional": {"latitude": "lat", "longitude": "lon"}})
    res = adapter.load(s, mapping)
    assert "invalid_latitude" in codes(res.report)
    assert np.isnan(res.data["latitude"].iloc[0])


# ------------------------------------------------------------ missing columns
def test_missing_required_columns_produce_clear_blocking_errors():
    s = DataSource("x.csv", b"date,value\n2020-01-01,1\n2020-02-01,2\n")
    profile = adapter.profile(s)
    assert not profile.mapping_complete
    res = adapter.load(s, profile.suggested_mapping)
    assert res.data is None and not res.report.can_import
    assert {"mapping_region", "mapping_variable", "mapping_unit", "mapping_data_source", "mapping_is_synthetic"} <= codes(res.report)
    assert all(i.severity == "error" for i in res.report.issues)


def test_units_are_never_guessed():
    s = DataSource("x.csv", b"date,region,variable,value,data_source,is_synthetic\n2020-01-01,R,V,1,s,false\n")
    mapping = ColumnMapping(date="date", region="region", variable="variable", value="value", data_source="data_source", is_synthetic="is_synthetic")
    res = adapter.load(s, mapping)
    assert not res.report.can_import and "mapping_unit" in codes(res.report)
    declared = mapping.model_copy(update={"defaults": MappingDefaults(unit="mm")})
    ok = adapter.load(s, declared)
    assert ok.report.can_import and ok.data["unit"].iloc[0] == "mm"


def test_mapping_to_a_nonexistent_column_is_an_error():
    mapping = identity_mapping().model_copy(update={"value": "does_not_exist"})
    res = adapter.load(src(*good_rows()), mapping)
    assert not res.report.can_import and "mapping_unknown_column" in codes(res.report)


def test_is_synthetic_must_be_declared_never_guessed():
    s = DataSource("x.csv", b"date,region,variable,value,unit,data_source\n2020-01-01,R,V,1,u,s\n")
    m = ColumnMapping(date="date", region="region", variable="variable", value="value", unit="unit", data_source="data_source")
    res = adapter.load(s, m)
    assert not res.report.can_import and "mapping_is_synthetic" in codes(res.report)
    ok = adapter.load(s, m.model_copy(update={"defaults": MappingDefaults(is_synthetic=False)}))
    assert ok.report.can_import and not ok.data["is_synthetic"].any()


def test_invalid_is_synthetic_tokens_exclude_rows():
    rows = good_rows(4) + ["2021-01-01,R1,V1,9,u,src,maybe"]
    res = adapter.load(src(*rows), identity_mapping())
    assert len(res.data) == 4 and "invalid_is_synthetic" in codes(res.report)


# ---------------------------------------------------------------- invalid data
def test_invalid_dates_are_excluded_and_reported():
    rows = good_rows(5) + ["not-a-date,R1,V1,1,u,src,false", "2020-13-45,R1,V1,2,u,src,false", ",R1,V1,3,u,src,false"]
    res = adapter.load(src(*rows), identity_mapping())
    assert res.report.n_invalid_dates == 3
    assert len(res.data) == 5 and res.report.n_rows_dropped == 3
    assert res.report.requires_confirmation and res.report.can_import
    issue = next(i for i in res.report.issues if i.code == "invalid_dates")
    assert "not-a-date" in issue.examples


def test_non_numeric_values_are_reported_never_zero_filled():
    rows = good_rows(5) + ["2021-01-01,R1,V1,abc,u,src,false", "2021-02-01,R1,V1,1,234,u,src,false"]
    # the second extra row has a stray comma -> malformed (too many fields)
    with pytest.raises(AppError) as exc:
        adapter.load(src(*rows), identity_mapping())
    assert exc.value.code == "malformed_csv"
    rows = good_rows(5) + ["2021-01-01,R1,V1,abc,u,src,false", "2021-02-01,R1,V1,inf,u,src,false"]
    res = adapter.load(src(*rows), identity_mapping())
    assert res.report.n_invalid_values == 2
    assert len(res.data) == 5
    assert (res.data["value"] != 0).all()


def test_blank_and_na_values_are_kept_as_missing_not_zero():
    rows = good_rows(4) + ["2021-01-01,R1,V1,,u,src,false", "2021-02-01,R1,V1,NA,u,src,false", "2021-03-01,R1,V1,NaN,u,src,false"]
    res = adapter.load(src(*rows), identity_mapping())
    assert len(res.data) == 7
    assert res.report.n_missing_values == 3 and res.report.n_invalid_values == 0
    assert res.data["value"].isna().sum() == 3
    assert not (res.data["value"] == 0).any()


def test_blank_labels_exclude_rows():
    rows = good_rows(3) + ["2021-01-01,,V1,1,u,src,false", "2021-02-01,R1,,1,u,src,false", "2021-03-01,R1,V1,1,,src,false"]
    res = adapter.load(src(*rows), identity_mapping())
    assert len(res.data) == 3 and res.report.n_invalid_labels == 3


def test_sentinel_values_are_flagged_but_not_converted():
    rows = good_rows(5) + ["2021-01-01,R1,V1,-9999,u,src,false"]
    res = adapter.load(src(*rows), identity_mapping())
    assert "possible_missing_value_codes" in codes(res.report)
    assert (res.data["value"] == -9999).sum() == 1  # still there, unchanged


def test_label_case_variants_warn_but_are_not_merged():
    rows = good_rows(3) + ["2021-01-01,r1,V1,1,u,src,false"]
    res = adapter.load(src(*rows), identity_mapping())
    assert "region_label_variants" in codes(res.report)
    assert set(res.data["region"]) == {"R1", "r1"}


# ------------------------------------------------------------------ duplicates
def test_identical_duplicates_are_removed_and_reported():
    rows = good_rows(3) + [good_rows(3)[0]]
    res = adapter.load(src(*rows), identity_mapping())
    assert res.report.n_duplicate_identical == 1 and res.report.n_duplicate_conflicting == 0
    assert len(res.data) == 3 and res.report.can_import


def conflicting_rows() -> list[str]:
    return good_rows(3) + ["2020-01-01,R1,V1,100,u,src,false"]


def test_conflicting_duplicates_block_by_default():
    res = adapter.load(src(*conflicting_rows()), identity_mapping())
    assert not res.report.can_import and "duplicate_conflict" in codes(res.report)
    assert res.report.n_duplicate_conflicting == 1 and res.data is None


@pytest.mark.parametrize(
    "policy,expected",
    [("first", 1.5), ("last", 100.0), ("mean", (1.5 + 100.0) / 2)],
)
def test_duplicate_policies_resolve_explicitly(policy, expected):
    mapping = identity_mapping().model_copy(update={"duplicate_policy": policy})
    res = adapter.load(src(*conflicting_rows()), mapping)
    assert res.report.can_import and res.report.requires_confirmation
    assert len(res.data) == 3
    first = res.data.sort_values("date").iloc[0]
    assert first["value"] == pytest.approx(expected)
    if policy == "mean":
        assert "mean of 2" in first["transformation_note"]


def test_duplicates_with_different_units_cannot_be_merged():
    rows = good_rows(3) + ["2020-01-01,R1,V1,5,other-unit,src,false"]
    mapping = identity_mapping().model_copy(update={"duplicate_policy": "mean"})
    res = adapter.load(src(*rows), mapping)
    assert not res.report.can_import and "duplicate_unit_conflict" in codes(res.report)


# ----------------------------------------------------------------------- units
def test_mixed_units_within_a_series_are_blocked():
    rows = good_rows(3) + ["2021-01-01,R1,V1,5,other-unit,src,false"]
    res = adapter.load(src(*rows), identity_mapping())
    assert not res.report.can_import and "mixed_units_in_series" in codes(res.report)


def test_units_differing_across_regions_warn_for_comparison():
    rows = good_rows(3) + ["2020-01-01,R2,V1,5,other-unit,src,false"]
    res = adapter.load(src(*rows), identity_mapping())
    assert res.report.can_import and "units_differ_across_regions" in codes(res.report)


# ----------------------------------------------------------------------- dates
def test_slash_dates_are_ambiguous_without_a_format():
    rows = ["01/02/2020,R1,V1,1,u,s,false", "02/02/2020,R1,V1,2,u,s,false", "03/02/2020,R1,V1,3,u,s,false"]
    res = adapter.load(src(*rows), identity_mapping())
    assert res.report.requires_confirmation and any("DD/MM" in a for a in res.report.ambiguities)


def test_explicit_date_format_resolves_ambiguity_and_parses_day_first():
    rows = ["31/01/2020,R1,V1,1,u,s,false", "29/02/2020,R1,V1,2,u,s,false"]
    mapping = identity_mapping().model_copy(update={"date_format": "%d/%m/%Y"})
    res = adapter.load(src(*rows), mapping)
    assert not res.report.requires_confirmation
    assert res.data["date"].dt.month.tolist() == [1, 2] and res.data["date"].dt.day.tolist() == [31, 29]


def test_iso_variants_year_month_and_year_only_parse():
    rows = ["2020-01,R1,V1,1,u,s,false", "2020-02-15,R1,V1,2,u,s,false", "2021,R1,V1,3,u,s,false"]
    res = adapter.load(src(*rows), identity_mapping())
    assert res.report.n_invalid_dates == 0 and len(res.data) == 3


# -------------------------------------------------------------- file handling
def test_semicolon_delimited_file_is_detected():
    text = "date;region;variable;value;unit;data_source;is_synthetic\n2020-01-01;R;V;1;u;s;false\n2020-02-01;R;V;2;u;s;false\n"
    insp = adapter.inspect(DataSource("semi.csv", text.encode()))
    assert insp.delimiter == ";" and insp.n_columns == 7 and insp.n_rows == 2


def test_non_utf8_file_decodes_with_a_warning():
    content = HEADER.encode() + "2020-01-01,Zürich,V,1,u,s,false\n".encode("cp1252")
    res = adapter.load(DataSource("l.csv", content), identity_mapping())
    assert res.data["region"].iloc[0] == "Zürich"
    assert "encoding" in codes(res.report)


def test_binary_empty_and_malformed_files_raise_clear_errors():
    with pytest.raises(AppError) as e1:
        adapter.inspect(DataSource("b.csv", b"\x00\x01\x02binary"))
    assert e1.value.code == "not_a_text_file"
    with pytest.raises(AppError) as e2:
        adapter.inspect(DataSource("e.csv", b"   \n"))
    assert e2.value.code == "empty_file"
    with pytest.raises(AppError) as e3:
        adapter.inspect(DataSource("h.csv", b"a,b,c\n"))
    assert e3.value.code == "no_rows"
    with pytest.raises(AppError) as e4:
        adapter.inspect(DataSource("m.csv", b"a,b\n1,2\n3,4,5,6\n"))
    assert e4.value.code == "malformed_csv" and "row 3" in e4.value.message
    with pytest.raises(AppError) as e5:  # extra field on EVERY row would otherwise be read as an implicit index
        adapter.inspect(DataSource("m2.csv", b"a,b\n1,2,3\n4,5,6\n"))
    assert e5.value.code == "malformed_csv"


def test_row_limit_is_enforced(settings, monkeypatch):
    monkeypatch.setattr("app.services.ingestion.csv_adapter.get_settings", lambda: settings)
    text = "a\n" + "\n".join(["1"] * (settings.max_rows + 1))
    with pytest.raises(AppError) as exc:
        adapter.inspect(DataSource("big.csv", text.encode()))
    assert exc.value.status_code == 413


def test_only_csv_is_supported_and_nothing_else_is_pretended():
    with pytest.raises(AppError) as exc:
        adapter_for("data.nc")
    assert exc.value.status_code == 415 and "not implemented" in exc.value.message
    for name in ("data.h5", "data.hdf", "data.tif", "noextension"):
        with pytest.raises(AppError):
            adapter_for(name)
    assert isinstance(adapter_for("OK.CSV"), CSVAdapter)


def test_profile_infers_types_and_suggests_a_mapping():
    text = (
        "Date,Site,Parameter,Reading,Units,Source,Synthetic,Lat,Lon\n"
        "2020-01-01,A,temp,1.5,K,x,false,10,20\n2020-02-01,A,temp,2.5,K,x,false,10,20\n"
    )
    p = adapter.profile(DataSource("p.csv", text.encode()))
    types = {c.name: c.inferred_type for c in p.column_profiles}
    assert types["Date"] == "datetime" and types["Reading"] == "numeric" and types["Site"] == "text"
    m = p.suggested_mapping
    assert (m.date, m.region, m.variable, m.value, m.unit, m.is_synthetic) == ("Date", "Site", "Parameter", "Reading", "Units", "Synthetic")
    assert m.optional == {"latitude": "Lat", "longitude": "Lon"}
    assert m.data_source == "Source"
    assert len(p.preview) == 2 and p.mapping_complete is True
    assert adapter.profile(DataSource("q.csv", b"date,value\n2020-01-01,1\n")).mapping_complete is False


def test_filename_sanitisation_and_csv_formula_protection():
    assert safe_filename("../../etc/passwd.csv") == "passwd.csv"
    assert safe_filename("C:\\Users\\x\\evil<>.csv") == "evil_.csv"
    assert safe_filename(None) == "upload.csv"
    assert csv_safe("=SUM(A1)") == "'=SUM(A1)"
    assert csv_safe("@cmd") == "'@cmd"
    assert csv_safe("normal") == "normal"
    assert csv_safe(-1.5) == -1.5  # numbers are never altered
