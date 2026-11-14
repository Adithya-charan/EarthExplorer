"""HTTP-level behaviour: endpoints, status codes, uploads, provenance, error shape."""

from __future__ import annotations

import io
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import DEMO

CSV = (
    "date,region,variable,value,unit,data_source,is_synthetic\n"
    + "\n".join(f"2020-{m:02d}-01,North,Gauge,{m * 1.5},mm,my lab,false" for m in range(1, 13))
    + "\n"
)
MAPPING = {
    "date": "date",
    "region": "region",
    "variable": "variable",
    "value": "value",
    "unit": "unit",
    "data_source": "data_source",
    "is_synthetic": "is_synthetic",
}


def post_upload(client, content=CSV, name="mine.csv", mapping=None, **form):
    data = {"mapping": json.dumps(mapping or MAPPING), "dry_run": "true"}
    data.update({k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in form.items()})
    return client.post("/api/upload", files={"file": (name, io.BytesIO(content.encode() if isinstance(content, str) else content), "text/csv")}, data=data)


# ------------------------------------------------------------- basics
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["datasets_loaded"] == 1
    assert body["nasa_dataset_integrated"] is False and body["uses_external_ai"] is False


def test_datasets_lists_demo_and_says_nasa_is_pending(client):
    body = client.get("/api/datasets").json()
    assert body["default_dataset_id"] == DEMO
    demo = body["datasets"][0]
    assert demo["status"] == "synthetic_demo" and demo["is_synthetic"] is True
    assert demo["n_rows"] == 2520 and demo["n_variables"] == 3 and demo["n_regions"] == 4 and demo["n_series"] == 10
    assert demo["date_start"] == "2000-01-01" and demo["date_end"] == "2023-12-01"
    assert body["nasa_dataset"]["integrated"] is False
    assert "has not been supplied" in body["nasa_dataset"]["message"]


def test_metadata_is_derived_from_loaded_data(client):
    body = client.get("/api/metadata", params={"dataset_id": DEMO}).json()
    assert {v["name"] for v in body["variables"]} == {"Synthetic Index A", "Synthetic Index B", "Synthetic Index C"}
    assert {r["name"] for r in body["regions"]} == {"Region Alpha", "Region Beta", "Region Gamma", "Region Delta"}
    assert len(body["series"]) == 10
    gamma_c = next(s for s in body["series"] if s["variable"] == "Synthetic Index C" and s["region"] == "Region Gamma")
    assert gamma_c["sampling"] == "annual" and gamma_c["n_valid"] == 24
    a_gamma = next(s for s in body["series"] if s["variable"] == "Synthetic Index A" and s["region"] == "Region Gamma")
    assert a_gamma["n_missing"] == 12
    assert body["provenance"]["is_synthetic"] is True
    assert "mission" not in body["optional_fields_present"] and "latitude" not in body["optional_fields_present"]
    # no fabricated geography
    assert body["spatial"]["available"] is False and body["spatial"]["latitude_range"] is None


def test_metadata_defaults_to_first_dataset_and_404s_for_unknown(client):
    assert client.get("/api/metadata").json()["dataset"]["id"] == DEMO
    r = client.get("/api/metadata", params={"dataset_id": "nope"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "dataset_not_found"


def test_observations_pagination_and_filters(client):
    p = {"dataset_id": DEMO, "variable": "Synthetic Index A", "region": "Region Alpha"}
    page = client.get("/api/observations", params={**p, "limit": 10, "offset": 5}).json()
    assert page["total"] == 288 and len(page["rows"]) == 10 and page["rows"][0]["date"] == "2000-06-01"
    assert page["provenance"]["is_synthetic"] is True
    row = page["rows"][0]
    assert row["is_synthetic"] is True and "Synthetic" in row["data_source"]
    ranged = client.get("/api/observations", params={**p, "start": "2001-01-01", "end": "2001-12-31"}).json()
    assert ranged["total"] == 12
    gamma = client.get("/api/observations", params={**p, "region": "Region Gamma", "include_missing": False}).json()
    assert gamma["total"] == 276
    gamma_all = client.get("/api/observations", params={**p, "region": "Region Gamma"}).json()
    assert gamma_all["total"] == 288 and any(r["value"] is None for r in gamma_all["rows"])


def test_observations_csv_export_carries_provenance(client):
    r = client.get("/api/observations", params={"dataset_id": DEMO, "variable": "Synthetic Index B", "region": "Region Beta", "format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.splitlines()
    assert lines[0].startswith("# EarthTrend Explorer export") and "is_synthetic: true" in lines[0]
    assert "Synthetic demo data" in lines[1]
    header = lines[2].split(",")
    assert "is_synthetic" in header and "data_source" in header
    assert len(lines) == 3 + 288


def test_validation_errors_use_the_standard_error_shape(client):
    r = client.get("/api/observations", params={"dataset_id": DEMO, "limit": 0})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    r = client.post("/api/analyze", json={"dataset_id": DEMO, "variable": "Synthetic Index A", "region": "Region Alpha", "alpha": 0.9})
    assert r.status_code == 422 and "alpha" in r.json()["error"]["message"]
    r = client.post("/api/analyze", json={"dataset_id": DEMO, "variable": "Synthetic Index A"})
    assert r.status_code == 422
    r = client.get("/api/observations", params={"dataset_id": DEMO, "start": "2010-01-01", "end": "2000-01-01"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_date_range"


def test_unhandled_errors_do_not_leak_internals(settings, monkeypatch):
    app = create_app(settings)

    def boom(*a, **k):
        raise RuntimeError("secret-internal-detail /srv/path")

    monkeypatch.setattr("app.routers.analysis.analysis.analyze_series", boom)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/api/analyze", json={"dataset_id": DEMO, "variable": "Synthetic Index A", "region": "Region Alpha"})
    assert r.status_code == 500
    assert "secret" not in r.text and "Traceback" not in r.text
    assert r.json()["error"]["code"] == "internal_error"


def test_cors_allows_only_configured_origins(client):
    ok = client.options("/api/health", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    forwarded = client.options("/api/health", headers={"Origin": "http://127.0.0.1:5174", "Access-Control-Request-Method": "GET"})
    assert forwarded.headers.get("access-control-allow-origin") == "http://127.0.0.1:5174"
    bad = client.options("/api/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_openapi_documents_every_required_endpoint(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ["/api/health", "/api/metadata", "/api/datasets", "/api/observations", "/api/upload", "/api/profile", "/api/analyze", "/api/compare", "/api/explain", "/api/methodology"]:
        assert p in paths


# ------------------------------------------------------------ analysis & explain
def test_analyze_endpoint_returns_provenance_stats_and_explanation(client):
    r = client.post("/api/analyze", json={"dataset_id": DEMO, "variable": "Synthetic Index A", "region": "Region Beta"})
    assert r.status_code == 200
    b = r.json()
    assert b["provenance"]["is_synthetic"] is True and b["provenance"]["status"] == "synthetic_demo"
    assert b["primary"]["trend"] == "decreasing" and b["primary"]["slope_unit"] == "synthetic unit A per year"
    assert b["linear_regression"]["ci_low"] < b["linear_regression"]["slope_per_year"] < b["linear_regression"]["ci_high"]
    assert b["coverage"]["n_valid"] == 288
    assert b["explanation"]["uses_external_ai"] is False
    assert b["assumptions"] and b["points"][0]["date"] == "2000-01-01"


def test_compare_endpoint(client):
    r = client.post("/api/compare", json={"dataset_id": DEMO, "variable": "Synthetic Index A", "regions": ["Region Alpha", "Region Beta", "Region Gamma"]})
    assert r.status_code == 200
    b = r.json()
    assert b["direction_summary"] == "opposite_directions" and b["n_tests"] == 3
    assert len(b["results"]) == 3 and all(x["provenance"]["is_synthetic"] for x in b["results"])
    assert b["provenance"]["is_synthetic"] is True


def test_explain_endpoint_matches_embedded_explanation_and_validates_input(client):
    a = client.post("/api/analyze", json={"dataset_id": DEMO, "variable": "Synthetic Index A", "region": "Region Delta"}).json()
    r = client.post("/api/explain", json={"analysis": a})
    assert r.status_code == 200 and r.json()["explanation"] == a["explanation"]
    c = client.post("/api/compare", json={"dataset_id": DEMO, "variable": "Synthetic Index A", "regions": ["Region Alpha", "Region Beta"]}).json()
    assert client.post("/api/explain", json={"comparison": c}).json()["explanation"] == c["explanation"]
    assert client.post("/api/explain", json={}).status_code == 422
    assert client.post("/api/explain", json={"analysis": a, "comparison": c}).status_code == 422


def test_methodology_endpoint_has_sections_and_verifiable_references(client):
    b = client.get("/api/methodology").json()
    ids = {s["id"] for s in b["sections"]}
    assert {"regression", "ci", "mann-kendall", "sen", "seasonality", "autocorrelation", "missing", "multiple", "limits"} <= ids
    assert any("Hamed" in r["citation"] for r in b["references"])
    assert all(r["url"] is None or r["url"].startswith("https://") for r in b["references"])


# ------------------------------------------------------------------ upload flow
def test_profile_endpoint_returns_columns_preview_and_suggested_mapping(client):
    r = client.post("/api/profile", files={"file": ("mine.csv", io.BytesIO(CSV.encode()), "text/csv")})
    assert r.status_code == 200
    b = r.json()
    assert b["columns"][:3] == ["date", "region", "variable"] and b["n_rows"] == 12 and len(b["preview"]) == 10
    assert b["mapping_complete"] is True and b["suggested_mapping"]["value"] == "value"


def test_dry_run_validates_without_importing(client):
    r = post_upload(client)
    assert r.status_code == 200
    b = r.json()
    assert b["dry_run"] is True and b["imported"] is False and b["quality"]["can_import"] is True
    assert len(client.get("/api/datasets").json()["datasets"]) == 1


def test_import_keeps_upload_separate_from_demo_and_never_labels_it_nasa_or_synthetic(client):
    r = post_upload(client, dry_run=False, dataset_name="Rain gauge")
    assert r.status_code == 200, r.text
    ds = r.json()["dataset"]
    assert ds["status"] == "uploaded" and ds["is_synthetic"] is False and ds["name"] == "Rain gauge"
    assert "NASA" not in (ds["notice"] or "") and "not been verified" in ds["notice"]
    listing = client.get("/api/datasets").json()
    assert [d["id"] for d in listing["datasets"]][0] == DEMO and len(listing["datasets"]) == 2
    assert listing["nasa_dataset"]["integrated"] is False  # an upload never becomes "NASA verified"
    a = client.post("/api/analyze", json={"dataset_id": ds["id"], "variable": "Gauge", "region": "North"}).json()
    assert a["provenance"]["is_synthetic"] is False and a["provenance"]["status"] == "uploaded"
    demo = client.get("/api/metadata", params={"dataset_id": DEMO}).json()
    assert demo["dataset"]["n_rows"] == 2520 and "Gauge" not in {v["name"] for v in demo["variables"]}


def test_uploaded_rows_flagged_synthetic_are_still_labelled_synthetic(client):
    csv = CSV.replace(",false", ",true")
    ds = post_upload(client, csv, dry_run=False).json()["dataset"]
    assert ds["is_synthetic"] is True
    a = client.post("/api/analyze", json={"dataset_id": ds["id"], "variable": "Gauge", "region": "North"}).json()
    assert a["provenance"]["is_synthetic"] is True and any(w["code"] == "synthetic_data" for w in a["warnings"])


def test_import_blocked_when_mapping_is_incomplete(client):
    bad = {k: v for k, v in MAPPING.items() if k != "unit"}
    r = post_upload(client, mapping=bad, dry_run=False)
    assert r.status_code == 422 and r.json()["error"]["code"] == "import_blocked"
    assert "unit" in r.json()["error"]["message"]
    assert len(client.get("/api/datasets").json()["datasets"]) == 1


def test_import_requires_confirmation_for_ambiguities(client):
    dirty = CSV + "not-a-date,North,Gauge,1,mm,my lab,false\n"
    dry = post_upload(client, dirty).json()
    assert dry["quality"]["requires_confirmation"] is True and dry["quality"]["n_invalid_dates"] == 1
    r = post_upload(client, dirty, dry_run=False)
    assert r.status_code == 409 and r.json()["error"]["code"] == "confirmation_required"
    ok = post_upload(client, dirty, dry_run=False, confirmed=True)
    assert ok.status_code == 200 and ok.json()["dataset"]["n_rows"] == 12


def test_invalid_mapping_json_is_a_clear_422(client):
    r = client.post("/api/upload", files={"file": ("a.csv", io.BytesIO(CSV.encode()), "text/csv")}, data={"mapping": "{not json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_mapping"
    r = post_upload(client, mapping={**MAPPING, "optional": {"made_up_field": "x"}})
    assert r.status_code == 422 and "made_up_field" in r.json()["error"]["message"]


def test_unsupported_formats_are_rejected_not_pretended(client):
    for name in ("data.nc", "data.h5", "data.tif", "data.xlsx", "data"):
        r = post_upload(client, "x", name=name)
        assert r.status_code == 415, name
        assert "not supported" in r.json()["error"]["message"]
    r = client.post("/api/profile", files={"file": ("data.nc", io.BytesIO(b"CDF"), "application/x-netcdf")})
    assert r.status_code == 415


def test_oversized_upload_is_rejected(client, settings):
    big = "date,value\n" + ("2020-01-01,1\n" * 120_000)  # > 1 MB limit configured in the fixture
    assert len(big) > settings.max_upload_bytes
    r = post_upload(client, big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
    r = client.post("/api/profile", files={"file": ("big.csv", io.BytesIO(big.encode()), "text/csv")})
    assert r.status_code == 413


def test_declared_content_length_over_limit_is_rejected_early(client, settings):
    r = client.post(
        "/api/upload",
        content=b"x",
        headers={"content-length": str(settings.max_upload_bytes + 5 * 1024 * 1024), "content-type": "multipart/form-data; boundary=x"},
    )
    assert r.status_code == 413


def test_empty_and_binary_uploads_are_rejected(client):
    assert post_upload(client, b"").status_code == 400
    r = post_upload(client, b"\x00\x01\x02\x03binary")
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_a_text_file"


def test_uploaded_filename_is_sanitised_and_never_used_as_a_path(client, settings):
    ds = post_upload(client, name="../../evil name.csv", dry_run=False).json()["dataset"]
    assert ds["source_file"] == "evil name.csv"
    stored = {p.name for p in settings.upload_dir.iterdir()}
    assert stored == {f"{ds['id']}.csv", f"{ds['id']}.json"}  # server-generated ids only


def test_uploads_persist_across_restart_and_can_be_deleted(client, settings):
    ds = post_upload(client, dry_run=False).json()["dataset"]
    fresh = TestClient(create_app(settings))
    assert ds["id"] in [d["id"] for d in fresh.get("/api/datasets").json()["datasets"]]
    again = fresh.post("/api/analyze", json={"dataset_id": ds["id"], "variable": "Gauge", "region": "North"})
    assert again.status_code == 200
    assert fresh.delete(f"/api/datasets/{ds['id']}").status_code == 204
    assert fresh.get("/api/metadata", params={"dataset_id": ds["id"]}).status_code == 404
    assert not list(settings.upload_dir.glob("*"))


def test_demo_dataset_cannot_be_deleted(client):
    r = client.delete(f"/api/datasets/{DEMO}")
    assert r.status_code == 403
    assert client.get("/api/health").json()["datasets_loaded"] == 1


def test_stored_dataset_limit_is_enforced(client):
    for i in range(3):
        assert post_upload(client, dry_run=False, dataset_name=f"d{i}").status_code == 200
    r = post_upload(client, dry_run=False, dataset_name="one too many")
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_many_datasets"


def test_csv_export_neutralises_spreadsheet_formulas(client):
    csv = CSV.replace("North", "=HYPERLINK(1)")
    ds = post_upload(client, csv, dry_run=False).json()["dataset"]
    r = client.get("/api/observations", params={"dataset_id": ds["id"], "format": "csv"})
    df = pd.read_csv(io.StringIO(r.text), comment="#")
    assert (df["region"] == "'=HYPERLINK(1)").all()
    assert df["value"].min() >= 0  # numbers are untouched
