"""Packaged CSVs: parsers, loader, class separation, labelling and diagnostics.

The inline CSV strings below are TEST FIXTURES with hand-checkable values. They are not observations and never reach
the running application; the application only loads files from the ``datasets/`` package.
"""

from __future__ import annotations

import json
import shutil

import numpy as np
import pandas as pd
import pytest

from app.services.diagnostics_report import autocorrelation_diag, missingness, month_of_year
from app.services.ingestion.package_adapters import SYNTHETIC_BANNER, SYNTHETIC_LABEL, parse_giovanni_csv, parse_regional_demo_csv
from app.services.ingestion.package_loader import (
    DEMO_ID,
    DEMO_NAME,
    OBSERVED_ERROR_FILE,
    OBSERVED_ID,
    OBSERVED_PRECIP_FILE,
    load_package,
)
from tests.conftest import REPO_DATASETS

GLOBAL = "Global (area-average)"


def giovanni(rows: list[str], column: str = "mean_GPM_3IMERGM_07_precipitation", extra_meta: str = "", end: str = "2025-12-31T23:59:59Z") -> bytes:
    head = (
        'Title:,"Test fixture"\n'
        f"User End Date:,{end}\n"
        + (extra_meta + "\n" if extra_meta else "")
        + f"Fill Value ({column}):, -9999.9\n"
        + "\n"
        + f"time, {column}\n"
    )
    return (head + "\n".join(rows) + "\n").encode()


def codes(parsed, severity=None) -> set[str]:
    return {c.code for c in parsed.checks if severity is None or c.severity == severity}


# ------------------------------------------------------------------------------------------- Giovanni parser
def test_giovanni_parses_values_and_unit_exactly():
    p = parse_giovanni_csv(giovanni(["1998-01-01 00:00:00,0.1", "1998-02-01 00:00:00,0.2", "1998-03-01 00:00:00,0.3"]))
    assert p.ok and p.variable == "precipitation" and p.unit == "mm/hr"
    assert p.data["value"].tolist() == [0.1, 0.2, 0.3]
    assert list(p.data["date"].dt.strftime("%Y-%m")) == ["1998-01", "1998-02", "1998-03"]
    assert "no_missing_months" in codes(p)


def test_giovanni_fill_value_becomes_explicit_missing_not_zero():
    p = parse_giovanni_csv(giovanni(["1998-01-01 00:00:00,0.1", "1998-02-01 00:00:00,-9999.9", "1998-03-01 00:00:00,0.3"]))
    assert p.ok and p.n_fill_values == 1
    assert np.isnan(p.data["value"].iloc[1]) and "fill_values" in codes(p, "warning")


def test_giovanni_missing_month_is_reported_not_filled():
    p = parse_giovanni_csv(giovanni(["1998-01-01 00:00:00,0.1", "1998-03-01 00:00:00,0.3"]))
    assert p.ok and len(p.data) == 2 and "missing_months" in codes(p, "warning")


def test_giovanni_duplicate_dates_rejected():
    p = parse_giovanni_csv(giovanni(["1998-01-01 00:00:00,0.1", "1998-01-01 00:00:00,0.2"]))
    assert not p.ok and "duplicate_dates" in codes(p, "error") and p.data is None


def test_giovanni_invalid_number_and_date_rejected():
    assert "invalid_value" in codes(parse_giovanni_csv(giovanni(["1998-01-01 00:00:00,abc"])), "error")
    assert "invalid_date" in codes(parse_giovanni_csv(giovanni(["not-a-date,0.1"])), "error")


def test_giovanni_unknown_column_has_no_guessed_unit():
    p = parse_giovanni_csv(giovanni(["1998-01-01 00:00:00,0.1"], column="mean_GPM_3IMERGM_07_mystery"))
    assert not p.ok and "unknown_unit" in codes(p, "error")


def test_giovanni_wrong_declared_unit_rejected():
    p = parse_giovanni_csv(giovanni(["1998-01-01 00:00:00,0.1"], extra_meta="Units:,mm/month"))
    assert not p.ok and "invalid_unit" in codes(p, "error")


def test_giovanni_declared_mm_per_hr_accepted():
    assert parse_giovanni_csv(giovanni(["1998-01-01 00:00:00,0.1"], extra_meta="Units:,mm/hr")).ok


def test_giovanni_end_date_discrepancy_is_noted():
    p = parse_giovanni_csv(giovanni(["1998-01-01 00:00:00,0.1", "1998-02-01 00:00:00,0.2"]))
    assert "coverage_shorter_than_requested" in codes(p, "info")


def test_giovanni_negative_rate_rejected():
    assert not parse_giovanni_csv(giovanni(["1998-01-01 00:00:00,-0.5"])).ok


@pytest.mark.parametrize("content", [b"", b"a,b\n1,2\n", b"\xff\xfe\x00bad"])
def test_giovanni_garbage_is_an_error_not_a_crash(content):
    assert not parse_giovanni_csv(content).ok


# ------------------------------------------------------------------------------------------- regional parser
def regional(rows: list[str], label: str = SYNTHETIC_LABEL, region: str = "India") -> bytes:
    head = "date,precipitation_mm_per_hour,uncertainty_random_error_mm_per_hour,uncertainty_lower_1sigma_mm_per_hour,uncertainty_upper_1sigma_mm_per_hour,region,dataset_type\n"
    return (head + "\n".join(f"{r},0.1,0.1,0.1,{region},{label}" if False else f"{r.split(',')[0]},{r.split(',')[1]},0.01,0,0,{region},{label}" for r in rows) + "\n").encode()


def test_regional_parses_and_keeps_label():
    p = parse_regional_demo_csv(regional(["1998-01-01,0.5", "1998-02-01,0.7"]))
    assert p.ok and p.region == "India" and p.data["precipitation"].tolist() == [0.5, 0.7]
    assert any(SYNTHETIC_BANNER in c.message for c in p.checks)


def test_regional_without_synthetic_label_is_refused():
    p = parse_regional_demo_csv(regional(["1998-01-01,0.5"], label="OBSERVED"))
    assert not p.ok and "not_labelled_synthetic" in codes(p, "error")


def test_regional_unsorted_rows_stay_aligned_with_their_dates():
    p = parse_regional_demo_csv(regional(["1998-03-01,0.3", "1998-01-01,0.1", "1998-02-01,0.2"]))
    assert p.ok and p.data["precipitation"].tolist() == [0.1, 0.2, 0.3]


def test_regional_missing_columns_and_bad_values():
    assert "missing_columns" in codes(parse_regional_demo_csv(b"date,region\n1998-01-01,India\n"), "error")
    bad = regional(["1998-01-01,oops"])
    assert "invalid_value" in codes(parse_regional_demo_csv(bad), "error")


# ------------------------------------------------------------------------------------------- loader
def package_copy(tmp_path):
    dst = tmp_path / "datasets"
    shutil.copytree(REPO_DATASETS, dst)
    return dst


def test_real_package_loads_two_separate_classes():
    r = load_package(REPO_DATASETS)
    assert [d.id for d in r.datasets] == [OBSERVED_ID, DEMO_ID] and r.issues == []
    obs, demo = r.datasets
    assert obs.status == "observed_global" and not obs.data["is_synthetic"].any()
    assert demo.status == "synthetic_regional_demo" and demo.data["is_synthetic"].all()
    assert set(obs.data["region"]) == {GLOBAL}
    assert set(demo.data["region"]) == {"India", "Amazon", "Central Africa"}
    assert set(obs.data["unit"]) == set(demo.data["unit"]) == {"mm/hr"}
    assert set(demo.data["data_source"]) == {SYNTHETIC_BANNER}
    assert len(obs.data[obs.data["variable"] == "precipitation"]) == 333


def test_loaded_values_equal_the_csv_exactly():
    raw = pd.read_csv(REPO_DATASETS / OBSERVED_PRECIP_FILE, skiprows=8, skipinitialspace=True)
    obs = load_package(REPO_DATASETS).datasets[0].data
    got = obs[obs["variable"] == "precipitation"]["value"].to_numpy()
    assert np.array_equal(got, raw.iloc[:, 1].to_numpy())


def test_missing_observed_file_is_reported_and_nothing_substituted(tmp_path):
    root = package_copy(tmp_path)
    (root / OBSERVED_PRECIP_FILE).unlink()
    r = load_package(root)
    assert [d.id for d in r.datasets] == [DEMO_ID]  # demo still loads, but it is NOT used in place of observed data
    assert any(i.code == "observed_unavailable" and i.severity == "error" for i in r.issues)


def test_missing_package_folder_is_a_warning(tmp_path):
    r = load_package(tmp_path / "nope")
    assert r.datasets == [] and r.issues[0].code == "package_missing"


def test_misaligned_random_error_is_not_loaded(tmp_path):
    root = package_copy(tmp_path)
    f = root / OBSERVED_ERROR_FILE
    lines = f.read_text(encoding="utf-8").splitlines()
    f.write_text("\n".join(ln for ln in lines if not ln.startswith("2000-06-01")) + "\n", encoding="utf-8")
    obs = load_package(root).datasets[0]
    assert set(obs.data["variable"]) == {"precipitation"}
    assert any(c.code == "dates_misaligned" for c in obs.info.checks)


def test_unlabelled_regional_file_is_skipped(tmp_path):
    root = package_copy(tmp_path)
    f = next((root / "synthetic_regional_demo").glob("*India*"))
    f.write_text(f.read_text(encoding="utf-8").replace(SYNTHETIC_LABEL, "OBSERVED"), encoding="utf-8")
    demo = load_package(root).datasets[1]
    assert "India" not in set(demo.data["region"])


# ------------------------------------------------------------------------------------------- API / labelling / separation
def test_api_lists_classes_and_prefers_observed_default(package_client):
    d = package_client.get("/api/datasets").json()
    by_id = {x["id"]: x for x in d["datasets"]}
    assert d["default_dataset_id"] == OBSERVED_ID and d["package_issues"] == []
    assert by_id[OBSERVED_ID]["status"] == "observed_global" and by_id[OBSERVED_ID]["info"]["regional_analysis_allowed"] is False
    assert by_id[OBSERVED_ID]["is_synthetic"] is False and by_id[DEMO_ID]["is_synthetic"] is True
    assert by_id[DEMO_ID]["info"]["label"] == SYNTHETIC_BANNER and SYNTHETIC_BANNER in by_id[DEMO_ID]["notice"]
    info = by_id[OBSERVED_ID]["info"]
    assert info["unit"] == "mm/hr" and info["temporal_coverage"].startswith("1998-01 to 2025-09") and info["limitations"]


def test_observed_global_is_a_single_global_region_and_cannot_be_compared(package_client):
    md = package_client.get("/api/metadata", params={"dataset_id": OBSERVED_ID}).json()
    assert [r["name"] for r in md["regions"]] == [GLOBAL]
    r = package_client.post("/api/compare", json={"dataset_id": OBSERVED_ID, "variable": "precipitation", "regions": [GLOBAL, "India"]})
    assert r.status_code in (404, 422)


def test_regions_do_not_leak_between_classes(package_client):
    r = package_client.post("/api/analyze", json={"dataset_id": OBSERVED_ID, "variable": "precipitation", "region": "India"})
    assert r.status_code == 404
    r = package_client.post("/api/analyze", json={"dataset_id": DEMO_ID, "variable": "precipitation", "region": GLOBAL})
    assert r.status_code == 404


def test_analyze_carries_the_class_notice_and_unit(package_client):
    a = package_client.post("/api/analyze", json={"dataset_id": DEMO_ID, "variable": "precipitation", "region": "India"}).json()
    assert a["provenance"]["is_synthetic"] is True and SYNTHETIC_BANNER in a["provenance"]["notice"] and a["unit"] == "mm/hr"
    g = package_client.post("/api/analyze", json={"dataset_id": OBSERVED_ID, "variable": "precipitation", "region": GLOBAL}).json()
    assert g["provenance"]["is_synthetic"] is False and "not any region" in g["provenance"]["notice"] and g["unit"] == "mm/hr"


def test_trend_is_computed_from_the_loaded_rows(package_client):
    g = package_client.post("/api/analyze", json={"dataset_id": OBSERVED_ID, "variable": "precipitation", "region": GLOBAL}).json()
    obs = load_package(REPO_DATASETS).datasets[0].data
    s = obs[obs["variable"] == "precipitation"].sort_values("date")
    t = (s["date"].dt.year + (s["date"].dt.month - 1) / 12).to_numpy()
    slope = np.polyfit(t, s["value"].to_numpy(), 1)[0]
    ols = g["linear_regression"]
    assert ols["slope_per_year"] == pytest.approx(slope, rel=0.02)  # same data, same estimator (time axis in years)
    assert ols["n"] == 333


def test_exports_carry_the_synthetic_banner(package_client):
    csv = package_client.get("/api/observations", params={"dataset_id": DEMO_ID, "format": "csv", "region": "Amazon"}).text
    assert csv.startswith("# EarthTrend Explorer export") and f"# {SYNTHETIC_BANNER}" in csv.splitlines()[1]
    assert "is_synthetic" in csv and SYNTHETIC_BANNER in csv.replace("\n", " ")
    j = package_client.get("/api/observations", params={"dataset_id": DEMO_ID, "limit": 3}).json()
    assert j["provenance"]["is_synthetic"] and all(r["is_synthetic"] for r in j["rows"])


def test_package_records_are_read_only(package_client):
    assert package_client.delete(f"/api/datasets/{OBSERVED_ID}").status_code == 403
    assert package_client.delete(f"/api/datasets/{DEMO_ID}").status_code == 403


# ------------------------------------------------------------------------------------------- diagnostics
def frame(values, start="2000-01-01", every="MS"):
    return pd.DataFrame({"date": pd.date_range(start, periods=len(values), freq=every), "value": values})


def test_month_of_year_summary_matches_hand_values():
    # two years: Jan = 1, 3 ; Feb = 2, 4 ; other months missing
    sub = pd.DataFrame({"date": pd.to_datetime(["2000-01-01", "2000-02-01", "2001-01-01", "2001-02-01"]), "value": [1.0, 2.0, 3.0, 4.0]})
    m = {x.month: x for x in month_of_year(sub)}
    assert (m[1].n, m[1].mean, m[1].median, m[1].minimum, m[1].maximum) == (2, 2.0, 2.0, 1.0, 3.0)
    assert m[1].std == pytest.approx(np.sqrt(2.0)) and m[2].mean == 3.0
    assert m[3].n == 0 and m[3].mean is None


def test_missingness_counts_absent_and_fill_months():
    sub = frame([1.0, 2.0, 3.0, 4.0, 5.0])
    sub = sub.drop(index=2)  # March absent
    sub.loc[3, "value"] = np.nan  # April present but missing
    d = missingness(sub)
    assert (d.expected_months, d.present_rows, d.valid_values, d.missing_values) == (5, 4, 3, 1)
    assert [m.month for m in d.absent_months] == [3] and d.longest_gap_months == 2
    assert d.coverage_fraction == pytest.approx(3 / 5)


def test_autocorrelation_constant_series_not_evaluated():
    ac = autocorrelation_diag(frame([2.0] * 40))
    assert ac.detrended is not None and ac.detrended.evaluated is False


def test_autocorrelation_flags_a_persistent_series_and_warns_on_gaps():
    rng = np.random.default_rng(0)
    x = np.zeros(120)
    for i in range(1, 120):  # AR(1) with phi 0.8: strongly autocorrelated by construction
        x[i] = 0.8 * x[i - 1] + rng.normal()
    ac = autocorrelation_diag(frame(x))
    assert ac.detrended.evaluated and ac.detrended.lag1 > 0.5 and ac.detrended.flagged is True
    gap = autocorrelation_diag(frame(x).drop(index=[10, 11]))
    assert gap.contiguous_months is False and "equal spacing" in gap.note


def test_perfect_line_leaves_no_trend_residual():
    ac = autocorrelation_diag(frame(list(np.arange(30, dtype=float))))
    assert ac.detrended.evaluated is False  # residuals are ~0 variance after the OLS fit


def test_diagnostics_endpoint_runtime_values(package_client):
    j = package_client.get("/api/diagnostics", params={"dataset_id": OBSERVED_ID, "variable": "precipitation", "region": GLOBAL}).json()
    obs = load_package(REPO_DATASETS).datasets[0].data
    s = obs[obs["variable"] == "precipitation"]
    assert j["missingness"]["expected_months"] == 333 and j["missingness"]["absent_months"] == [] and j["missingness"]["valid_values"] == 333
    jan = j["month_of_year"][0]
    assert jan["n"] == 28 and jan["mean"] == pytest.approx(s[s["date"].dt.month == 1]["value"].mean())
    re_ = j["random_error"]
    assert re_["available"] and re_["dates_aligned"] and re_["usable_as_confidence_interval"] is False and re_["unit"] == "mm/hr"
    assert "not a confidence interval" in re_["note"]
    assert j["provenance"]["is_synthetic"] is False


def test_diagnostics_for_synthetic_region_keep_the_banner(package_client):
    j = package_client.get("/api/diagnostics", params={"dataset_id": DEMO_ID, "variable": "precipitation", "region": "India"}).json()
    assert j["provenance"]["is_synthetic"] and SYNTHETIC_BANNER in j["provenance"]["notice"]


def test_diagnostics_errors_are_explicit(package_client):
    r = package_client.get("/api/diagnostics", params={"dataset_id": OBSERVED_ID, "variable": "precipitation", "region": "India"})
    assert r.status_code == 404
    r = package_client.get("/api/diagnostics", params={"dataset_id": "nope", "variable": "precipitation", "region": "x"})
    assert r.status_code == 404


def test_default_name_constant_is_labelled():
    assert "NOT NASA OBSERVATIONS" in DEMO_NAME


def test_provenance_carries_a_stable_dataset_checksum(package_client):
    q = {"dataset_id": OBSERVED_ID, "variable": "precipitation", "region": GLOBAL}
    a = package_client.post("/api/analyze", json=q).json()["provenance"]
    b = package_client.post("/api/analyze", json={**q, "start": "2010-01-01"}).json()["provenance"]
    d = package_client.post("/api/analyze", json={"dataset_id": DEMO_ID, "variable": "precipitation", "region": "India"}).json()["provenance"]
    assert len(a["dataset_checksum"]) == 64 and a["generated_at"]
    assert a["dataset_checksum"] == b["dataset_checksum"] != d["dataset_checksum"]  # identifies the dataset, not the selection
    csv = package_client.get("/api/observations", params={"dataset_id": OBSERVED_ID, "format": "csv", "limit": 5}).text
    assert f"dataset_sha256: {a['dataset_checksum']}" in csv.splitlines()[0]


def test_csv_export_header_has_checksum_and_generated_at(package_client):
    csv = package_client.get("/api/observations", params={"dataset_id": OBSERVED_ID, "format": "csv", "limit": 5}).text
    head = csv.splitlines()[0]
    assert "dataset_sha256: " in head and "| generated_at: 20" in head and head.rstrip().endswith("+00:00")


def test_seasonal_autocorrelation_warning_separates_assessment_from_correction(package_client):
    a = package_client.post("/api/analyze", json={"dataset_id": OBSERVED_ID, "variable": "precipitation", "region": GLOBAL}).json()
    assert a["autocorrelation"]["evaluated"] is True and a["autocorrelation"]["flagged"] is True
    msg = next(w["message"] for w in a["warnings"] if w["code"] == "autocorrelation_uncorrected")
    assert "was assessed" in msg and "Hamed-Rao correction is not available for the seasonal analysis path" in msg
    limits = json.dumps(a["explanation"])
    assert "was assessed" in limits and "seasonal analysis path" in limits
