"""Whole-record overview and atlas."""

from __future__ import annotations

G, D, R = "gpm-imerg-global-observed", "gpm-imerg-regional-synthetic-demo", "Global (area-average)"


def test_overview_observed_global_is_complete_and_traceable(package_client):
    r = package_client.get("/api/overview", params={"dataset_id": G, "region": R})
    assert r.status_code == 200
    b = r.json()
    assert b["banner"] is None and b["provenance"]["is_synthetic"] is False
    assert b["provenance"]["dataset_checksum"]
    assert len(b["years"]) == b["last_year"] - b["first_year"] + 1
    assert len(b["matrix_values"]) == len(b["years"]) and all(len(row) == 12 for row in b["matrix_values"])
    assert len(b["matrix_z"]) == len(b["years"]) and len(b["climatology"]) == 12
    assert all(s["evidence"] for s in b["sentences"])
    assert {s["kind"] for s in b["sentences"]} >= {"observation", "limitation"}
    # a z value only exists where a value exists
    for rv, rz in zip(b["matrix_values"], b["matrix_z"]):
        assert all(v is not None for v, z in zip(rv, rz) if z is not None)


def test_overview_synthetic_is_labelled(package_client):
    b = package_client.get("/api/overview", params={"dataset_id": D, "region": "India"}).json()
    assert b["banner"] == "SYNTHETIC DEMO — NOT NASA OBSERVATIONS"
    assert any("SYNTHETIC DEMO" in c for c in b["caveats"])
    assert "(synthetic demo)" in b["sentences"][0]["text"]


def test_overview_unknown_region_and_variable(package_client):
    assert package_client.get("/api/overview", params={"dataset_id": G, "region": "Nowhere"}).status_code == 404
    assert package_client.get("/api/overview", params={"dataset_id": G, "region": R, "variable": "nope"}).status_code == 404


def test_atlas_covers_every_region_with_aligned_years(package_client):
    b = package_client.get("/api/atlas", params={"dataset_id": D}).json()
    assert {x["region"] for x in b["regions"]} >= {"India", "Amazon", "Central Africa"}
    assert all(len(x["z"]) == len(b["years"]) for x in b["regions"])
    assert b["banner"] == "SYNTHETIC DEMO — NOT NASA OBSERVATIONS"


def test_overview_never_fills_missing_months(client, tmp_path):
    """Years with fewer than 10 valid months get no yearly number."""
    import io

    rows = ["date,region,variable,value,unit"]
    for y in range(2000, 2012):
        for m in range(1, 13):
            if y == 2005 and m > 6:
                continue  # only 6 valid months in 2005
            rows.append(f"{y}-{m:02d}-01,A,rain,{10 + m + (y % 5)},mm/month")
    csv = "\n".join(rows).encode()
    mapping = {
        "date": "date", "region": "region", "variable": "variable", "value": "value", "unit": "unit",
        "defaults": {"data_source": "test", "is_synthetic": False},
    }
    import json

    up = client.post(
        "/api/upload",
        files={"file": ("t.csv", io.BytesIO(csv), "text/csv")},
        data={"mapping": json.dumps(mapping), "dry_run": "false", "confirmed": "true"},
    )
    assert up.status_code == 200, up.text
    ds = up.json()["dataset"]["id"]
    b = client.get("/api/overview", params={"dataset_id": ds, "region": "A"}).json()
    y2005 = next(y for y in b["years"] if y["year"] == 2005)
    assert y2005["n_months"] == 6 and y2005["mean_z"] is None and y2005["mean_value"] is None
    assert b["matrix_values"][5][8] is None  # Sep 2005 stays missing


def test_snapshot_places_known_regions_and_lists_the_rest(package_client):
    b = package_client.get("/api/snapshot", params={"dataset_id": D, "year": 2015, "month": 7}).json()
    assert b["label"] == "July 2015" and b["banner"] == "SYNTHETIC DEMO — NOT NASA OBSERVATIONS"
    assert b["unlocated"]  # regions outside the India reference table are listed, never drawn
    assert all(isinstance(p["lon"], float) for p in b["points"])
    assert all(s["evidence"] for s in b["sentences"])
    assert package_client.get("/api/snapshot", params={"dataset_id": D, "year": 1500}).status_code == 422
    assert package_client.get("/api/snapshot", params={"dataset_id": D, "year": 2015, "month": 13}).status_code == 422
