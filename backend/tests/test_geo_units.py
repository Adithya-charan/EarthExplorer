"""Unit tests for coordinates, geometry, the Nominatim client, terrain sampling and the request schemas."""

from __future__ import annotations

import math

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.errors import AppError
from app.geo import geometry as G
from app.geo.coords import coordinate_id, format_coordinates, parse_coordinate_id, parse_coordinates
from app.geo.nominatim import GeocoderUnavailable, NominatimClient, classify_osm
from app.geo.schemas import BBox, CustomStyle, ResolveItem, Viewpoint, VisualizationPreferences
from app.geo.terrain import TerrainService
from tests.geo_helpers import EIFFEL, NOMINATIM_HOST, TILE_HOST, FakeNet, terrarium_png


def settings(**kw) -> Settings:
    base = dict(
        nominatim_url=f"https://{NOMINATIM_HOST}",
        terrain_tile_url=f"https://{TILE_HOST}/{{z}}/{{x}}/{{y}}.png",
        geocoder_min_interval_s=0.0,
        geo_warm_on_start=False,
    )
    base.update(kw)
    return Settings(**base)


# ------------------------------------------------------------------------------------ coordinates
def test_parse_decimal_dms_and_hemisphere_letters():
    assert parse_coordinates("48.8584, 2.2945") == (48.8584, 2.2945)
    assert parse_coordinates("34.05 S, 118.25 W") == (-34.05, -118.25)
    assert parse_coordinates("N 40.7128 W 74.0060") == (40.7128, -74.006)
    lat, lon = parse_coordinates("40°26'46\"N 79°58'56\"W")
    assert lat == pytest.approx(40.446111, abs=1e-5) and lon == pytest.approx(-79.982222, abs=1e-5)
    assert parse_coordinates("geo:27.9881,86.925;u=35") == (27.9881, 86.925)


def test_place_names_are_not_mistaken_for_coordinates():
    for text in ("Paris", "Mount Everest", "Springfield, Illinois", "K2", "Route 66"):
        assert parse_coordinates(text) is None


@pytest.mark.parametrize("text", ["95, 10", "-91, 0", "10, 181", "10, -200", "40°70'00\"N 10°0'0\"E"])
def test_invalid_coordinates_raise_a_clear_error(text):
    with pytest.raises(AppError) as exc:
        parse_coordinates(text)
    assert exc.value.status_code == 422 and exc.value.code == "invalid_coordinates"


def test_format_and_coordinate_ids_round_trip():
    assert format_coordinates(48.8583, 2.2945) == "48.8583°N, 2.2945°E"
    assert format_coordinates(-17.8, -170.2) == "17.8000°S, 170.2000°W"
    cid = coordinate_id(-33.8688, 151.2093)
    assert cid == "coord:-33.868800,151.209300"
    assert parse_coordinate_id(cid) == (-33.8688, 151.2093)
    assert parse_coordinate_id("coord:abc") is None


# --------------------------------------------------------------------------------------- geometry
def test_circular_extent_chooses_the_short_way_round_the_antimeridian():
    west, east, crosses = G.circular_extent([(176.8, 180.0), (-180.0, -178.3)])
    assert crosses and west == pytest.approx(176.8) and east == pytest.approx(181.7)
    assert G.circular_extent([(10, 20), (30, 40)]) == (10, 40, False)


def test_union_bbox_of_tonga_and_fiji_is_narrow():
    fiji = BBox(west=176.8, south=-20.7, east=181.7, north=-12.5, crosses_antimeridian=True)
    tonga = BBox(west=-175.4, south=-22.4, east=-173.7, north=-15.5)
    box = G.union_bbox([fiji, tonga])
    assert box.crosses_antimeridian
    assert box.east - box.west < 12  # not ~350° as a naive min/max would give
    assert box.west == pytest.approx(176.8) and box.east == pytest.approx(186.3)


def test_geodesic_path_is_continuous_across_the_dateline():
    path = G.geodesic_path(0.0, 170.0, 0.0, -170.0)
    lons = [p[0] for p in path]
    assert all(b >= a for a, b in zip(lons, lons[1:]))  # monotonic: no jump from +180 to -180
    assert lons[0] == pytest.approx(170.0) and lons[-1] == pytest.approx(190.0)
    dist, bearing = G.geodesic_leg(0.0, 170.0, 0.0, -170.0)
    assert dist == pytest.approx(2226.4, abs=2.0) and bearing == pytest.approx(90.0, abs=0.5)


def test_angular_distance_and_tile_maths():
    assert G.angular_distance_deg(0, 0, 0, 180) == pytest.approx(180.0)
    assert G.angular_distance_deg(10, 20, 10, 20) == pytest.approx(0.0, abs=1e-6)
    assert G.tile_xy(0.0, 0.0, 1) == (1, 1, 0.0, 0.0)
    x, y, fx, fy = G.tile_xy(27.9881, 86.925, 10)
    # x = floor((86.925 + 180) / 360 * 2^10) = 759; y from the Web Mercator formula = 429
    assert (x, y) == (759, 429) and 0 <= fx < 1 and 0 <= fy < 1


# ------------------------------------------------------------------------------ OSM classification
@pytest.mark.parametrize(
    "item,expected",
    [
        ({"category": "place", "type": "city", "place_rank": 16}, "city"),
        ({"category": "boundary", "type": "administrative", "addresstype": "country", "place_rank": 4}, "country"),
        ({"category": "boundary", "type": "administrative", "addresstype": "state", "place_rank": 8}, "state_province"),
        ({"category": "natural", "type": "peak"}, "mountain_peak"),
        ({"category": "natural", "type": "water"}, "lake"),
        ({"category": "waterway", "type": "river"}, "river"),
        ({"category": "tourism", "type": "attraction"}, "landmark"),
        ({"category": "man_made", "type": "tower"}, "landmark"),
        ({"category": "place", "type": "ocean"}, "ocean_sea"),
    ],
)
def test_classify_osm(item, expected):
    assert classify_osm(item)[0] == expected


# -------------------------------------------------------------------------------- Nominatim client
def test_nominatim_search_uses_the_providers_coordinates_unchanged():
    net = FakeNet()
    net.search_results["Eiffel Tower"] = [EIFFEL]
    client = NominatimClient(settings(), transport=net.transport())
    (cand,) = client.search("Eiffel Tower")
    assert cand.id == "osm:W5013364"
    assert (cand.latitude, cand.longitude) == (48.8582599, 2.2945006)
    assert cand.position_kind == "provider_point" and cand.feature_class == "landmark"
    assert cand.context.country == "France" and cand.context.country_code == "FR"
    assert "Paris" in (cand.context.label or "")


def test_nominatim_sends_an_identifying_generic_user_agent():
    net = FakeNet()
    net.search_results["x y"] = []
    NominatimClient(settings(), transport=net.transport()).search("x y")
    ua = net.geocoder_calls()[0].headers["user-agent"]
    assert ua == "geo-explorer-dev/0.1 (local development)"
    assert "@" not in ua


def test_nominatim_results_are_cached():
    net = FakeNet()
    net.search_results["Eiffel Tower"] = [EIFFEL]
    client = NominatimClient(settings(), transport=net.transport())
    client.search("Eiffel Tower")
    client.search("Eiffel Tower")
    assert len(net.geocoder_calls()) == 1


def test_nominatim_requests_are_spaced_by_the_policy_interval():
    net = FakeNet()
    now = [100.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    client = NominatimClient(settings(geocoder_min_interval_s=1.1), transport=net.transport(), clock=lambda: now[0], sleep=sleep)
    client.search("first")
    now[0] += 0.3  # only 0.3 s later
    client.search("second")
    assert len(slept) == 1 and slept[0] == pytest.approx(0.8, abs=1e-6)


@pytest.mark.parametrize("status,code", [(429, "geocoder_rate_limited"), (403, "geocoder_blocked"), (503, "geocoder_unavailable")])
def test_nominatim_failures_are_reported_not_hidden(status, code):
    net = FakeNet()
    net.geocoder_status = status
    with pytest.raises(GeocoderUnavailable) as exc:
        NominatimClient(settings(), transport=net.transport()).search("anything")
    assert exc.value.code == code


def test_nominatim_timeout_and_disabled():
    net = FakeNet()
    net.geocoder_timeout = True
    with pytest.raises(GeocoderUnavailable) as exc:
        NominatimClient(settings(), transport=net.transport()).search("anything")
    assert exc.value.code == "geocoder_unavailable"
    off = NominatimClient(settings(geocoder_enabled=False), transport=net.transport())
    with pytest.raises(GeocoderUnavailable) as exc2:
        off.search("anything")
    assert exc2.value.code == "geocoder_disabled"


def test_nominatim_lookup_point_has_no_invented_geometry():
    net = FakeNet()
    net.lookup_results["W5013364"] = [EIFFEL]
    loc = NominatimClient(settings(), transport=net.transport()).lookup("W5013364")
    assert loc.geometry is None and loc.geometry_type == "Point"
    assert loc.geometry_info.available is False and loc.geometry_info.quality == "not_applicable"
    assert loc.source.provider == "openstreetmap" and "ODbL" in loc.source.license
    assert loc.validation.status == "validated_with_limits"


def test_nominatim_lookup_area_keeps_the_providers_outline_and_marks_it_generalized():
    lake = {
        "osm_type": "relation",
        "osm_id": 42,
        "lat": "10.0",
        "lon": "20.0",
        "category": "natural",
        "type": "water",
        "name": "Test Lake",
        "importance": 0.3,
        "address": {"country": "Testland", "country_code": "tl"},
        "boundingbox": ["9.5", "10.5", "19.5", "20.5"],
        "geojson": {"type": "Polygon", "coordinates": [[[19.5, 9.5], [20.5, 9.5], [20.5, 10.5], [19.5, 10.5], [19.5, 9.5]]]},
    }
    net = FakeNet()
    net.lookup_results["R42"] = [lake]
    loc = NominatimClient(settings(), transport=net.transport()).lookup("R42")
    assert loc.feature_class == "lake" and loc.geometry_type == "Polygon"
    assert loc.geometry_info.quality == "generalized" and loc.geometry_info.area_km2 and loc.geometry_info.area_km2 > 10_000
    assert loc.bbox and (loc.bbox.west, loc.bbox.east) == (19.5, 20.5)


def test_nominatim_lookup_of_a_missing_object_is_a_404():
    net = FakeNet()
    with pytest.raises(AppError) as exc:
        NominatimClient(settings(), transport=net.transport()).lookup("N999")
    assert exc.value.status_code == 404
    with pytest.raises(AppError) as exc2:
        NominatimClient(settings(), transport=net.transport()).lookup("X1")
    assert exc2.value.code == "invalid_location_id"


# ---------------------------------------------------------------------------------------- terrain
def test_terrain_sampling_decodes_terrarium_and_interpolates():
    net = FakeNet()
    net.tile_png = terrarium_png(lambda x, y: 1000.0 + x)  # elevation rises 1 m per pixel eastwards
    svc = TerrainService(settings(), transport=net.transport())
    lat, lon, z = 27.9881, 86.925, 10
    res = svc.elevation(lat, lon, z)
    _, _, fx, _ = G.tile_xy(lat, lon, z)
    expected = 1000.0 + min(255.0, max(0.0, fx * 256.0 - 0.5))
    assert res.available and res.elevation_m == pytest.approx(expected, abs=0.6)
    assert res.tile == {"z": 10, "x": 759, "y": 429}
    assert any("not a surveyed height" in n for n in res.notes)
    assert res.approx_resolution_m == pytest.approx(156543.03392 * math.cos(math.radians(lat)) / 2**10, abs=0.1)


def test_terrain_negative_depths_are_labelled():
    net = FakeNet()
    net.tile_png = terrarium_png(lambda x, y: -3500.0 + 0 * x)
    res = TerrainService(settings(), transport=net.transport()).elevation(0.0, -30.0, 5)
    assert res.elevation_m == pytest.approx(-3500.0, abs=0.1)
    assert any("depths below sea level" in n for n in res.notes)


def test_terrain_unavailable_cases_say_why():
    net = FakeNet()  # tiles return 404
    svc = TerrainService(settings(), transport=net.transport())
    missing = svc.elevation(10.0, 10.0, 5)
    assert missing.available is False and missing.elevation_m is None and "could not be loaded" in missing.notes[0]
    polar = svc.elevation(89.0, 0.0)
    assert polar.available is False and "85.05" in polar.notes[0]
    with pytest.raises(AppError) as exc:
        svc.elevation(91.0, 0.0)
    assert exc.value.code == "invalid_coordinates"


# ---------------------------------------------------------------------------------------- schemas
def test_resolve_item_requires_exactly_one_input():
    assert ResolveItem(ref="a", query="  Paris  ").query == "Paris"
    for bad in (dict(ref="a"), dict(ref="a", query="x", candidate_id="ne:admin0:FRA"), dict(ref="a", query="   ")):
        with pytest.raises(ValidationError):
            ResolveItem(**bad)


def test_viewpoint_and_style_validation():
    with pytest.raises(ValidationError):
        Viewpoint(mode="preset")
    with pytest.raises(ValidationError):
        Viewpoint(mode="region")
    assert Viewpoint(mode="preset", preset="asia").preset == "asia"
    assert CustomStyle(ocean="#ABCDEF").ocean == "#abcdef"
    with pytest.raises(ValidationError):
        CustomStyle(ocean="blue")
    with pytest.raises(ValidationError):
        VisualizationPreferences(unknown_option=True)


def test_bbox_validation():
    with pytest.raises(ValidationError):
        BBox(west=10, south=5, east=5, north=10)  # east < west
    with pytest.raises(ValidationError):
        BBox(west=0, south=10, east=5, north=5)  # south > north
    assert BBox(west=176.8, south=-20, east=181.7, north=-12, crosses_antimeridian=True).east == 181.7
