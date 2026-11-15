"""Earth Time Machine: locations, period validation, the three outcomes, ground truth, areas, AI fallbacks, bad data."""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import httpx
import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.config import Settings
from app.explorer import synthetic as syn
from app.explorer.datasets import DatasetService, inspect_file, validate_meta
from app.explorer.geoutil import area_ha, pixel_area_m2_per_row
from app.main import create_app

# Compact versions of the demo sites (coarser pixels, shorter record) so the suite stays quick.
BELL = dataclasses.replace(
    syn.SITES[0], res_deg=0.0009, first_year=2005, last_year=2015, gap_months=[(2008, m) for m in range(4, 9)],
    events=[
        syn.Event("encroachment", 2007.0, 2013.0, -75, -5, note="shore lobe built over"),
        syn.Event("drying", 2008.0, 2014.0, 135, 185, note="arm dries"),
        syn.Event("new_pond", 2010.4, 2010.4, centre_m=(1500, 850), radius_m=190),
    ],
)
HUSSAIN = dataclasses.replace(syn.SITES[1], res_deg=0.0009, first_year=2005, last_year=2015)
CHILIKA = dataclasses.replace(syn.SITES[2], res_deg=0.0012)
STABLE_MONTHLY = dataclasses.replace(syn.SITES[0], id="stable-monthly", name="Stable monthly lake (simulated)", res_deg=0.0009, first_year=2005, last_year=2012, events=[], gap_months=[], seed=5)


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("explorer")
    syn.generate_all(d, sites=[BELL, HUSSAIN, CHILIKA, STABLE_MONTHLY])
    return d


@pytest.fixture()
def ex_client(tmp_path, data_dir) -> TestClient:
    s = Settings(upload_dir=tmp_path / "u", datasets_dir=tmp_path / "none", explorer_dir=data_dir, explorer_generate_demo=False, groq_api_key=None)
    return TestClient(create_app(s))


def detect(c, ds, a, b, **kw):
    r = c.post("/api/explorer/analysis/detect-change", json={"dataset_id": ds, "start_year": a, "end_year": b, **kw})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------------ locations / session
def test_location_search_finds_demo_places_and_rejects_nonsense(ex_client):
    r = ex_client.get("/api/explorer/locations/search", params={"q": "Bellandur Lake Bengaluru", "online": False})
    assert r.status_code == 200 and r.json()[0]["name"].startswith("Bellandur")
    assert 12.8 < r.json()[0]["lat"] < 13.1
    assert ex_client.get("/api/explorer/locations/search", params={"q": "qqzzxx nowhere land", "online": False}).json() == []


def test_session_ready_no_dataset_and_not_found(ex_client):
    ok = ex_client.post("/api/explorer/session", json={"query": "Bellandur Lake", "start_year": 2005, "end_year": 2015, "online": False}).json()
    assert ok["status"] == "ready" and ok["dataset"]["is_synthetic"] is True and ok["simulated_label"]
    latest = ok["latest"]
    assert latest["label"] == "Latest available observation" and "not live" in latest["note"].lower()
    assert {"date", "source", "spatial_resolution_m", "quality", "historical_coverage"} <= latest.keys()
    amazon = ex_client.post("/api/explorer/session", json={"query": "Amazon Rainforest", "start_year": 2000, "end_year": 2020, "online": False}).json()
    assert amazon["status"] == "no_dataset" and amazon["location"]["lat"] < 0 and amazon["insufficient"]["code"] == "no_dataset"
    missing = ex_client.post("/api/explorer/session", json={"query": "qqzzxx nowhere land", "start_year": 2000, "end_year": 2020, "online": False}).json()
    assert missing["status"] == "not_found" and missing["examples"] and missing["location"] is None


def test_period_validation_explains_unsupported_ranges(ex_client):
    out = ex_client.post("/api/explorer/session", json={"query": "Bellandur", "start_year": 1990, "end_year": 1995, "online": False}).json()
    assert out["status"] == "period_unsupported" and "2005" in out["message"] and out["insufficient"]["suggested_period"]
    clip = ex_client.post("/api/explorer/session", json={"query": "Bellandur", "start_year": 1995, "end_year": 2010, "online": False}).json()
    assert clip["status"] == "ready" and clip["period"]["status"] == "clipped" and clip["period"]["effective"] == {"start_year": 2005, "end_year": 2010}
    bad = ex_client.post("/api/explorer/session", json={"query": "Bellandur", "start_year": 2010, "end_year": 2010})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_period"
    assert ex_client.post("/api/explorer/session", json={"start_year": 2000, "end_year": 2010}).status_code == 422


# ----------------------------------------------------------------------------------- outcomes
def test_outcome_a_matches_ground_truth(ex_client, data_dir):
    s = detect(ex_client, "bellandur-synthetic", 2005, 2015)
    assert s["outcome"] == "change_detected" and s["analysis_id"]
    truth = json.loads((data_dir / "bellandur-synthetic" / "ground_truth.json").read_text())
    a = s["areas"]
    assert a["lost_ha"] == pytest.approx(truth["loss_ha"], rel=0.2)
    pond = np.pi * 190**2 / 10_000
    assert a["gained_ha"] == pytest.approx(pond, rel=0.35)
    kinds = [h["kind"] for h in s["hotspots"]]
    assert kinds.count("loss") >= 2 and "gain" in kinds
    se = [h for h in s["hotspots"] if h["kind"] == "loss" and h["centroid"]["lat"] < BELL.lat and h["centroid"]["lon"] > BELL.lon]  # the built-in encroachment
    assert se and se[0]["area_ha"] > 5
    ne = [h for h in s["hotspots"] if h["kind"] == "gain"][0]  # the built-in pond, north-east of the centre
    assert ne["centroid"]["lat"] > BELL.lat and ne["centroid"]["lon"] > BELL.lon
    assert s["most_affected"]["kind"] == "loss" and s["trend"]["direction"] == "decreasing"
    assert s["progression"][0]["year"] == 2005 and s["progression"][-1]["cumulative_loss_ha"] == pytest.approx(a["lost_ha"], rel=0.15)
    assert s["confidence"] in {"high", "medium"} and s["limitations"] and "SIMULATED" in s["limitations"][0]


def test_outcome_b_stable_lake_is_not_reported_as_change(ex_client):
    s = detect(ex_client, "hussain-sagar-synthetic", 2005, 2015)
    assert s["outcome"] == "no_clear_change" and s["hotspots"] == []
    assert "No clear change" in s["headline"] and s["what_was_analysed"] and s["areas"]["water_start_ha"] > 0
    assert abs(s["areas"]["pct_net_change"]) < 3


def test_seasonal_cycle_alone_is_not_a_permanent_change(ex_client):
    s = detect(ex_client, "stable-monthly", 2005, 2012)
    assert s["outcome"] == "no_clear_change"
    assert s["areas"]["seasonal_amplitude_pct"] and s["areas"]["seasonal_amplitude_pct"] > 5  # the seasons clearly vary...
    assert any("between seasons" in x for x in s["limitations"])  # ...and the result says so


def test_outcome_c_sparse_data_never_says_no_change(ex_client):
    s = detect(ex_client, "chilika-synthetic", 2014, 2019)
    assert s["outcome"] == "insufficient_data" and "No clear change" not in s["headline"]
    ins = s["insufficient"]
    assert "38%" in " ".join(ins["missing"]) and ins["suggested_period"] == {"start_year": 2016, "end_year": 2019}
    assert ins["available_dates"] == ["2016", "2019"]
    ok = detect(ex_client, "chilika-synthetic", 2016, 2019)  # the suggestion works and is honest about thin evidence
    assert ok["outcome"] in {"no_clear_change", "change_detected"} and ok["confidence"] != "high"


def test_outcome_c_when_a_period_has_too_few_same_season_observations(ex_client):
    s = detect(ex_client, "bellandur-synthetic", 2005, 2015, params={"min_valid_obs_monthly": 12})
    assert s["outcome"] == "insufficient_data" and "at least 12" in s["insufficient"]["reason"]


def test_missing_months_are_never_interpolated(ex_client):
    obs = ex_client.get("/api/explorer/datasets/bellandur-synthetic/observations").json()
    dates = {o["date"] for o in obs}
    assert all(f"2008-{m:02d}-01" not in dates for m in range(4, 9))
    r = ex_client.get("/api/explorer/datasets/bellandur-synthetic/observations/2008-05-01/layer.png")
    assert r.status_code == 404 and "never interpolated" in r.json()["error"]["message"]
    s = detect(ex_client, "bellandur-synthetic", 2008, 2015)  # a window with a gap still analyses from what exists
    assert s["outcome"] in {"change_detected", "insufficient_data"}


def test_different_temporal_resolutions_coexist(ex_client):
    infos = {d["id"]: d for d in ex_client.get("/api/explorer/datasets").json()}
    assert infos["bellandur-synthetic"]["temporal_resolution"] == "monthly" and infos["hussain-sagar-synthetic"]["temporal_resolution"] == "yearly"
    assert infos["chilika-synthetic"]["observation_count"] == 3 and infos["bellandur-synthetic"]["resolution_m"] != infos["chilika-synthetic"]["resolution_m"]


def test_thresholds_are_configurable(ex_client):
    strict = detect(ex_client, "bellandur-synthetic", 2005, 2015, params={"min_change_pct": 90})
    assert strict["outcome"] == "no_clear_change" and strict["thresholds"]["min_change_pct"] == 90


# ------------------------------------------------------------------------------ layers / geometry
def test_layers_and_hotspot_geometry(ex_client):
    s = detect(ex_client, "bellandur-synthetic", 2005, 2015)
    aid = s["analysis_id"]
    for name in ("difference.png", "before.png", "after.png"):
        r = ex_client.get(f"/api/explorer/analysis/{aid}/layers/{name}")
        assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    tif = ex_client.get(f"/api/explorer/analysis/{aid}/layers/difference.tif")
    with MemoryFile(tif.content).open() as src:
        arr = src.read(1)
        assert src.crs.to_epsg() == 4326 and {3, 4} <= set(np.unique(arr).tolist())
    fc = ex_client.get(f"/api/explorer/analysis/{aid}/hotspots").json()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == len(s["hotspots"])
    for h in s["hotspots"]:  # polygon area measured in UTM agrees with the pixel-area sum
        assert h["geometry_area_ha"] == pytest.approx(h["area_ha"], rel=0.12)
    assert all(f["geometry"]["type"] in {"Polygon", "MultiPolygon"} for f in fc["features"])
    assert ex_client.get(f"/api/explorer/analysis/{aid}/layers/nope.png").status_code == 404
    assert ex_client.get("/api/explorer/analysis/deadbeef/hotspots").status_code == 404
    obs = ex_client.get("/api/explorer/datasets/bellandur-synthetic/observations").json()[10]["date"]
    assert ex_client.get(f"/api/explorer/datasets/bellandur-synthetic/observations/{obs}/layer.png").status_code == 200


def test_pixel_areas_use_geodesic_not_degrees():
    tf = from_origin(77.6, 13.0, 0.0003, 0.0003)
    rows = pixel_area_m2_per_row(tf, 10, CRS.from_epsg(4326))
    expect = (0.0003 * 111_320 * np.cos(np.radians(12.998))) * (0.0003 * 110_700)
    assert rows[0] == pytest.approx(expect, rel=0.01) and rows[0] != pytest.approx(0.0003**2)
    assert rows[0] < rows[-1]  # row 0 is the northern edge; pixels shrink slightly toward the pole
    assert area_ha(np.ones((10, 10), bool), rows) == pytest.approx(rows.sum() * 10 / 1e4)
    proj = pixel_area_m2_per_row(from_origin(500000, 1000000, 30, 30), 5, CRS.from_epsg(32643))
    assert proj[0] == pytest.approx(900.0)


# ------------------------------------------------------------------------------------ bad data
def test_invalid_raster_is_skipped_and_reported(tmp_path, data_dir):
    d = tmp_path / "ex"
    shutil.copytree(data_dir / "hussain-sagar-synthetic", d / "hussain-sagar-synthetic")
    (d / "hussain-sagar-synthetic" / "observations" / "2005.tif").write_bytes(b"this is not a tiff")
    svc = DatasetService(d)
    ds = svc.get("hussain-sagar-synthetic")
    from app.explorer.change import ChangeDetectionService
    res = ChangeDetectionService(svc).detect(ds, 2005, 2015)
    summary = getattr(res, "summary", res)
    assert summary.outcome == "insufficient_data"  # the broken 2005 file leaves the start of the period without usable data
    assert "could not be read" in " ".join(summary.insufficient.missing + [summary.insufficient.reason]) or "2005" in summary.insufficient.reason
    s2 = getattr(ChangeDetectionService(svc).detect(ds, 2006, 2015), "summary")
    assert s2.outcome in {"no_clear_change", "change_detected"}
    c = TestClient(create_app(Settings(upload_dir=tmp_path / "u", datasets_dir=tmp_path / "n", explorer_dir=d, explorer_generate_demo=False)))
    assert c.get("/api/explorer/datasets/hussain-sagar-synthetic/observations/2005-12-01/layer.png").status_code == 422


def test_broken_dataset_folder_does_not_stop_the_others(tmp_path, data_dir):
    d = tmp_path / "ex"
    shutil.copytree(data_dir / "chilika-synthetic", d / "chilika-synthetic")
    (d / "broken").mkdir()
    (d / "broken" / "dataset.json").write_text(json.dumps({"id": "broken", "name": "x"}))
    svc = DatasetService(d)
    assert [x.id for x in svc.list()] == ["chilika-synthetic"] and "broken" in svc.rejected


def test_metadata_validation_and_file_inspection(tmp_path, data_dir):
    assert validate_meta({"id": "x"})  # missing keys
    good = json.loads((data_dir / "chilika-synthetic" / "dataset.json").read_text())
    assert validate_meta(good) == []
    bad = dict(good, bbox=[10, 10, 5, 5])
    assert any("bbox" in p for p in validate_meta(bad))
    tif = inspect_file(data_dir / "chilika-synthetic" / "observations" / "2016.tif")
    assert tif["valid"] and tif["kind"] == "raster" and tif["crs"] == "EPSG:4326" and tif["tags"]["SYNTHETIC"] == "true"
    assert inspect_file(data_dir / "chilika-synthetic" / "dataset.json")["kind"] == "metadata"
    junk = tmp_path / "x.tif"
    junk.write_bytes(b"nope")
    assert inspect_file(junk)["valid"] is False
    csv_ok = tmp_path / "p.csv"
    csv_ok.write_text("lon,lat,class\n85.3,19.7,2\n")
    assert inspect_file(csv_ok)["valid"] and inspect_file(csv_ok)["rows"] == 1
    gj = tmp_path / "w.geojson"
    gj.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    assert inspect_file(gj)["valid"] is False


def test_geojson_and_csv_observations_share_the_interface(tmp_path):
    root = tmp_path / "vec"
    obs = root / "observations"
    obs.mkdir(parents=True)
    poly = lambda w: {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"class": "water"}, "geometry": {"type": "Polygon", "coordinates": [[[10.0, 50.0], [10.0 + w, 50.0], [10.0 + w, 50.05], [10.0, 50.05], [10.0, 50.0]]]}}]}
    (obs / "2001.geojson").write_text(json.dumps(poly(0.04)))
    (obs / "2002.geojson").write_text(json.dumps(poly(0.02)))
    meta = {"id": "vec", "name": "Vector lake", "temporal_resolution": "yearly", "bbox": [10.0, 50.0, 10.05, 50.05], "resolution_deg": 0.001, "crs": "EPSG:4326", "coverage": {"start": "2001-06-01", "end": "2002-06-01"},
            "observations": [{"date": "2001-06-01", "file": "observations/2001.geojson"}, {"date": "2002-06-01", "file": "observations/2002.geojson"}]}
    (root / "dataset.json").write_text(json.dumps(meta))
    svc = DatasetService(tmp_path)
    ds = svc.get("vec")
    a, b = (svc.read(ds, o) for o in ds.observations)
    assert (a == 2).sum() > (b == 2).sum() > 0 and a.shape == (ds.height, ds.width)


# ------------------------------------------------------------------------------------------ AI
def test_explain_without_key_is_a_deterministic_report_from_measurements(ex_client):
    s = detect(ex_client, "bellandur-synthetic", 2005, 2015)
    e = ex_client.post(f"/api/explorer/analysis/{s['analysis_id']}/explain").json()
    assert e["source"] == "deterministic" and "GROQ_API_KEY" in e["notice"]
    assert "SIMULATED" in e["text"] and f"{s['areas']['lost_ha']:,.1f}" in e["text"] and "cannot tell you" in e["text"]
    assert "live" not in e["text"].lower() and "caused by" not in e["text"].lower()


def test_chat_rules_answer_from_numbers_and_never_claim_causes(ex_client):
    aid = detect(ex_client, "bellandur-synthetic", 2005, 2015)["analysis_id"]
    where = ex_client.post("/api/explorer/ai/chat", json={"question": "Where did it change?", "analysis_id": aid}).json()
    assert "ha of water lost" in where["answer"] and where["source"] == "deterministic"
    why = ex_client.post("/api/explorer/ai/chat", json={"question": "Why did the lake shrink?", "analysis_id": aid}).json()
    assert "not why" in why["answer"] and "Possible factors" in why["answer"]
    nothing = ex_client.post("/api/explorer/ai/chat", json={"question": "hello"}).json()
    assert "analysis first" in nothing["answer"]
    insufficient = detect(ex_client, "chilika-synthetic", 2014, 2019)
    assert insufficient["analysis_id"] is None


def _groq_client(tmp_path, data_dir, handler):
    s = Settings(upload_dir=tmp_path / "u", datasets_dir=tmp_path / "n", explorer_dir=data_dir, explorer_generate_demo=False, groq_api_key="test-key-not-real", groq_model="test-model")
    return TestClient(create_app(s, ai_transport=httpx.MockTransport(handler)))


def test_groq_tool_loop_uses_backend_tools(tmp_path, data_dir):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["authorization"] == "Bearer test-key-not-real"
        if not any(m["role"] == "tool" for m in body["messages"]):
            call = {"id": "c1", "type": "function", "function": {"name": "get_hotspots", "arguments": "{}"}}
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}]})
        tool_msg = next(m for m in body["messages"] if m["role"] == "tool")
        assert "hotspots" in json.loads(tool_msg["content"])
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Water was lost on the south-eastern shore."}}]})

    c = _groq_client(tmp_path, data_dir, handler)
    aid = detect(c, "bellandur-synthetic", 2005, 2015)["analysis_id"]
    e = c.post(f"/api/explorer/analysis/{aid}/explain").json()
    assert e["source"] == "groq" and e["model"] == "test-model" and e["tools_used"] == ["get_hotspots"]
    assert e["text"].startswith("SIMULATED")  # synthetic data is always labelled, even if the model forgets
    assert seen[0]["tools"] and "Never claim a cause" in seen[0]["messages"][0]["content"]
    chat = c.post("/api/explorer/ai/chat", json={"question": "where?", "analysis_id": aid}).json()
    assert chat["source"] == "groq"


@pytest.mark.parametrize("failure", ["connect", "timeout", "http500", "empty"])
def test_groq_failures_fall_back_without_breaking(tmp_path, data_dir, failure):
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "connect":
            raise httpx.ConnectError("network down")
        if failure == "timeout":
            raise httpx.ReadTimeout("slow network")
        if failure == "http500":
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": ""}}]})

    c = _groq_client(tmp_path, data_dir, handler)
    aid = detect(c, "bellandur-synthetic", 2005, 2015)["analysis_id"]
    e = c.post(f"/api/explorer/analysis/{aid}/explain")
    assert e.status_code == 200 and e.json()["source"] == "deterministic" and "could not be reached" in e.json()["notice"]
    assert "test-key-not-real" not in e.text
    assert c.post("/api/explorer/ai/chat", json={"question": "how much?", "analysis_id": aid}).json()["source"] == "deterministic"


def test_generator_is_reproducible_and_marked_simulated(data_dir):
    meta = json.loads((data_dir / "bellandur-synthetic" / "dataset.json").read_text())
    assert meta["is_synthetic"] is True and "SIMULATED" in meta["simulated_label"]
    targets = {t["name"] for t in meta["real_dataset_targets"]}
    assert any("JRC" in t for t in targets) and any("Sentinel-2" in t for t in targets) and any("Landsat" in t for t in targets)
    with rasterio.open(data_dir / "bellandur-synthetic" / "observations" / "2010-09.tif") as src:
        assert src.dtypes[0] == "uint8" and src.nodata == 255 and src.tags()["SYNTHETIC"] == "true"
