"""Spatial availability is derived only from real latitude/longitude columns in the loaded data."""

from __future__ import annotations

from .conftest import DEMO
from .test_api import MAPPING, post_upload

HEADER = "date,region,variable,value,unit,data_source,is_synthetic,lat,lon\n"


def _csv(rows: list[tuple[str, str, str]]) -> str:
    """rows: (month, lat, lon); lat/lon may be blank."""
    return HEADER + "\n".join(f"2020-{m}-01,Site 1,Gauge,{i + 1.0},mm,my lab,false,{lat},{lon}" for i, (m, lat, lon) in enumerate(rows)) + "\n"


MAPPING_WITH_COORDS = {**MAPPING, "optional": {"latitude": "lat", "longitude": "lon"}}


def test_coordinates_in_an_upload_enable_the_spatial_summary(client):
    content = _csv([("01", "10.5", "-20.25"), ("02", "11.5", "-21.0"), ("03", "12.0", "-22.5"), ("04", "", "-23.0"), ("05", "13.0", "")])
    r = post_upload(client, content, mapping=MAPPING_WITH_COORDS, dry_run=False)
    assert r.status_code == 200, r.text
    dataset_id = r.json()["dataset"]["id"]

    meta = client.get("/api/metadata", params={"dataset_id": dataset_id}).json()
    assert {"latitude", "longitude"} <= set(meta["optional_fields_present"])
    spatial = meta["spatial"]
    assert spatial["available"] is True
    # only rows with BOTH coordinates count; blanks are not treated as 0
    assert spatial["n_points_with_coordinates"] == 3
    assert spatial["latitude_range"] == [10.5, 12.0]
    assert spatial["longitude_range"] == [-22.5, -20.25]
    # the note must not claim to know what the coordinates mean
    assert "does not know" in spatial["note"]

    # the coordinates are served back unchanged in the observations
    rows = client.get("/api/observations", params={"dataset_id": dataset_id}).json()["rows"]
    assert rows[0]["latitude"] == 10.5 and rows[0]["longitude"] == -20.25
    assert rows[3]["latitude"] is None  # missing stays missing


def test_demo_dataset_still_reports_no_spatial_data(client):
    spatial = client.get("/api/metadata", params={"dataset_id": DEMO}).json()["spatial"]
    assert spatial["available"] is False and spatial["n_points_with_coordinates"] == 0
    assert "no latitude/longitude" in spatial["note"]


def test_out_of_range_latitude_is_reported_and_not_plotted(client):
    content = _csv([("01", "95.0", "10.0"), ("02", "11.0", "10.0"), ("03", "12.0", "10.0")])
    r = post_upload(client, content, mapping=MAPPING_WITH_COORDS, dry_run=True)
    codes = {i["code"] for i in r.json()["quality"]["issues"]}
    assert "invalid_latitude" in codes
