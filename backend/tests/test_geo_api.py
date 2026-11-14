"""Earth Explorer API tests. The Natural Earth atlas is read from disk (tests skip if it is not installed);
the geocoder and elevation tiles are replaced by a fake network, so nothing here touches the internet."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import BACKEND_DIR, Settings
from app.geo.naturalearth import Gazetteer
from app.main import create_app
from tests.geo_helpers import EIFFEL, NOMINATIM_HOST, TILE_HOST, FakeNet, terrarium_png

DATA_DIR = BACKEND_DIR / "data" / "naturalearth"
needs_atlas = pytest.mark.skipif(not Gazetteer(DATA_DIR).available, reason="Natural Earth data not installed (run scripts/fetch_natural_earth.py)")


def make_settings(tmp_path, **kw) -> Settings:
    base = dict(
        upload_dir=tmp_path / "uploads",
        demo_csv_path=BACKEND_DIR / "data" / "earth_science_trend_demo.csv",
        nominatim_url=f"https://{NOMINATIM_HOST}",
        terrain_tile_url=f"https://{TILE_HOST}/{{z}}/{{x}}/{{y}}.png",
        geocoder_min_interval_s=0.0,
        geo_warm_on_start=False,
    )
    base.update(kw)
    return Settings(**base)


@pytest.fixture()
def net() -> FakeNet:
    return FakeNet()


@pytest.fixture()
def geo(tmp_path, net) -> TestClient:
    return TestClient(create_app(make_settings(tmp_path), geo_transport=net.transport()))


def resolve(client, *items, online=False):
    body = {"online": online, "items": [dict(ref=f"r{i}", **it) for i, it in enumerate(items)]}
    r = client.post("/api/locations/resolve", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def preview_body(ids, **prefs):
    return {"locations": [{"location_id": i} for i in ids], "preferences": prefs}


def confirm_body(preview_json, ids, confirmed=True, **prefs):
    body = preview_body(ids, **prefs)
    body["confirmation_token"] = preview_json["confirmation_token"]
    body["confirmed"] = confirmed
    return body


# ============================================================================================ health
def test_health_reports_geo_status_without_breaking_existing_fields(geo):
    d = geo.get("/api/health").json()
    assert d["status"] == "ok" and "datasets_loaded" in d and d["uses_external_ai"] is False
    assert d["geo"]["geocoder"]["provider"] == "OpenStreetMap Nominatim"
    assert set(d["geo"]["reference_atlas"]["layers_installed"]) >= {"countries", "admin1", "places"}


def test_missing_reference_atlas_is_reported_clearly(tmp_path, net):
    empty = TestClient(create_app(make_settings(tmp_path, geo_data_dir=tmp_path / "nothing"), geo_transport=net.transport()))
    assert empty.get("/api/health").json()["geo"]["reference_atlas"]["available"] is False
    r = empty.get("/api/geography/boundaries")
    assert r.status_code == 503 and r.json()["error"]["code"] == "geo_data_missing"
    # name search still works through the geocoder when the atlas is absent, and says what was skipped
    net.search_results["Eiffel Tower"] = [EIFFEL]
    d = empty.get("/api/geocode", params={"q": "Eiffel Tower"}).json()
    assert [c["id"] for c in d["candidates"]] == ["osm:W5013364"]
    assert d["sources"]["natural_earth"] == "unavailable"
    assert any(m["code"] == "geo_data_missing" for m in d["messages"])


# ========================================================================================== geocode
@needs_atlas
def test_geocode_springfield_lists_every_place_with_context(geo):
    d = geo.get("/api/geocode", params={"q": "Springfield", "online": "false"}).json()
    names = [c["display_name"] for c in d["candidates"]]
    assert len(names) >= 3
    assert all(n.startswith("Springfield, ") and "United States" in n for n in names)
    assert len(set(names)) == len(names)  # distinguishable by state
    assert all(c["provider"] == "natural_earth" for c in d["candidates"])
    assert "Natural Earth" in " ".join(d["attributions"])


@needs_atlas
def test_geocode_georgia_offers_the_country_and_the_us_state(geo):
    d = geo.get("/api/geocode", params={"q": "Georgia", "online": "false"}).json()
    by_class = {c["feature_class"]: c for c in d["candidates"]}
    assert set(by_class) >= {"country", "state_province"}
    assert by_class["country"]["id"] == "ne:admin0:GEO"
    assert by_class["state_province"]["context"]["country"] == "United States of America"
    assert by_class["state_province"]["display_name"] == "Georgia (state), United States of America"


def test_geocode_accepts_coordinates_and_rejects_impossible_ones(geo):
    d = geo.get("/api/geocode", params={"q": "48.8584, 2.2945"}).json()
    (c,) = d["candidates"]
    assert c["id"] == "coord:48.858400,2.294500" and c["provider"] == "user" and c["position_kind"] == "user_supplied"
    bad = geo.get("/api/geocode", params={"q": "95, 200"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_coordinates"


def test_geocode_validates_its_input(geo):
    assert geo.get("/api/geocode").status_code == 422
    assert geo.get("/api/geocode", params={"q": "x" * 201}).status_code == 422
    assert geo.get("/api/geocode", params={"q": "Paris", "language": "not a language"}).status_code == 422


def test_suggest_mode_never_calls_the_online_geocoder(geo, net):
    geo.get("/api/geocode", params={"q": "Spring", "suggest": "true"})
    assert net.geocoder_calls() == []


# ========================================================================================== resolve
@needs_atlas
def test_ambiguous_name_is_never_resolved_on_the_users_behalf(geo):
    # Fiji is both a country and an island group; Hyderabad is in India and in Pakistan.
    d = resolve(geo, {"query": "Georgia"}, {"query": "Springfield"}, {"query": "Fiji"}, {"query": "Hyderabad"})
    assert d["all_resolved"] is False
    assert {c["id"] for c in d["results"][2]["candidates"]} >= {"ne:admin0:FJI"}
    assert {c["context"]["country"] for c in d["results"][3]["candidates"]} >= {"India", "Pakistan"}
    for res in d["results"]:
        assert res["status"] == "ambiguous" and res["resolved"] is None and len(res["candidates"]) >= 2
        assert any(m["code"] == "ambiguous" for m in res["messages"])


@needs_atlas
def test_choosing_a_candidate_resolves_it_and_records_that_the_user_chose(geo):
    first = resolve(geo, {"query": "Georgia"})["results"][0]
    state = next(c for c in first["candidates"] if c["feature_class"] == "state_province")
    chosen = resolve(geo, {"candidate_id": state["id"]})["results"][0]
    assert chosen["status"] == "resolved"
    loc = chosen["resolved"]
    assert loc["id"] == state["id"] and loc["resolution"] == "user_selected"
    assert loc["context"]["country"] == "United States of America" and loc["geometry_type"] in ("Polygon", "MultiPolygon")
    assert loc["geometry_info"]["quality"] == "generalized" and loc["geometry_info"]["generalization"]


@needs_atlas
def test_unique_offline_matches_resolve_with_their_source_and_limits(geo):
    d = resolve(geo, {"query": "Mount Everest"}, {"query": "Pacific Ocean"}, {"candidate_id": "ne:admin0:FJI"})
    assert d["all_resolved"] is True
    everest, pacific, fiji = (r["resolved"] for r in d["results"])
    assert everest["feature_class"] == "mountain_peak" and everest["resolution"] == "only_match"
    assert "summit" in everest["point"]["note"].lower()  # the note says the Natural Earth point can be km from the summit
    assert pacific["feature_class"] == "ocean_sea" and pacific["point"]["kind"] in ("label_point", "representative_point")
    assert fiji["bbox"]["crosses_antimeridian"] is True and fiji["bbox"]["east"] > 180
    for loc in (everest, pacific, fiji):
        assert loc["source"]["provider"] == "natural_earth" and loc["source"]["license"] == "Public domain"
        assert loc["validation"]["status"] in ("validated", "validated_with_limits") and loc["validation"]["limitations"]


@needs_atlas
def test_geographic_poles_are_built_in_defined_points(geo):
    south = resolve(geo, {"query": "South Pole"})["results"][0]
    loc = south["resolved"] if south["status"] == "resolved" else None
    if loc is None:  # "South Pole" can also match the magnetic pole entry: the choice is then the user's
        pick = next(c for c in south["candidates"] if c["id"] == "builtin:geographic-south-pole")
        loc = resolve(geo, {"candidate_id": pick["id"]})["results"][0]["resolved"]
    assert loc["id"] == "builtin:geographic-south-pole" and loc["point"]["latitude"] == -90.0
    assert loc["source"]["provider"] == "builtin" and loc["geometry"] is None


def test_unknown_names_are_not_found_and_say_how_to_fix_it(geo):
    r = resolve(geo, {"query": "Zzyzxqwv"})["results"][0]
    assert r["status"] == "not_found" and r["resolved"] is None
    assert r["messages"][0]["code"] == "no_match" and "coordinates" in r["messages"][0]["text"]


def test_custom_coordinates_are_plotted_exactly_and_labelled_unverified(geo):
    r = resolve(geo, {"coordinates": {"lat": -17.7134, "lon": 178.065, "label": "My spot"}}, {"query": "35.5, -170.25"})
    a, b = (x["resolved"] for x in r["results"])
    assert (a["point"]["latitude"], a["point"]["longitude"]) == (-17.7134, 178.065) and a["name"] == "My spot"
    assert (b["point"]["latitude"], b["point"]["longitude"]) == (35.5, -170.25)
    for loc in (a, b):
        assert loc["validation"]["status"] == "user_supplied_unverified" and loc["source"]["provider"] == "user"
        assert loc["geometry"] is None and loc["point"]["kind"] == "user_supplied"


def test_invalid_coordinates_are_reported_per_item_not_as_a_crash(geo):
    d = resolve(geo, {"query": "91.5, 10"}, {"coordinates": {"lat": 0, "lon": 181}}, {"coordinates": {"lat": 10, "lon": 10}})
    assert [r["status"] for r in d["results"]] == ["invalid", "invalid", "resolved"]
    assert all(r["messages"][0]["code"] == "invalid_coordinates" for r in d["results"][:2])


def test_resolve_request_validation(geo):
    assert geo.post("/api/locations/resolve", json={"items": []}).status_code == 422
    assert geo.post("/api/locations/resolve", json={"items": [{"ref": "a"}]}).status_code == 422  # no input
    assert geo.post("/api/locations/resolve", json={"items": [{"ref": "a", "query": "x", "candidate_id": "ne:admin0:FRA"}]}).status_code == 422
    too_many = [{"ref": f"r{i}", "query": f"{i}.5, 10"} for i in range(26)]
    assert geo.post("/api/locations/resolve", json={"items": too_many}).status_code == 422


def test_resolve_uses_the_geocoders_point_for_landmarks(geo, net):
    net.search_results["Eiffel Tower"] = [EIFFEL]
    net.lookup_results["W5013364"] = [EIFFEL]
    d = geo.post("/api/locations/resolve", json={"items": [{"ref": "e", "query": "Eiffel Tower"}]}).json()
    assert d["online_geocoder"] == "used" and d["all_resolved"] is True
    loc = d["results"][0]["resolved"]
    assert loc["id"] == "osm:W5013364" and (loc["point"]["latitude"], loc["point"]["longitude"]) == (48.8582599, 2.2945006)
    assert loc["source"]["attribution"].startswith("©") and "ODbL" in loc["source"]["license"]
    assert loc["geometry"] is None and loc["geometry_info"]["available"] is False


@needs_atlas
def test_a_geocoder_outage_is_an_error_not_a_false_not_found(geo, net):
    net.geocoder_status = 503
    d = geo.post("/api/locations/resolve", json={"items": [{"ref": "x", "query": "Zzyzxqwv Road"}]}).json()
    assert d["online_geocoder"] == "unavailable"
    r = d["results"][0]
    assert r["status"] == "error" and any(m["code"] == "search_incomplete" for m in r["messages"])
    # places that the offline atlas knows still resolve while the geocoder is down
    ok = geo.post("/api/locations/resolve", json={"items": [{"ref": "f", "query": "Mount Everest"}]}).json()["results"][0]
    assert ok["status"] == "resolved" and ok["resolved"]["source"]["provider"] == "natural_earth"


def test_geocoder_can_be_switched_off_for_offline_use(tmp_path, net):
    c = TestClient(create_app(make_settings(tmp_path, geocoder_enabled=False), geo_transport=net.transport()))
    d = c.post("/api/locations/resolve", json={"items": [{"ref": "x", "query": "Zzyzxqwv"}]}).json()
    assert d["online_geocoder"] == "disabled" and net.geocoder_calls() == []


@needs_atlas
def test_get_location_returns_full_details_and_rejects_bad_ids(geo):
    r = geo.get("/api/locations/ne:admin0:FJI")
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "Fiji" and d["geometry"]["type"] == "MultiPolygon" and d["geometry_info"]["vertex_count"] > 10
    assert geo.get("/api/locations/ne:admin0:ZZZ").status_code == 404
    assert geo.get("/api/locations/bad id!").status_code in (400, 404)
    assert geo.get("/api/locations/nonsense:1").json()["error"]["code"] == "invalid_location_id"
    coord = geo.get("/api/locations/coord:10.500000,-20.250000").json()
    assert coord["point"]["latitude"] == 10.5 and coord["point"]["longitude"] == -20.25


# ====================================================================== preview / confirmation gate
@needs_atlas
def test_preview_summarises_everything_the_user_must_confirm(geo):
    ids = ["ne:admin0:FRA", "coord:48.858300,2.294500"]
    d = geo.post("/api/visualization/preview", json=preview_body(ids, format="both", style="atlas", detail="advanced", labels={"coordinates": True})).json()
    assert d["question"] == "Are these locations and visualization settings correct?"
    s = d["summary"]
    assert [loc["index"] for loc in s["locations"]] == [1, 2]
    assert s["locations"][1]["coordinates_text"] == "48.8583°N, 2.2945°E"
    assert (s["format"], s["detail"], s["style"]) == ("both", "advanced", "atlas") and s["labels"]["coordinates"] is True
    assert d["camera"]["mode"] == "auto" and d["camera"]["bbox"] and len(d["confirmation_token"]) == 64
    cats = {q["category"] for q in d["data_quality"]}
    assert {"generalized", "illustrative"} <= cats
    assert any(a["id"] == "natural_earth" for a in d["attributions"])
    assert any(w["code"] == "terrain_limits" for w in d["warnings"])
    assert s["legs"][0]["distance_km"] > 0


@needs_atlas
def test_nothing_is_generated_without_explicit_confirmation(geo):
    ids = ["ne:admin0:FRA", "ne:admin0:DEU"]
    p = geo.post("/api/visualization/preview", json=preview_body(ids)).json()
    not_yet = geo.post("/api/visualization/confirm", json=confirm_body(p, ids, confirmed=False))
    assert not_yet.status_code == 400 and not_yet.json()["error"]["code"] == "not_confirmed"
    ok = geo.post("/api/visualization/confirm", json=confirm_body(p, ids))
    assert ok.status_code == 200
    g = ok.json()
    assert g["confirmed_token"] == p["confirmation_token"] and [x["id"] for x in g["locations"]] == ids
    assert g["locations"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")  # real outlines, not placeholders


@needs_atlas
def test_changing_anything_after_the_preview_invalidates_the_confirmation(geo):
    ids = ["ne:admin0:FRA", "ne:admin0:DEU"]
    p = geo.post("/api/visualization/preview", json=preview_body(ids, style="light")).json()
    for other_ids, prefs in ((ids, {"style": "dark"}), (list(reversed(ids)), {"style": "light"}), (ids[:1], {"style": "light"}), (ids, {"style": "light", "effects": {"day_night": True}})):
        r = geo.post("/api/visualization/confirm", json=confirm_body(p, other_ids, **prefs))
        assert r.status_code == 409 and r.json()["error"]["code"] == "stale_confirmation"
    forged = confirm_body(p, ids, style="light")
    forged["confirmation_token"] = "0" * 64
    assert geo.post("/api/visualization/confirm", json=forged).status_code == 409


@needs_atlas
def test_the_server_resolves_ids_itself_and_never_trusts_client_coordinates(geo):
    ids = ["ne:admin0:FRA"]
    body = preview_body(ids)
    body["locations"][0]["latitude"] = 0.0  # extra fields are refused rather than silently used
    r = geo.post("/api/visualization/preview", json=body)
    assert r.status_code == 422


@needs_atlas
def test_duplicate_and_unknown_locations_are_rejected(geo):
    dup = geo.post("/api/visualization/preview", json=preview_body(["ne:admin0:FRA", "ne:admin0:FRA"]))
    assert dup.status_code == 422 and dup.json()["error"]["code"] == "duplicate_locations"
    assert geo.post("/api/visualization/preview", json=preview_body(["ne:admin0:ZZZ"])).status_code == 404
    assert geo.post("/api/visualization/preview", json=preview_body(["bad id!"])).status_code == 400
    assert geo.post("/api/visualization/preview", json={"locations": [], "preferences": {}}).status_code == 422
    assert geo.post("/api/visualization/preview", json=preview_body(["ne:admin0:FRA"], format="4d")).status_code == 422
    assert geo.post("/api/visualization/preview", json=preview_body(["ne:admin0:FRA"], custom_colour="red")).status_code == 422


def test_near_duplicate_and_antipodal_points_get_warnings(geo):
    near = geo.post("/api/visualization/preview", json=preview_body(["coord:10.000000,10.000000", "coord:10.001000,10.001000"])).json()
    assert any(w["code"] == "near_duplicate" for w in near["warnings"])
    far = geo.post("/api/visualization/preview", json=preview_body(["coord:0.000000,0.000000", "coord:0.000000,179.000000"], format="3d")).json()
    assert any(w["code"] == "antipodal_span" for w in far["warnings"])
    flat = geo.post("/api/visualization/preview", json=preview_body(["coord:0.000000,0.000000", "coord:0.000000,179.000000"], format="2d")).json()
    assert not any(w["code"] == "antipodal_span" for w in flat["warnings"])


def test_locations_either_side_of_the_dateline_are_framed_the_short_way(geo):
    p = geo.post("/api/visualization/preview", json=preview_body(["coord:-17.713400,178.065000", "coord:-21.178900,-175.198200"])).json()
    box = p["camera"]["bbox"]
    assert box["crosses_antimeridian"] is True and box["east"] > 180
    assert box["east"] - box["west"] < 10
    assert any(w["code"] == "antimeridian" for w in p["warnings"])
    assert p["camera"]["center"]["lon"] == pytest.approx(-178.56, abs=0.2) or abs(p["camera"]["center"]["lon"]) > 175


def test_connection_lines_follow_geodesics_across_the_dateline(geo):
    ids = ["coord:-17.713400,178.065000", "coord:-21.178900,-175.198200"]
    p = geo.post("/api/visualization/preview", json=preview_body(ids, effects={"connect_lines": True})).json()
    leg = p["summary"]["legs"][0]
    assert leg["crosses_antimeridian"] is True and 700 < leg["distance_km"] < 900
    g = geo.post("/api/visualization/confirm", json=confirm_body(p, ids, effects={"connect_lines": True})).json()
    (line,) = g["connections"]["features"]
    lons = [c[0] for c in line["geometry"]["coordinates"]]
    assert max(b - a for a, b in zip(lons, lons[1:])) < 5 and max(lons) > 180  # continuous, unwrapped


def test_connections_are_always_returned_so_the_viewer_can_toggle_them(geo):
    ids = ["coord:0.000000,0.000000", "coord:10.000000,10.000000"]
    p = geo.post("/api/visualization/preview", json=preview_body(ids)).json()
    g = geo.post("/api/visualization/confirm", json=confirm_body(p, ids)).json()
    assert len(g["connections"]["features"]) == 1
    assert g["preferences"]["effects"]["connect_lines"] is False  # drawing is a display choice


@needs_atlas
def test_polar_locations_switch_the_2d_map_to_a_polar_projection(geo):
    south = geo.post("/api/visualization/preview", json=preview_body(["builtin:geographic-south-pole", "ne:continent:antarctica"], format="2d")).json()
    assert south["summary"]["projection_2d"] == "polar_south"
    assert any(w["code"] == "polar_projection" for w in south["warnings"])
    north = geo.post("/api/visualization/preview", json=preview_body(["coord:89.000000,10.000000"], format="2d")).json()
    assert north["summary"]["projection_2d"] == "polar_north"
    anta = geo.post("/api/visualization/preview", json=preview_body(["coord:10.000000,10.000000"], viewpoint={"mode": "preset", "preset": "antarctica"})).json()
    assert anta["summary"]["projection_2d"] == "polar_south"


def test_wide_views_default_to_an_equal_area_projection_and_mercator_stays_available(geo):
    ids = ["coord:51.500000,-0.120000", "coord:-33.870000,151.210000"]
    auto = geo.post("/api/visualization/preview", json=preview_body(ids)).json()
    assert auto["summary"]["projection_2d"] == "equal_earth" and any(w["code"] == "projection_equal_earth" for w in auto["warnings"])
    forced = geo.post("/api/visualization/preview", json=preview_body(ids, projection_2d="mercator")).json()
    assert forced["summary"]["projection_2d"] == "mercator"
    city = geo.post("/api/visualization/preview", json=preview_body(["coord:48.858300,2.294500", "coord:51.500000,-0.120000"])).json()
    assert city["summary"]["projection_2d"] == "mercator"


def test_viewpoint_presets_and_regions(geo):
    ids = ["coord:48.858300,2.294500"]
    asia = geo.post("/api/visualization/preview", json=preview_body(ids, viewpoint={"mode": "preset", "preset": "asia"})).json()
    assert asia["camera"]["mode"] == "preset" and "not geographic boundaries" in asia["camera"]["framing_note"]
    assert geo.post("/api/visualization/preview", json=preview_body(ids, viewpoint={"mode": "preset"})).status_code == 422
    pointy = geo.post("/api/visualization/preview", json=preview_body(ids, viewpoint={"mode": "region", "region_location_id": "coord:10.000000,10.000000"}))
    assert pointy.status_code == 422 and pointy.json()["error"]["code"] == "viewpoint_needs_area"


@needs_atlas
def test_region_viewpoint_frames_the_chosen_area(geo):
    p = geo.post("/api/visualization/preview", json=preview_body(["coord:48.858300,2.294500"], viewpoint={"mode": "region", "region_location_id": "ne:admin0:FRA"})).json()
    assert p["camera"]["mode"] == "region" and "France" in p["camera"]["description"]
    assert p["camera"]["bbox"]["west"] < -4 and p["camera"]["bbox"]["east"] > 8


def test_single_location_uses_a_close_zoom_and_marks_unverified_coordinates(geo):
    p = geo.post("/api/visualization/preview", json=preview_body(["coord:48.858300,2.294500"])).json()
    assert p["camera"]["zoom_hint"] and p["camera"]["zoom_hint"] >= 6
    assert any(w["code"] == "user_coordinates" for w in p["warnings"])
    assert any(q["category"] == "source_data" and "exactly as you entered" in q["text"] for q in p["data_quality"])


def test_imagery_and_day_night_are_labelled_as_static_or_computed(geo):
    p = geo.post("/api/visualization/preview", json=preview_body(["coord:0.000000,0.000000"], style="satellite", effects={"day_night": True})).json()
    codes = {w["code"] for w in p["warnings"]}
    assert {"imagery_static", "day_night_computed"} <= codes
    kinds = {a["id"]: a["kind"] for a in p["attributions"]}
    assert kinds["gibs"] == "imagery" and kinds["computed"] == "computed"
    assert any(q["category"] == "illustrative" and "day/night" in q["text"] for q in p["data_quality"])


def test_custom_labels_are_used_in_the_summary(geo):
    cid = "coord:48.858300,2.294500"
    p = geo.post("/api/visualization/preview", json=preview_body([cid], labels={"custom": {cid: "  Our hotel  "}})).json()
    assert p["summary"]["locations"][0]["name"] == "Our hotel"


# =============================================================================== reference geography
@needs_atlas
def test_boundaries_return_geojson_with_provenance(geo):
    r = geo.get("/api/geography/boundaries", params={"simplify": 0.5})
    assert r.status_code == 200 and r.headers["cache-control"].startswith("public")
    d = r.json()
    assert d["type"] == "FeatureCollection" and len(d["features"]) > 150
    assert d["source"]["provider"] == "Natural Earth" and "legal borders" in d["source"]["note"]
    france = next(f for f in d["features"] if f["id"] == "ne:admin0:FRA")
    assert france["geometry"]["type"] in ("Polygon", "MultiPolygon")


@needs_atlas
def test_boundaries_by_id_and_guardrails(geo):
    d = geo.get("/api/geography/boundaries", params={"layer": "admin1", "ids": "ne:admin0:FJI"}).json()
    assert [f["id"] for f in d["features"]] == ["ne:admin0:FJI"]
    assert geo.get("/api/geography/boundaries", params={"layer": "admin1"}).json()["error"]["code"] == "ids_required"
    assert geo.get("/api/geography/boundaries", params={"layer": "bogus"}).status_code == 422
    assert geo.get("/api/geography/boundaries", params={"simplify": 99}).status_code == 422
    many = ",".join(f"ne:admin0:A{i:02d}" for i in range(51))
    assert geo.get("/api/geography/boundaries", params={"ids": many}).json()["error"]["code"] == "too_many_ids"


def test_terrain_descriptor_names_its_sources(geo):
    d = geo.get("/api/geography/terrain").json()
    assert d["type"] == "raster-dem" and d["encoding"] == "terrarium" and "{z}/{x}/{y}" in d["tiles"][0]
    assert "SRTM" in d["attribution"] and d["notes"]


def test_elevation_endpoint_reports_values_and_gaps_honestly(geo, net):
    net.tile_png = terrarium_png(lambda x, y: 2000.0 + 0 * x)
    ok = geo.get("/api/geography/elevation", params={"lat": 27.9881, "lon": 86.925}).json()
    assert ok["available"] is True and ok["elevation_m"] == pytest.approx(2000.0, abs=0.1) and "tile" in ok
    assert "not a surveyed height" in " ".join(ok["notes"])
    polar = geo.get("/api/geography/elevation", params={"lat": 89.5, "lon": 0}).json()
    assert polar["available"] is False and polar["elevation_m"] is None
    net.tile_png = None
    gone = geo.get("/api/geography/elevation", params={"lat": 10, "lon": 10}).json()
    assert gone["available"] is False and gone["elevation_m"] is None
    bad = geo.get("/api/geography/elevation", params={"lat": 95, "lon": 0})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_coordinates"
    assert geo.get("/api/geography/elevation", params={"lat": 1, "lon": 1, "zoom": 30}).status_code == 422
