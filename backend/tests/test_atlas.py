"""India historical atlas: gazetteer, suggestions, boundaries, variables, statistics and ranking, against the real atlas on disk."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ATLAS = Path(__file__).resolve().parents[2] / "datasets" / "india_historical_atlas"
pytestmark = pytest.mark.skipif(not (ATLAS / "geographical_boundaries" / "index.json").exists() or not (ATLAS / "processed").exists(), reason="atlas not generated")


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    t = tmp_path_factory.mktemp("atlas")
    s = Settings(upload_dir=t / "u", datasets_dir=t / "n", explorer_dir=ATLAS / "processed", atlas_dir=ATLAS, explorer_generate_demo=False, groq_api_key=None)
    return TestClient(create_app(s))


def session(c: TestClient, q: str, sy: int = 2000, ey: int = 2020, **kw) -> dict:
    r = c.post("/api/explorer/session", json={"query": q, "start_year": sy, "end_year": ey, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_all_required_regions_are_loaded_and_labelled(client):
    ds = {d["id"]: d for d in client.get("/api/explorer/datasets").json()}
    for needed in ("ghsl-built-up-chennai", "ghsl-built-up-kolkata", "ghsl-built-up-delhi-ncr", "ghsl-built-up-kochi", "jrc-water-chilika-lake", "jrc-water-vembanad-lake", "ghsl-built-up-hyderabad", "worldcover-sundarbans-2021"):
        assert needed in ds, needed
    assert len(ds) >= 40
    # Every dataset is derived from an official satellite product; nothing generated is served.
    assert all(d["designation"] == "official_derived" and not d["is_synthetic"] and d["public_label"] == "Satellite Observations" for d in ds.values())


def test_suggestions_show_name_hierarchy_and_type(client):
    r = client.get("/api/explorer/locations/suggest", params={"q": "Bellan"}).json()
    assert r and r[0]["name"].startswith("Bellandur")
    assert r[0]["level"] and r[0]["hierarchy"]
    assert client.get("/api/explorer/locations/suggest", params={"q": "z"}).json() == []


def test_similar_names_are_disambiguated_by_hierarchy(client):
    r = client.get("/api/explorer/locations/suggest", params={"q": "Hyderabad"}).json()
    assert len({tuple(x["hierarchy"]) + (x["level"],) for x in r}) == len(r)


def test_boundaries_are_real_or_honestly_approximate(client):
    loc = session(client, "Bellandur Lake")["location"]
    b = client.get(f"/api/explorer/locations/{loc['id']}/boundary").json()
    assert b["geometry"] and b["status"] in {"derived_from_official_data", "authoritative_simplified"}
    assert b["area_km2"] and 0.5 < b["area_km2"] < 10
    pt = session(client, "Gachibowli")["location"]
    bp = client.get(f"/api/explorer/locations/{pt['id']}/boundary").json()
    assert bp["authoritative"] is False and bp["status"] in {"approximate_point", "approximate_bbox"}


def test_a_place_without_a_dataset_is_never_given_history(client):
    s = session(client, "Guwahati")
    assert s["status"] == "no_dataset" and s["dataset"] is None and s["latest"] is None
    assert s["insufficient"]["code"] == "no_dataset"


def test_a_parent_area_points_to_the_datasets_inside_it(client):
    s = session(client, "Tamil Nadu")
    assert s["status"] == "no_dataset"
    assert any(d["id"] == "ghsl-built-up-chennai" for d in s["nearby_datasets"])


def test_unknown_place_is_not_found(client):
    assert session(client, "Zzzzqqq")["status"] == "not_found"


def test_official_data_is_preferred_where_it_covers_the_period(client):
    s = session(client, "Hyderabad", 2000, 2020)
    assert s["status"] == "ready"
    assert s["dataset"]["designation"] == "official_derived"
    s2 = session(client, "Chennai", 2000, 2020)
    assert s2["status"] == "ready" and s2["dataset"]["public_label"] == "Satellite Observations"


def test_variables_are_analysed_separately_and_unknown_variables_are_rejected(client):
    ds = next(d for d in client.get("/api/explorer/datasets").json() if d["id"] == "worldcover-sundarbans-2021")
    keys = {v["key"] for v in ds["variables"]}
    assert {"mangrove", "water"} <= keys
    st = client.get(f"/api/explorer/datasets/{ds['id']}/statistics").json()
    assert {"mangrove", "water"} <= set(st["variables"])
    areas = {k: st["variables"][k]["series"][0]["area_ha"] for k in ("mangrove", "water")}
    assert areas["mangrove"] != areas["water"]  # each variable is measured on its own class
    bad = client.post("/api/explorer/analysis/detect-change", json={"dataset_id": "jrc-water-bellandur", "start_year": 1984, "end_year": 2021, "params": {"variable": "nonsense"}})
    assert bad.status_code == 422


def test_single_date_datasets_never_report_zero_change(client):
    ds = next(d for d in client.get("/api/explorer/datasets").json() if d["id"] == "worldcover-sundarbans-2021")
    r = client.post("/api/explorer/analysis/detect-change", json={"dataset_id": ds["id"], "start_year": 2000, "end_year": 2024}).json()
    assert r["outcome"] == "insufficient_data" and r["areas"].get("net_ha") in (None, "")


def test_statistics_endpoint_serves_measured_series(client):
    st = client.get("/api/explorer/datasets/jrc-water-bellandur/statistics").json()
    assert st["observations"] and st["variables"]
    water = st["variables"].get("water") or next(iter(st["variables"].values()))
    assert all(p["area_ha"] >= 0 for p in water["series"])


def test_metadata_catalogue_and_registry_endpoints(client):
    assert client.get("/api/explorer/datasets/jrc-water-bellandur/metadata").status_code == 200
    assert client.get("/api/explorer/catalogue").status_code == 200
    r = client.get("/api/explorer/source-registry")
    assert r.status_code in (200, 404)


def test_projection_extends_the_measured_trend_without_inventing_a_band(client):
    r = client.get("/api/explorer/datasets/ghsl-built-up-chennai/projection", params={"horizon": 2040}).json()
    assert r["available"] and r["n_observations"] == 3 and r["band"]
    last = r["projection"][-1]
    assert last["year"] == 2040 and last["low_ha"] <= last["central_ha"] <= last["high_ha"] <= r["footprint_ha"]
    assert last["central_ha"] > r["history"][-1]["area_ha"]  # Chennai's measured trend is upward
    two = client.get("/api/explorer/datasets/jrc-water-bellandur/projection").json()
    assert two["available"] and two["band"] is False and two["confidence"] == "low"
    assert "low_ha" not in two["projection"][-1]
    assert client.get("/api/explorer/datasets/ghsl-built-up-chennai/projection", params={"horizon": 2200}).status_code == 422
    one = client.get("/api/explorer/datasets/worldcover-sundarbans-2021/projection").json()
    assert one["available"] is False


def test_projection_map_renders_png_for_each_horizon(client):
    for yrs in (10, 20):
        r = client.get("/api/explorer/datasets/ghsl-built-up-chennai/projection-map.png", params={"years": yrs})
        assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert client.get("/api/explorer/datasets/jrc-water-bellandur/projection-map.png", params={"years": 10}).status_code == 200
    assert client.get("/api/explorer/datasets/worldcover-sundarbans-2021/projection-map.png").status_code == 422
