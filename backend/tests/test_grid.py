"""Gridded NetCDF upload, per-cell frames and honest handling of gaps."""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
import xarray as xr


def make_nc(unit: str | None = "mm/hr", n_years: int = 4, with_gap: bool = True, name: str = "precip", extra_var: bool = False) -> bytes:
    times = pd.date_range("2018-01-01", periods=12 * n_years, freq="MS")
    lat = np.array([10.0, 11.0, 12.0])  # descending order is tested below by reversing
    lon = np.array([70.0, 71.0, 72.0, 73.0])
    rng = np.random.default_rng(1)
    base = np.arange(len(times))[:, None, None] * 0.01 + lat[None, :, None] * 0.1 + lon[None, None, :] * 0.0
    vals = (base + rng.normal(0, 0.001, base.shape)).astype("float32")
    if with_gap:
        vals[5, 1, 2] = np.nan
    attrs = {"units": unit} if unit else {}
    ds = xr.Dataset(
        {name: (("time", "lat", "lon"), vals, attrs)},
        coords={"time": times, "lat": ("lat", lat, {"units": "degrees_north"}), "lon": ("lon", lon, {"units": "degrees_east"})},
    )
    if extra_var:
        ds["other"] = (("time", "lat", "lon"), vals * 2)
    ds = ds.isel(lat=slice(None, None, -1))  # descending latitude on disk
    buf = io.BytesIO(ds.to_netcdf(engine="scipy"))
    return buf.getvalue()


def up(client, data: bytes, **form):
    return client.post("/api/upload-grid", files={"file": ("grid.nc", data, "application/x-netcdf")}, data=form)


def test_grid_upload_creates_series_and_frames(client):
    r = up(client, make_nc(), dataset_name="Test grid")
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["n_lat"], b["n_lon"], b["n_times"], b["unit"]) == (3, 4, 48, "mm/hr")
    ds = b["dataset_id"]
    reg = client.get("/api/regions", params={"dataset_id": ds}).json()
    assert reg["regions"][0]["geo"]["kind"] == "dataset_coordinates"
    assert reg["regions"][0]["geo"]["bbox"] == [69.5, 9.5, 73.5, 12.5]
    f = client.get("/api/grid", params={"dataset_id": ds, "month": "2018-06-01"}).json()
    assert f["lat"] == [10.0, 11.0, 12.0] and len(f["values"]) == 3 and len(f["values"][0]) == 4
    assert f["values"][1][2] is None  # the gap stays a gap (time index 5 = June)
    assert f["anomaly"] is not None and f["unit"] == "mm/hr"
    s = client.post("/api/story", json={"dataset_id": ds, "region": "Whole grid area", "start": "2019-01-01", "end": "2019-12-01"})
    assert s.status_code == 200 and s.json()["geo"]["kind"] == "dataset_coordinates"


def test_regional_mean_excludes_missing_cells_without_filling(client):
    ds = up(client, make_nc()).json()["dataset_id"]
    obs = client.get("/api/observations", params={"dataset_id": ds, "limit": 100}).json()
    assert obs["total"] == 48 and all(r["value"] is not None for r in obs["rows"][:10])
    assert "cos latitude" in obs["rows"][0]["transformation_note"]
    assert obs["provenance"]["status"] == "uploaded" and obs["provenance"]["is_synthetic"] is False


def test_unit_missing_is_reported_not_guessed(client):
    r = up(client, make_nc(unit=None)).json()
    assert r["unit"] == "unspecified"


def test_errors_are_clear(client):
    assert up(client, b"not a netcdf file at all").json()["error"]["code"] == "unreadable_grid_file"
    amb = up(client, make_nc(extra_var=True)).json()
    assert amb["error"]["code"] == "ambiguous_variable" and "other" in amb["error"]["message"]
    assert up(client, make_nc(extra_var=True), variable="other").status_code == 200
    assert up(client, make_nc(), variable="nope").json()["error"]["code"] == "variable_not_found"
    ds = up(client, make_nc()).json()["dataset_id"]
    assert client.get("/api/grid", params={"dataset_id": ds, "month": "1990-01-01"}).json()["error"]["code"] == "date_not_in_grid"
    assert client.get("/api/grid", params={"dataset_id": "synthetic-demo", "month": "2020-01-01"}).json()["error"]["code"] == "not_gridded"


def test_grid_survives_restart_and_delete_removes_it(client, settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    ds = up(client, make_nc()).json()["dataset_id"]
    again = TestClient(create_app(settings))
    assert again.get("/api/grid", params={"dataset_id": ds, "month": "2019-03-01"}).status_code == 200
    assert again.delete(f"/api/datasets/{ds}").status_code in (200, 204)
    assert not list(settings.upload_dir.glob(f"{ds}.*"))
