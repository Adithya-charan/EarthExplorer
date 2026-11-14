"""Story summary and rule-based chat."""

from __future__ import annotations

G, D, R = "gpm-imerg-global-observed", "gpm-imerg-regional-synthetic-demo", "Global (area-average)"


def story(c, ds, region, start, end, **kw):
    return c.post("/api/story", json={"dataset_id": ds, "region": region, "start": start, "end": end, **kw})


def test_regions_listing_has_geo(package_client):
    r = package_client.get("/api/regions", params={"dataset_id": D}).json()
    names = {x["region"]: x for x in r["regions"]}
    assert {"India", "Amazon", "Central Africa"} <= set(names)
    assert names["India"]["geo"]["kind"] == "approximate_extent"
    assert r["default_variable"] == "precipitation"
    g = package_client.get("/api/regions", params={"dataset_id": G}).json()
    assert g["regions"][0]["geo"]["kind"] == "none"


def test_story_range_observed_global(package_client):
    r = story(package_client, G, R, "2010-01-01", "2015-12-01")
    assert r.status_code == 200
    b = r.json()
    assert b["banner"] is None and b["provenance"]["is_synthetic"] is False
    assert b["provenance"]["dataset_checksum"] and b["provenance"]["generated_at"]
    assert b["period"]["n_months_expected"] == 72 and b["stats"]["mean"] > 0
    kinds = {s["kind"] for s in b["sentences"]}
    assert "observation" in kinds and "limitation" in kinds
    assert all(s["evidence"] for s in b["sentences"])
    assert b["why"]["cause_established"] is False
    assert "cannot explain why" in b["why"]["statement"]
    # random_error is never offered as a driver
    assert b["why"]["co_varying"] == []


def test_story_single_month_and_anomaly(package_client):
    b = story(package_client, G, R, "2012-03-15", "2012-03-20").json()
    assert b["period"]["n_months_expected"] == 1 and b["period"]["label"] == "March 2012"
    m = b["months"][0]
    assert m["climatology"] is not None and m["anomaly"] is not None


def test_story_synthetic_is_labelled_everywhere(package_client):
    b = story(package_client, D, "India", "2005-01-01", "2008-12-01").json()
    assert b["banner"] == "SYNTHETIC DEMO — NOT NASA OBSERVATIONS"
    assert b["provenance"]["is_synthetic"] is True
    assert any("SYNTHETIC DEMO" in c for c in b["caveats"])
    assert any("synthetic demo" in s["text"] for s in b["sentences"] if s["kind"] == "observation")
    assert b["geo"]["bbox"] is not None


def test_story_errors(package_client):
    assert story(package_client, G, "India", "2010-01-01", "2011-01-01").status_code == 404
    assert story(package_client, G, R, "2011-01-01", "2010-01-01").status_code == 422
    assert story(package_client, G, R, "1950-01-01", "1951-01-01").json()["error"]["code"] == "period_outside_data"
    assert story(package_client, "nope", R, "2010-01-01", "2011-01-01").status_code == 404
    assert story(package_client, G, R, "2010-01-01", "2011-01-01", variable="zzz").status_code == 404


def test_story_never_invents_missing_months(package_client):
    b = story(package_client, G, R, "1990-01-01", "2000-12-01").json()
    assert b["period"]["n_valid"] < b["period"]["n_months_expected"]
    assert any("outside the data" in c for c in b["caveats"])


def chat(c, msg, ds=D, **kw):
    return c.post("/api/chat", json={"dataset_id": ds, "message": msg, **kw}).json()


def test_chat_range_for_place(package_client):
    r = chat(package_client, "What happened in India from 2010 to 2015?")
    assert r["action"]["type"] == "show_story" and r["action"]["region"] == "India"
    assert r["action"]["start"] == "2010-01-01" and r["action"]["end"] == "2015-12-01"
    assert r["understood"]["place"] == "India"
    assert r["story"]["banner"]
    assert "3D map" in r["reply"]


def test_chat_month_year_and_reversed_years(package_client):
    r = chat(package_client, "show me Amazon in March 2012")
    assert r["action"]["start"] == r["action"]["end"] == "2012-03-01"
    r = chat(package_client, "amazon between 2015 and 2010")
    assert r["action"]["start"] == "2010-01-01" and r["action"]["end"] == "2015-12-01"


def test_chat_asks_when_place_or_time_missing(package_client):
    r = chat(package_client, "what happened from 2010 to 2012")
    assert r["action"]["type"] == "none" and "Which place" in r["reply"]
    r = chat(package_client, "tell me about India")
    assert r["action"]["type"] == "none" and "not the time" in r["reply"]


def test_chat_uses_selected_region_and_single_region_dataset(package_client):
    r = chat(package_client, "what happened in 2012?", current_region="Amazon")
    assert r["action"]["region"] == "Amazon"
    r = chat(package_client, "what happened from 2010 to 2015", ds=G)
    assert r["action"]["region"] == R and r["story"]["banner"] is None


def test_chat_compare_and_help_and_clipping(package_client):
    r = chat(package_client, "Compare India and Amazon from 2005 to 2010")
    assert r["action"]["type"] == "compare" and r["action"]["regions"] == ["India", "Amazon"]
    assert "illustrative" in r["reply"]
    assert chat(package_client, "help")["action"]["type"] == "none"
    r = chat(package_client, "India from 1900 to 2010")
    assert "clipped" in r["understood"]["period"]
    r = chat(package_client, "India in 1900")
    assert r["action"]["type"] == "none" and "outside the data" in r["reply"]


def test_chat_does_not_claim_causes(package_client):
    r = chat(package_client, "Why did rain change in India from 2010 to 2015?")
    assert r["action"]["type"] == "show_story"
    assert r["story"]["why"]["cause_established"] is False
