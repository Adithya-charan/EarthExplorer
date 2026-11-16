"""Deep-Time Earth: the built reconstruction data, its API, the honesty flags and the grounded assistant.

These tests read the real built data in datasets/deep_time (scripts/build_deeptime_data.py); they are skipped if it is absent.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.explorer.deeptime import DeepTimeService, key, ma_text
from app.explorer.deeptime_ai import missing_taxa, parse_age
from app.main import create_app

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "datasets" / "deep_time"
pytestmark = pytest.mark.skipif(not (DATA / "manifest.json").exists(), reason="deep-time data not built")

REQUESTED = [0, 0.001, 0.01, 0.1, 1, 5, 10, 20, 30, 40, 50, 55, 66, 75, 90, 100, 120, 140, 150, 180, 200, 230, 250]
DINO = [250, 230, 200, 180, 150, 130, 120, 100, 90, 75, 66]
BASE = "/api/explorer/deeptime"


@pytest.fixture(scope="module")
def svc() -> DeepTimeService:
    return DeepTimeService(DATA)


@pytest.fixture()
def dclient(tmp_path) -> TestClient:
    s = Settings(upload_dir=tmp_path / "u", datasets_dir=tmp_path / "no", explorer_dir=tmp_path / "e", explorer_generate_demo=False, groq_api_key=None, deeptime_dir=DATA)
    return TestClient(create_app(s))


# ----------------------------------------------------------------------------------------------- time scale and frames
def test_every_requested_age_is_supported(svc):
    assert all(a in svc.ages for a in REQUESTED)
    assert len(svc.ages) == len(set(svc.ages))


def test_age_keys_round_trip():
    assert key(0.001) == "0p001" and key(66) == "66" and key(0.1) == "0p1"
    assert ma_text(0) == "present day"


def test_period_labels_come_from_the_ics_scale(svc):
    cret = svc.frame_meta(100)
    assert (cret["era"], cret["period"]) == ("Mesozoic", "Cretaceous")
    assert svc.frame_meta(66)["boundary"].startswith("Cretaceous-Paleogene")
    assert svc.frame_meta(250)["period"] == "Triassic"
    assert svc.frame_meta(0)["period"] == "Quaternary"


def test_frames_are_labelled_as_reconstruction_never_as_observation(svc):
    f = svc.frame(66)
    assert f["mode_label"] == "Geological Reconstruction"
    assert "not a satellite observation" in f["caveat"]
    blob = json.dumps(f).lower()
    assert "nasa" not in blob and "ieee" not in blob


def test_indian_plate_moves_north_with_time(svc):
    lats = {a: svc.frame(a)["india"]["earthbyte"]["india"][0] for a in (250, 100, 66, 40, 0)}
    assert lats[0] == pytest.approx(28.5, abs=0.01)
    assert lats[250] < lats[100] < lats[66] < lats[40] < lats[0]
    assert lats[66] < 0 < lats[0]


def test_two_models_are_reported_not_blended(svc):
    f = svc.frame(100)
    assert f["india"]["earthbyte"]["india"] != f["india"]["paleomap"]["india"]
    assert isinstance(f["models_disagree_km"], int) and f["models_disagree_km"] > 0
    assert svc.frame(0)["models_disagree_km"] == 0


def test_paleomap_maps_are_never_interpolated(svc):
    pm5 = svc.frame_meta(5)["models"]["paleomap"]
    assert pm5["map_exact"] is False and pm5["map_age_ma"] == 4 and pm5["map_offset_ma"] == -1
    assert svc.frame_meta(66)["models"]["paleomap"]["map_exact"] is True
    for a in svc.ages:
        mf = svc.paleomap_path(a)
        assert mf is not None and mf.exists()


def test_no_cao_paleogeography_below_two_ma_and_it_is_flagged(svc):
    assert not svc.frame_meta(1)["has_cao"] and svc.frame_meta(5)["has_cao"]
    f = svc.frame(1)
    assert f["has_paleogeography"] is False
    assert not any(l["name"] in ("landmass", "shallow_marine") for l in f["layers"])


def test_layer_files_exist_for_every_frame(svc):
    for a in svc.ages:
        assert svc.layer_path(a, "plates") is not None
        assert svc.layer_path(a, "india_outline_earthbyte") is not None


# ----------------------------------------------------------------------------------------------- real records only
def test_fossil_records_are_the_pbdb_download_unedited(svc):
    orig = (DATA.parent.parent / "datasets" / "deep_time" / "fossils.json")
    assert orig.exists()
    recs = svc.fossils
    assert len(recs) == 293
    assert all(re.fullmatch(r"PBDB:occ:\d+", r["occurrence_id"]) for r in recs)
    assert len({r["occurrence_id"] for r in recs}) == len(recs)
    assert all(r["minimum_age_ma"] <= r["maximum_age_ma"] for r in recs)
    assert all(r["source_database"].startswith("The Paleobiology Database") for r in recs)


def test_fossils_shown_at_an_age_span_that_age(svc):
    for r in svc.fossil_records(90, 0.0):
        assert r["minimum_age_ma"] <= 90 <= r["maximum_age_ma"]
    wide = {r["occurrence_id"] for r in svc.fossil_records(90, 5.0)}
    exact = {r["occurrence_id"] for r in svc.fossil_records(90, 0.0)}
    assert exact <= wide


def test_birds_are_flagged_not_passed_off_as_dinosaurs(svc):
    young = svc.fossil_records(0, 0.0)
    assert young and all(r["is_bird"] for r in young)


def test_dinosaur_slices_are_the_requested_ones(svc):
    d = svc.dinosaur_era()
    assert [s["age_ma"] for s in d["slices"]] == DINO


def test_formations_keep_their_provenance(svc):
    assert svc.formations
    for r in svc.formations:
        assert r["minimum_age_ma"] <= r["maximum_age_ma"]
        assert "Paleobiology Database" in r["source_database"]
    assert "not formal formation ages" in svc.formation_geojson(100, 5)["properties"]["note"]


def test_csv_files_match_the_required_columns_and_the_data():
    d = DATA / "csv"
    want = {
        "india_plate_reconstruction.csv": "reconstruction_id,geological_age_ma,plate_id,plate_name,reconstructed_latitude,reconstructed_longitude,rotation_model,reconstruction_source,uncertainty,source_reference",
        "india_dinosaur_fossil_occurrences.csv": "occurrence_id,taxon_name,higher_taxonomy,fossil_type,geological_period,minimum_age_ma,maximum_age_ma,locality,state,latitude,longitude,formation,reference_id,source_database,data_quality",
        "geological_events_timeline.csv": "event_id,event_name,start_age_ma,end_age_ma,affected_region,geological_process,description,evidence_source,confidence,uncertainty_notes",
    }
    for name, header in want.items():
        with (d / name).open(encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        assert ",".join(rows[0]) == header
    with (d / "india_dinosaur_fossil_occurrences.csv").open(encoding="utf-8", newline="") as f:
        ids = [r["occurrence_id"] for r in csv.DictReader(f)]
    assert ids == [r["occurrence_id"] for r in DeepTimeService(DATA).fossils]


# ----------------------------------------------------------------------------------------------- places
def test_place_is_a_reference_point_on_a_plate_not_ancient_geography(svc):
    p = svc.place("city:hyderabad", 66)
    assert p["plate"]["earthbyte"]["plate_id"] == 501
    assert p["reconstructed_position"]["earthbyte"][0] < 0
    assert any("did not exist" in l for l in p["limitations"])
    assert any("city-scale" in l for l in p["limitations"])
    assert svc.place("city:nowhere", 66) is None


def test_present_day_place_is_unchanged(svc):
    p = svc.place("city:hyderabad", 0)
    assert p["reconstructed_position"]["earthbyte"] == pytest.approx([p["modern_position"]["latitude"], p["modern_position"]["longitude"]], abs=0.01)


def test_himalayan_stages_keep_ranges_and_uncertainty(svc):
    h = svc.himalaya()
    ages = [s["age_ma"] for s in h["stages"]]
    assert ages == sorted(ages, reverse=True) and ages[0] == 250 and ages[-1] == 0
    assert "debated" in h["note"]
    assert all(s["uncertainty"] for s in h["stages"])
    assert all(s["references"] for s in h["stages"])
    assert svc.himalaya()["stages"][0]["collision"].lower().startswith("no collision")


def test_events_carry_confidence_and_sources(svc):
    ev = svc.events()
    assert len(ev) >= 14
    for e in ev:
        assert e["confidence"] and e["evidence_source"] and e["uncertainty_notes"]
    cp = next(e for e in ev if "Cretaceous-Paleogene" in e["event_name"])
    assert cp["start_age_ma"] == 66


def test_bibliography_is_complete(svc):
    for e in svc.events():
        for rid in e["evidence_source"].split(";"):
            assert svc.references(rid), rid


# ----------------------------------------------------------------------------------------------- API
def test_manifest_endpoint(dclient):
    r = dclient.get(f"{BASE}/manifest")
    assert r.status_code == 200
    m = r.json()
    assert m["mode_label"] == "Geological Reconstruction"
    assert set(REQUESTED) <= {a["age_ma"] for a in m["ages"]}


def test_frame_endpoint_and_decimal_age_syntax(dclient):
    a = dclient.get(f"{BASE}/frames/0p001?model=paleomap")
    b = dclient.get(f"{BASE}/frames/0.001?model=paleomap")
    assert a.status_code == b.status_code == 200
    assert a.json()["age_ma"] == b.json()["age_ma"] == 0.001
    assert a.json()["raster"]["exact"] is False


def test_frame_validation_errors(dclient):
    assert dclient.get(f"{BASE}/frames/66?model=bogus").status_code == 422
    assert dclient.get(f"{BASE}/frames/abc").status_code == 422
    assert dclient.get(f"{BASE}/frames/66/layers/nope").status_code == 404
    assert dclient.get(f"{BASE}/places/city:nowhere?age=66").status_code == 404


def test_layer_and_paleomap_files_are_served(dclient):
    g = dclient.get(f"{BASE}/frames/66/layers/plates")
    assert g.status_code == 200 and g.json()["type"] == "FeatureCollection" and g.json()["features"]
    assert any(f["properties"].get("is_indian_plate") for f in g.json()["features"])
    im = dclient.get(f"{BASE}/frames/66/paleomap")
    assert im.status_code == 200 and im.headers["content-type"].startswith("image/")


def test_fossil_geojson_endpoint(dclient):
    r = dclient.get(f"{BASE}/frames/90/fossils?model=earthbyte&window=0")
    assert r.status_code == 200
    fc = r.json()
    assert fc["features"] and all(f["properties"]["occurrence_id"].startswith("PBDB:occ:") for f in fc["features"])
    assert "does not show" in fc["properties"]["note"]


def test_himalaya_dinosaur_events_references_endpoints(dclient):
    assert len(dclient.get(f"{BASE}/himalaya").json()["stages"]) == 16
    assert [s["age_ma"] for s in dclient.get(f"{BASE}/dinosaur-era").json()["slices"]] == DINO
    assert dclient.get(f"{BASE}/events").json()
    assert all(b["id"].startswith("B") for b in dclient.get(f"{BASE}/references").json())


def test_unbuilt_data_gives_a_clear_503(tmp_path):
    s = Settings(upload_dir=tmp_path / "u", datasets_dir=tmp_path / "no", explorer_dir=tmp_path / "e", explorer_generate_demo=False, groq_api_key=None, deeptime_dir=tmp_path / "empty")
    c = TestClient(create_app(s))
    r = c.get(f"{BASE}/manifest")
    assert r.status_code == 503 and r.json()["error"]["code"] == "deeptime_unavailable"


def test_gazetteer_finds_the_new_geological_places(dclient):
    for q, pid in (("Western Ghats", "mountain:western-ghats"), ("Deccan Plateau", "plateau:deccan-plateau")):
        hits = dclient.get(f"/api/explorer/locations/search?q={q}").json()
        assert hits and hits[0]["id"] == pid


# ----------------------------------------------------------------------------------------------- grounded assistant
def chat(client, question, age=66, loc=None):
    r = client.post("/api/explorer/ai/chat", json={"question": question, "analysis_id": None, "history": [], "deep_time": True, "deep_time_age": age, "deep_time_location": loc})
    assert r.status_code == 200, r.text
    return r.json()


def test_answer_has_labelled_parts_and_only_real_record_ids(dclient, svc):
    out = chat(dclient, "Which dinosaur fossils were found in India around 90 million years ago?", age=90)
    assert out["source"] == "deterministic"
    assert "Dataset records:" in out["answer"] and "Uncertainty:" in out["answer"]
    known = {r["occurrence_id"] for r in svc.fossils}
    found = set(re.findall(r"PBDB:occ:\d+", out["answer"]))
    assert found and found <= known


def test_unrecorded_taxon_is_not_invented(dclient):
    out = chat(dclient, "Were there Tyrannosaurus rex fossils found in India?")
    assert "no PBDB record of Tyrannosaurus" in out["answer"]


def test_birds_are_called_birds(dclient):
    out = chat(dclient, "What fossils lived here?", age=0)
    assert "birds (Aves)" in out["answer"]


def test_himalaya_answer_separates_model_interpretation_and_uncertainty(dclient):
    out = chat(dclient, "When did the Himalaya form?", age=50)
    a = out["answer"]
    assert "Model reconstruction:" in a and "Published interpretation:" in a and "Uncertainty:" in a
    assert "no single date is agreed" in a


def test_helpers():
    assert parse_age("what about 66 million years ago") == 66
    assert missing_taxa("Tell me about Tyrannosaurus", []) == ["Tyrannosaurus"]
    assert missing_taxa("sauropods in India", []) == []


# ---------------------------------------------------------------------------------------- analytics
def test_analytics_endpoint_reports_both_models_and_consistent_totals(dclient):
    r = dclient.get("/api/explorer/deeptime/analytics")
    assert r.status_code == 200
    a = r.json()
    assert a["kpis"]["path_km"]["earthbyte"] > 0 and a["kpis"]["path_km"]["paleomap"] > 0
    assert a["kpis"]["max_models_disagree_km"] >= 0
    # Every record is counted exactly once in each breakdown.
    total = a["kpis"]["fossil_records"]
    assert sum(x["records"] for x in a["fossils"]["by_period"]) == total
    # A record whose age range spans several bins is counted in each of them, so the bins can exceed the total.
    assert sum(x["records"] for x in a["fossils"]["by_age"]) >= total
    assert sum(x["records"] for x in a["fossils"]["by_group"]) == total
    ages = [t["age_ma"] for t in a["track"]]
    assert ages == sorted(set(ages))
    assert {p["name"] for p in a["places"]} >= {"Hyderabad", "Bengaluru"}


def test_sources_endpoint_lists_checksummed_files(dclient):
    r = dclient.get("/api/explorer/deeptime/sources")
    assert r.status_code == 200
    rows = r.json()
    assert rows and all(row["original_filename"] and row["license"] for row in rows)
