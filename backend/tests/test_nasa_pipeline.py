"""Tests for the NASA pipeline building blocks.

The small HDF5 files built here are *structural test fixtures* for the code paths (dimension order, fill values,
attributes). Their numbers are arbitrary and are never presented as NASA observations. The integration test against a
real granule runs only when ``EARTHTREND_NASA_SAMPLE`` points to one.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import httpx
import numpy as np
import pytest
import xarray as xr

from app.errors import AppError
from app.nasa import areaweight as aw
from app.nasa import auth
from app.nasa.cmr import CmrClient, GranuleRecord, monthly_completeness, parse_granule
from app.nasa.config import DataLayout, resolve_data_dir
from app.nasa.download import Downloader, sha256_file
from app.nasa.inspect_hdf5 import inspect_granule, load_field, quality_report

# ----------------------------------------------------------------------------- CMR


def umm(month: str, last_day: int | None = None, size: float = 17.0) -> dict:
    y, m = month.split("-")
    import calendar

    last = last_day or calendar.monthrange(int(y), int(m))[1]
    name = f"3B-MO.MS.MRG.3IMERG.{y}{m}01-S000000-E235959.{m}.V07B.HDF5"
    return {
        "GranuleUR": f"GPM_3IMERGM.07:{name}",
        "TemporalExtent": {"RangeDateTime": {"BeginningDateTime": f"{month}-01T00:00:00.000Z", "EndingDateTime": f"{month}-{last:02d}T23:59:59.999Z"}},
        "DataGranule": {"Identifiers": [{"Identifier": name, "IdentifierType": "ProducerGranuleId"}], "ProductionDateTime": "2024-10-28T20:01:26.000Z", "ArchiveAndDistributionInformation": [{"Size": size, "SizeUnit": "MB"}]},
        "RelatedUrls": [
            {"Type": "GET DATA", "URL": f"https://data.example.test/{y}/{name}"},
            {"Type": "GET DATA VIA DIRECT ACCESS", "URL": f"s3://bucket/{name}"},
            {"Type": "USE SERVICE API", "URL": f"https://opendap.example.test/{name}"},
        ],
    }


MONTHS = ["1998-01", "1998-02", "1998-03", "1998-04", "1998-05"]


def cmr_transport(months: list[str], page_log: list[int] | None = None, fail_first: int = 0, status: int = 200):
    state = {"fails": fail_first}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fails"] > 0:
            state["fails"] -= 1
            return httpx.Response(503)
        if status != 200:
            return httpx.Response(status, text="bad")
        q = dict(request.url.params)
        page, size = int(q.get("page_num", 1)), int(q.get("page_size", 10))
        if page_log is not None:
            page_log.append(page)
        chunk = months[(page - 1) * size : page * size]
        return httpx.Response(200, json={"hits": len(months), "items": [{"umm": umm(m)} for m in chunk]})

    return httpx.MockTransport(handler)


def client(transport) -> CmrClient:
    return CmrClient(client=httpx.Client(transport=transport), backoff_s=0)


def test_cmr_paginates_until_all_granules_are_read():
    pages: list[int] = []
    recs, hits = client(cmr_transport(MONTHS, pages)).granules("C1", page_size=2)
    assert hits == 5 and len(recs) == 5
    assert pages == [1, 2, 3]
    assert recs[0].file_name.startswith("3B-MO.MS.MRG.3IMERG.19980101")
    assert recs[0].https_url.startswith("https://data.example.test/1998/")
    assert recs[0].s3_url.startswith("s3://") and recs[0].opendap_url


def test_cmr_retries_transient_errors_then_succeeds():
    recs, _ = client(cmr_transport(MONTHS, fail_first=2)).granules("C1")
    assert len(recs) == 5


def test_cmr_gives_up_with_a_clear_error():
    c = CmrClient(client=httpx.Client(transport=cmr_transport(MONTHS, fail_first=99)), retries=2, backoff_s=0)
    with pytest.raises(AppError) as e:
        c.granules("C1")
    assert e.value.code == "cmr_unavailable"


def test_cmr_rejection_is_not_retried_and_is_reported():
    with pytest.raises(AppError) as e:
        client(cmr_transport(MONTHS, status=400)).granules("C1")
    assert e.value.code == "cmr_rejected_request"


def test_cmr_pagination_mismatch_is_detected():
    def handler(request):
        return httpx.Response(200, json={"hits": 9, "items": [{"umm": umm("1998-01")}]} if request.url.params["page_num"] == "1" else {"hits": 9, "items": []})

    with pytest.raises(AppError) as e:
        client(httpx.MockTransport(handler)).granules("C1")
    assert e.value.code == "cmr_pagination_mismatch"


def test_collection_lookup_requires_exactly_one_match():
    def handler(request):
        return httpx.Response(200, json={"hits": 0, "items": []})

    with pytest.raises(AppError) as e:
        client(httpx.MockTransport(handler)).find_collection("NOPE", "01")
    assert e.value.code == "collection_not_found"


def test_completeness_detects_gaps_duplicates_and_partial_months():
    g = [parse_granule(umm(m)) for m in ["1998-01", "1998-02", "1998-04", "1998-04"]]
    c = monthly_completeness(g)
    assert c.missing_months == ["1998-03"]
    assert c.duplicate_months == ["1998-04"]
    assert c.expected_months == 4 and c.present_months == 3 and not c.complete
    partial = monthly_completeness([parse_granule(umm("2000-02", last_day=28))])  # 2000 is a leap year: 29 days
    assert partial.non_calendar_months == ["2000-02"]
    full = monthly_completeness([parse_granule(umm(m)) for m in MONTHS])
    assert full.complete and (full.first, full.last) == ("1998-01", "1998-05")


# ----------------------------------------------------------------------------- configuration


def test_data_dir_must_be_set(monkeypatch):
    monkeypatch.delenv("EARTHTREND_NASA_DATA_DIR", raising=False)
    with pytest.raises(AppError) as e:
        resolve_data_dir()
    assert e.value.code == "nasa_data_dir_unset"


@pytest.mark.skipif(os.name != "nt", reason="drive letters")
def test_system_drive_is_refused_unless_explicitly_allowed(monkeypatch):
    monkeypatch.setenv("SystemDrive", "C:")
    with pytest.raises(AppError) as e:
        resolve_data_dir("C:\\nasa_data")
    assert e.value.code == "nasa_data_dir_on_system_drive"
    assert resolve_data_dir("D:\\nasa_data") == Path("D:\\nasa_data")
    monkeypatch.setenv("EARTHTREND_NASA_ALLOW_SYSTEM_DRIVE", "1")
    assert resolve_data_dir("C:\\nasa_data") == Path("C:\\nasa_data")


def test_environment_variable_sets_the_root(monkeypatch, tmp_path):
    monkeypatch.setenv("EARTHTREND_NASA_ALLOW_SYSTEM_DRIVE", "1")
    monkeypatch.setenv("EARTHTREND_NASA_DATA_DIR", str(tmp_path))
    assert resolve_data_dir() == tmp_path


# ----------------------------------------------------------------------------- authentication


def test_missing_credentials_are_reported_without_any_network_call(monkeypatch, tmp_path):
    for k in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD", "EARTHDATA_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
    assert auth.credentials_configured() is False
    with pytest.raises(AppError) as e:
        auth.earthdata_session()
    assert e.value.code == "earthdata_credentials_missing"
    assert "EARTHDATA_USERNAME" in e.value.message


def test_credentials_present_is_detected_but_never_echoed(monkeypatch):
    monkeypatch.setenv("EARTHDATA_USERNAME", "someone")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "very-secret-value")
    assert auth.credentials_configured() is True


# ----------------------------------------------------------------------------- download


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), 7):
            yield self._body[i : i + 7]

    def close(self):
        pass


class FakeSession:
    """Serves one payload, honours Range, and can fail a number of times first."""

    def __init__(self, payload=b"x" * 100, fail=0, status=200, ctype="application/x-hdf5", honour_range=True, lie_about_length=False):
        self.payload, self.fail, self.status, self.ctype, self.honour_range, self.lie = payload, fail, status, ctype, honour_range, lie_about_length
        self.calls: list[dict] = []

    def get(self, url, **kw):
        self.calls.append({"url": url, **kw})
        if self.fail > 0:
            self.fail -= 1
            raise ConnectionError("boom")
        if self.status != 200:
            return FakeResponse(self.status)
        rng = kw.get("headers", {}).get("Range")
        if rng and self.honour_range:
            start = int(rng.split("=")[1].split("-")[0])
            body = self.payload[start:]
            return FakeResponse(206, body, {"Content-Type": self.ctype, "Content-Length": str(len(body) + (5 if self.lie else 0))})
        return FakeResponse(200, self.payload, {"Content-Type": self.ctype, "Content-Length": str(len(self.payload) + (5 if self.lie else 0))})


COLLECTION = {"concept_id": "C2723754851-GES_DISC", "doi": "10.5067/GPM/IMERG/3B-MONTH/07", "provider": "GES_DISC", "title": "t"}


def make_dl(tmp_path, session, **kw):
    layout = DataLayout(tmp_path).ensure()
    return Downloader(layout, session, sleep=lambda s: None, **kw), layout


def granule() -> GranuleRecord:
    return parse_granule(umm("2019-07", size=0.0001))


def test_download_writes_read_only_original_checksum_and_manifest(tmp_path):
    payload = b"hdf5-bytes" * 20
    dl, layout = make_dl(tmp_path, FakeSession(payload))
    e = dl.download(granule(), "GPM_3IMERGM", "07", COLLECTION)
    dest = tmp_path / e.relative_path
    assert dest.read_bytes() == payload
    assert e.sha256 == hashlib.sha256(payload).hexdigest() == sha256_file(dest)
    assert not os.access(dest, os.W_OK) or not (dest.stat().st_mode & stat.S_IWRITE)
    assert not dest.with_name(dest.name + ".part").exists()
    m = json.loads(layout.manifest_path("GPM_3IMERGM", "07").read_text())
    assert m["doi"] == COLLECTION["doi"] and m["collection_concept_id"] == COLLECTION["concept_id"]
    assert m["entries"][0]["sha256"] == e.sha256 and m["entries"][0]["source_url"].startswith("https://")
    assert "Authorization" not in json.dumps(m) and "password" not in json.dumps(m).lower()


def test_interrupted_download_resumes_with_a_range_request(tmp_path):
    payload = bytes(range(200))
    s = FakeSession(payload)
    dl, layout = make_dl(tmp_path, s)
    g = granule()
    part = layout.raw_path("GPM_3IMERGM", "07", g.year, g.file_name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(payload[:80])
    e = dl.download(g, "GPM_3IMERGM", "07", COLLECTION)
    assert s.calls[0]["headers"]["Range"] == "bytes=80-"
    assert e.resumed_from_bytes == 80
    assert (tmp_path / e.relative_path).read_bytes() == payload


def test_server_that_ignores_range_restarts_cleanly(tmp_path):
    payload = bytes(range(150))
    dl, layout = make_dl(tmp_path, FakeSession(payload, honour_range=False))
    g = granule()
    part = layout.raw_path("GPM_3IMERGM", "07", g.year, g.file_name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"stale-garbage")
    e = dl.download(g, "GPM_3IMERGM", "07", COLLECTION)
    assert (tmp_path / e.relative_path).read_bytes() == payload and e.resumed_from_bytes == 0


def test_transient_failures_are_retried(tmp_path):
    s = FakeSession(b"abc" * 30, fail=2)
    dl, _ = make_dl(tmp_path, s)
    e = dl.download(granule(), "GPM_3IMERGM", "07", COLLECTION)
    assert len(s.calls) == 3 and e.size_bytes == 90


def test_download_fails_clearly_after_all_retries(tmp_path):
    dl, _ = make_dl(tmp_path, FakeSession(fail=99), retries=2)
    with pytest.raises(AppError) as e:
        dl.download(granule(), "GPM_3IMERGM", "07", COLLECTION)
    assert e.value.code == "download_failed"


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failures_are_reported_and_not_retried(tmp_path, status):
    s = FakeSession(status=status)
    dl, _ = make_dl(tmp_path, s)
    with pytest.raises(AppError) as e:
        dl.download(granule(), "GPM_3IMERGM", "07", COLLECTION)
    assert e.value.code == "earthdata_auth_failed" and len(s.calls) == 1


def test_a_login_page_instead_of_data_is_detected(tmp_path):
    dl, _ = make_dl(tmp_path, FakeSession(b"<html>login</html>", ctype="text/html; charset=utf-8"))
    with pytest.raises(AppError) as e:
        dl.download(granule(), "GPM_3IMERGM", "07", COLLECTION)
    assert e.value.code == "earthdata_login_page"


def test_truncated_download_is_rejected(tmp_path):
    dl, _ = make_dl(tmp_path, FakeSession(b"z" * 50, lie_about_length=True))
    with pytest.raises(AppError) as e:
        dl.download(granule(), "GPM_3IMERGM", "07", COLLECTION)
    assert e.value.code == "size_mismatch"


def test_second_download_verifies_instead_of_refetching(tmp_path):
    s = FakeSession(b"q" * 40)
    dl, _ = make_dl(tmp_path, s)
    first = dl.download(granule(), "GPM_3IMERGM", "07", COLLECTION)
    again = dl.download(granule(), "GPM_3IMERGM", "07", COLLECTION)
    assert again.sha256 == first.sha256 and len(s.calls) == 1


def test_originals_are_never_overwritten(tmp_path):
    dl, layout = make_dl(tmp_path, FakeSession(b"new" * 10))
    g = granule()
    dest = layout.raw_path("GPM_3IMERGM", "07", g.year, g.file_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"someone elses file")
    with pytest.raises(AppError) as e:
        dl.download(g, "GPM_3IMERGM", "07", COLLECTION)
    assert e.value.code == "raw_file_unrecorded" and dest.read_bytes() == b"someone elses file"


def test_tampering_with_a_recorded_original_is_detected(tmp_path):
    dl, _ = make_dl(tmp_path, FakeSession(b"k" * 40))
    e = dl.download(granule(), "GPM_3IMERGM", "07", COLLECTION)
    dest = tmp_path / e.relative_path
    dest.chmod(stat.S_IREAD | stat.S_IWRITE)
    dest.write_bytes(b"tampered")
    with pytest.raises(AppError) as err:
        dl.download(granule(), "GPM_3IMERGM", "07", COLLECTION)
    assert err.value.code == "raw_file_modified"


# ----------------------------------------------------------------------------- area weighting


def test_exact_band_weights_cover_the_sphere():
    lat = np.arange(-89.95, 90, 0.1)
    lo, hi = aw.centres_to_bounds(lat)
    w = aw.exact_band_weights(lo, hi)
    assert w.sum() == pytest.approx(2.0, abs=1e-9)  # integral of cos(phi) dphi over the globe
    assert (w * 2 * np.pi * aw.EARTH_RADIUS_KM**2).sum() == pytest.approx(aw.sphere_area_km2(), rel=1e-9)


def test_constant_field_has_that_mean_whatever_the_weights():
    lat = np.arange(-89.95, 90, 0.1)
    f = np.full((lat.size, 6), 3.25)
    for w in (aw.cos_lat_weights(lat), aw.exact_band_weights(*aw.centres_to_bounds(lat))):
        assert aw.weighted_mean(f, w, "t").mean == pytest.approx(3.25)


def test_matches_an_analytic_area_mean():
    # The global area mean of sin^2(latitude) is exactly 1/3. A plain average over rows would give about 0.5.
    lat = np.arange(-89.95, 90, 0.1)
    f = np.repeat((np.sin(np.deg2rad(lat)) ** 2)[:, None], 4, axis=1)
    exact = aw.weighted_mean(f, aw.exact_band_weights(*aw.centres_to_bounds(lat)), "exact").mean
    cos = aw.weighted_mean(f, aw.cos_lat_weights(lat), "cos").mean
    assert exact == pytest.approx(1 / 3, abs=1e-6)
    assert cos == pytest.approx(1 / 3, abs=1e-5)
    assert abs(exact - cos) / exact < 1e-4  # cos(lat) is a fine approximation on a 0.1 degree grid
    assert f.mean() == pytest.approx(0.5, abs=0.01)


def test_missing_cells_are_excluded_with_weights_renormalised_and_reported():
    lat = np.array([-45.0, 45.0])
    f = np.array([[1.0, np.nan], [3.0, 3.0]])
    r = aw.weighted_mean(f, np.array([1.0, 1.0]), "t")
    assert r.mean == pytest.approx((1 + 3 + 3) / 3) and r.n_valid == 3 and r.valid_area_fraction == pytest.approx(0.75)
    assert aw.weighted_mean(np.full((2, 2), np.nan), np.ones(2), "t").mean is None


def test_latitude_mask_limits_the_average_and_the_coverage_base():
    lat = np.array([-80.0, 0.0, 80.0])
    f = np.array([[np.nan], [2.0], [100.0]])
    r = aw.weighted_mean(f, np.ones(3), "t", lat_mask=np.abs(lat) < 60)
    assert r.mean == 2.0 and r.valid_area_fraction == 1.0


def test_bad_inputs_are_rejected():
    with pytest.raises(ValueError):
        aw.cos_lat_weights(np.array([91.0]))
    with pytest.raises(ValueError):
        aw.centres_to_bounds(np.array([0.0, 1.0, 3.0]))
    with pytest.raises(ValueError):
        aw.weighted_mean(np.zeros((3, 3)), np.ones(2), "t")


def test_hours_in_month_uses_the_calendar():
    assert aw.hours_in_month(2020, 2) == 29 * 24
    assert aw.hours_in_month(2019, 2) == 28 * 24
    assert aw.hours_in_month(2019, 7) == 31 * 24


# ----------------------------------------------------------------------------- HDF5 inspection (structural fixtures)

FILL = np.float32(-9999.9)


def make_granule(path: Path, *, units: str = "mm/hr", lat_n: int = 18, lon_n: int = 36, time_s: int = 1_246_000_000, fill_polar=True) -> Path:
    """A tiny file with the same group, variable names and (time, lon, lat) layout. Values are arbitrary test numbers."""
    lat = (np.arange(lat_n) * (180 / lat_n) - 90 + 90 / lat_n).astype("float32")
    lon = (np.arange(lon_n) * (360 / lon_n) - 180 + 180 / lon_n).astype("float32")
    rng = np.random.default_rng(0)
    precip = rng.gamma(2.0, 0.1, size=(1, lon_n, lat_n)).astype("float32")
    err = (precip * 0.3).astype("float32")
    qi = rng.uniform(0, 1, size=(1, lon_n, lat_n)).astype("float32")
    if fill_polar:
        for a in (precip, err, qi):
            a[:, :, :2] = FILL
        qi[:, 0, 5] = FILL  # one cell where only the quality index is missing
    dims = ("time", "lon", "lat")

    def var(a, u):
        return xr.Variable(dims, a, {"units": u})

    half = 90 / lat_n
    ds = xr.Dataset(
        {
            "precipitation": var(precip, units),
            "randomError": var(err, "mm/hr"),
            "precipitationQualityIndex": var(qi, "Equivalent gauges per 2.5 deg box"),
            "lat_bnds": (("lat", "latv"), np.stack([lat - half, lat + half], axis=1)),
            "time_bnds": (("time", "nv"), np.array([[time_s - 100, time_s + 100]], dtype="int32")),
        },
        coords={
            "lat": ("lat", lat, {"units": "degrees_north"}),
            "lon": ("lon", lon, {"units": "degrees_east"}),
            "time": ("time", np.array([time_s], dtype="int32"), {"units": "seconds since 1980-01-06 00:00:00 UTC"}),
        },
    )
    enc = {n: {"_FillValue": FILL} for n in ("precipitation", "randomError", "precipitationQualityIndex")}
    ds.to_netcdf(path, group="Grid", engine="h5netcdf", encoding=enc)
    return path


def test_inspection_reads_dimension_order_units_fill_and_time(tmp_path):
    p = make_granule(tmp_path / "g.HDF5")
    r = inspect_granule(p, cmr_size_mb=1.0, granule_begin="2019-07-01T00:00:00.000Z", granule_end="2019-07-31T23:59:59.999Z")
    assert r["dimension_order"] == [["time", "lon", "lat"]]
    assert r["variables"]["precipitation"]["attrs"]["units"] == "mm/hr"
    assert float(r["variables"]["precipitation"]["attrs"]["_FillValue"]) == pytest.approx(-9999.9, abs=0.01)
    assert not r["variables"]["precipitation"]["has_scale_factor"]
    assert r["time"]["decoded_utc"].startswith("2019-07")
    assert r["time"]["matches_cmr_month"] is True
    # the fixture is 18x36, not the 1800x3600 the real product has, and the inspector must say so
    assert any("not the 1800 x 3600" in f["text"] for f in r["findings"])
    assert r["lat_axis_ascending"] is True


def test_inspection_flags_unit_and_month_disagreements(tmp_path):
    p = make_granule(tmp_path / "g.HDF5", units="mm/day")
    r = inspect_granule(p, granule_begin="2020-01-01T00:00:00.000Z")
    texts = " ".join(f["text"] for f in r["findings"])
    assert "mm/day" in texts and "not in the CMR month" in texts
    assert r["ok"] is False


def test_non_hdf5_file_is_rejected(tmp_path):
    bad = tmp_path / "x.HDF5"
    bad.write_bytes(b"not hdf5")
    with pytest.raises(ValueError):
        inspect_granule(bad)


def test_fill_values_become_nan_and_other_values_are_untouched(tmp_path):
    p = make_granule(tmp_path / "g.HDF5")
    arr, lat, lon, attrs = load_field(p, "precipitation")
    assert arr.shape == (18, 36) and lat[0] < lat[-1]  # reordered to (lat, lon) by dimension name
    assert np.isnan(arr[:2]).all() and np.isfinite(arr[2:]).all()
    assert (arr[np.isfinite(arr)] >= 0).all()
    assert attrs["units"] == "mm/hr"  # original unit preserved, no conversion


def test_quality_report_counts_missing_values_and_mask_disagreement(tmp_path):
    p = make_granule(tmp_path / "g.HDF5")
    q = quality_report(p, granule_begin="2019-07-01T00:00:00.000Z")
    pv = q["variables"]["precipitation"]
    assert pv["missing_fill"] == 2 * 36 and pv["valid"] == 16 * 36
    assert q["mask_agreement"]["precip_valid_and_quality_missing"] == 1
    assert q["mask_agreement"]["precip_missing_and_randomError_valid"] == 0
    w = q["weighting"]
    assert w["exact_band_weights_sum_check"] == pytest.approx(1.0, abs=1e-9)
    assert w["global_mean_precipitation_valid_cells_only"]["units"] == "mm/hr"
    assert 0 < w["global_mean_precipitation_valid_cells_only"]["valid_area_fraction_exact"] < 1
    assert q["derived_example_not_stored"]["hours_in_month"] == 31 * 24
    json.dumps(q)  # the report must be serialisable


# ----------------------------------------------------------------------------- real granule (optional)


@pytest.mark.skipif(not os.environ.get("EARTHTREND_NASA_SAMPLE"), reason="set EARTHTREND_NASA_SAMPLE to a downloaded real granule")
def test_real_granule_passes_inspection():
    p = Path(os.environ["EARTHTREND_NASA_SAMPLE"])
    r = inspect_granule(p)
    assert r["ok"], r["findings"]
    assert r["coordinates"]["n_lat"] == 1800 and r["coordinates"]["n_lon"] == 3600
