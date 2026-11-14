"""OpenStreetMap Nominatim client.

Follows the public instance's usage policy (https://operations.osmfoundation.org/policies/nominatim/):

* at most one request per second (a lock enforces the interval; the interval is configurable),
* an identifying ``User-Agent`` that is configurable and never contains personal details,
* results are cached (24 h by default) and no keystroke-by-keystroke autocomplete is performed,
* attribution (© OpenStreetMap contributors, ODbL) travels with every result.

Only fields the service actually returned are used; nothing is estimated or filled in.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

import httpx
from shapely.geometry import shape

from app.config import Settings
from app.geo import geometry as G
from app.geo.schemas import (
    CLASS_LABELS,
    SHAPE_BY_CLASS,
    BBox,
    Candidate,
    Context,
    Fact,
    GeometryInfo,
    PointInfo,
    ResolvedLocation,
    SourceInfo,
    Validation,
)

log = logging.getLogger("earthtrend.geo")

OSM_COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
ATTRIBUTION = "© OpenStreetMap contributors (ODbL 1.0)"
TYPE_LETTER = {"node": "N", "way": "W", "relation": "R"}
LETTER_TYPE = {v: k for k, v in TYPE_LETTER.items()}

CITY_TYPES = {"city", "town", "village", "hamlet", "municipality", "suburb", "neighbourhood", "quarter", "borough", "city_district", "isolated_dwelling", "locality"}
STATE_TYPES = {"state", "province", "region", "territory", "prefecture", "governorate", "department", "emirate", "canton", "voivodeship", "oblast", "federal_district"}
LANDMARK_CATEGORIES = {"tourism", "historic", "man_made", "amenity", "building", "leisure", "aeroway", "railway", "shop", "office", "military", "craft", "highway"}


class GeocoderUnavailable(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class TTLCache:
    """Small thread-safe cache with a time-to-live and a size bound."""

    def __init__(self, ttl_s: float, maxsize: int = 512, clock: Callable[[], float] = time.monotonic):
        self._ttl, self._max, self._clock = ttl_s, maxsize, clock
        self._data: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            expires, value = hit
            if expires < self._clock():
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            self._data[key] = (self._clock() + self._ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


def classify_osm(item: dict[str, Any]) -> tuple[str, str]:
    """(feature_class, class_label) from the OSM category / type / place rank the geocoder returned."""
    cat = (item.get("category") or item.get("class") or "").lower()
    typ = (item.get("type") or "").lower()
    at = (item.get("addresstype") or "").lower()
    try:
        rank = int(item.get("place_rank") or 0)
    except (TypeError, ValueError):
        rank = 0
    human = typ.replace("_", " ").capitalize() if typ else None

    if cat in ("boundary", "place"):
        t = typ if cat == "place" else (at or typ)
        if t == "country" or (cat == "boundary" and typ == "administrative" and 0 < rank <= 4):
            return "country", CLASS_LABELS["country"]
        if t == "continent":
            return "continent", CLASS_LABELS["continent"]
        if t in ("ocean", "sea"):
            return "ocean_sea", CLASS_LABELS["ocean_sea"]
        if t in ("island", "islet", "archipelago"):
            return "island", CLASS_LABELS["island"]
        if t in STATE_TYPES or (cat == "boundary" and typ == "administrative" and 5 <= rank <= 8):
            return "state_province", CLASS_LABELS["state_province"]
        if t in CITY_TYPES or at in CITY_TYPES:
            return "city", CLASS_LABELS["city"]
        if cat == "boundary" and typ == "administrative" and rank <= 12:
            return "region", (human or "Administrative area").replace("Administrative", "Administrative area")
        if cat == "boundary" and typ == "administrative":
            return "city", CLASS_LABELS["city"]
        if cat == "boundary":
            return "region", human or "Boundary"
        return "region", human or CLASS_LABELS["region"]
    if cat == "natural":
        if typ in ("peak", "volcano", "hill", "mountain", "saddle"):
            return "mountain_peak", CLASS_LABELS["mountain_peak"]
        if typ in ("mountain_range", "ridge"):
            return "mountain_range", CLASS_LABELS["mountain_range"]
        if typ in ("water", "lake", "reservoir"):
            return "lake", CLASS_LABELS["lake"]
        if typ in ("bay", "strait", "sea", "ocean", "coastline"):
            return "ocean_sea", CLASS_LABELS["ocean_sea"]
        if typ in ("desert", "sand"):
            return "desert", CLASS_LABELS["desert"]
        if typ in ("wood", "forest"):
            return "forest", CLASS_LABELS["forest"]
        if typ in ("island", "islet"):
            return "island", CLASS_LABELS["island"]
        return "region", human or CLASS_LABELS["region"]
    if cat == "waterway":
        return "river", (human or CLASS_LABELS["river"]) if typ != "river" else CLASS_LABELS["river"]
    if cat == "landuse" and typ == "forest":
        return "forest", CLASS_LABELS["forest"]
    if cat in ("leisure", "boundary") and typ in ("nature_reserve", "national_park", "protected_area"):
        return "region", human or CLASS_LABELS["region"]
    if cat in LANDMARK_CATEGORIES:
        return "landmark", (human or CLASS_LABELS["landmark"]) if cat not in ("tourism", "historic") else (f"{human} ({cat})" if human else CLASS_LABELS["landmark"])
    return "other", human or CLASS_LABELS["other"]


def _context_from(item: dict[str, Any], name: str) -> Context:
    addr = item.get("address") or {}
    country = addr.get("country")
    code = (addr.get("country_code") or "").upper() or None
    admin1 = addr.get("state") or addr.get("province") or addr.get("region")
    admin2 = addr.get("county") or addr.get("state_district")
    locality = next((addr.get(k) for k in ("city", "town", "village", "municipality", "hamlet") if addr.get(k)), None)
    parts: list[str] = []
    for part in (locality, admin2, admin1, country):
        if part and part != name and part not in parts:
            parts.append(part)
    return Context(
        country=country,
        country_code=code,
        admin1=admin1,
        admin2=admin2,
        locality=locality,
        label=", ".join(parts) or None,
        source_note="OpenStreetMap address",
    )


def _bbox_from(item: dict[str, Any]) -> BBox | None:
    raw = item.get("boundingbox")
    try:
        south, north, west, east = (float(x) for x in raw)  # Nominatim order: [south, north, west, east]
    except (TypeError, ValueError):
        return None
    if not (-90 <= south <= north <= 90):
        return None
    if west > east:  # the provider used west > east to mean "crosses the antimeridian"
        return G.bbox_from_extent(west, south, east, north)
    if west < -180 or east > 180:
        return None
    return BBox(west=west, south=south, east=east, north=north)


def _floatp(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def osm_key(item: dict[str, Any]) -> str | None:
    letter = TYPE_LETTER.get(str(item.get("osm_type") or "").lower())
    oid = item.get("osm_id")
    if not letter or oid in (None, ""):
        return None
    try:
        return f"{letter}{int(oid)}"
    except (TypeError, ValueError):
        return None


class NominatimClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.enabled = settings.geocoder_enabled
        self.base_url = settings.nominatim_url.rstrip("/")
        self.min_interval = settings.geocoder_min_interval_s
        self.max_results = settings.geocoder_max_results
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()
        self._last = -1e9
        self._cache = TTLCache(settings.geocoder_cache_ttl_s, 512)
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"User-Agent": settings.geocoder_user_agent, "Accept": "application/json"},
            timeout=settings.geocoder_timeout_s,
            transport=transport,
        )
        self.requests_made = 0

    # ----------------------------------------------------------------------------- transport
    def _get(self, path: str, params: dict[str, Any]) -> Any:
        if not self.enabled:
            raise GeocoderUnavailable("geocoder_disabled", "Online geocoding is turned off on this server.")
        key = (path, tuple(sorted(params.items())))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        with self._lock:  # one request at a time, spaced by the policy interval
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
            try:
                response = self._client.get(path, params=params)
            except httpx.TimeoutException as exc:
                raise GeocoderUnavailable("geocoder_unavailable", "The geocoding service did not answer in time.") from exc
            except httpx.HTTPError as exc:
                raise GeocoderUnavailable("geocoder_unavailable", "The geocoding service could not be reached.") from exc
            finally:
                self._last = self._clock()
                self.requests_made += 1
        if response.status_code == 429:
            raise GeocoderUnavailable("geocoder_rate_limited", "The geocoding service asked us to slow down. Try again in a minute.")
        if response.status_code in (401, 403):
            raise GeocoderUnavailable("geocoder_blocked", "The geocoding service refused the request.")
        if response.status_code >= 400:
            raise GeocoderUnavailable("geocoder_unavailable", f"The geocoding service returned HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError as exc:
            raise GeocoderUnavailable("geocoder_unavailable", "The geocoding service returned an unreadable response.") from exc
        self._cache.set(key, data)
        return data

    # ------------------------------------------------------------------------------- search
    def search(self, query: str, limit: int | None = None, language: str = "en") -> list[Candidate]:
        n = max(1, min(limit or self.max_results, 10))
        data = self._get(
            "/search",
            {"q": query, "format": "jsonv2", "addressdetails": 1, "extratags": 1, "limit": n, "dedupe": 1, "accept-language": language},
        )
        if not isinstance(data, list):
            raise GeocoderUnavailable("geocoder_unavailable", "The geocoding service returned an unexpected response.")
        out = [c for c in (self._candidate(item) for item in data) if c is not None]
        # Drop results far less important than the best one; they are rarely what anyone meant.
        imps = [c.provider_importance for c in out if c.provider_importance is not None]
        if len(imps) >= 2 and max(imps) > 0:
            top = max(imps)
            out = [c for i, c in enumerate(out) if i < 3 or c.provider_importance is None or c.provider_importance >= 0.25 * top]
        return out

    def _candidate(self, item: dict[str, Any]) -> Candidate | None:
        key = osm_key(item)
        lat, lon = _floatp(item.get("lat")), _floatp(item.get("lon"))
        if key is None or lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        fclass, label = classify_osm(item)
        name = (item.get("name") or str(item.get("display_name") or "").split(",")[0]).strip()
        if not name:
            return None
        ctx = _context_from(item, name)
        display = f"{name}, {ctx.label}" if ctx.label else name
        return Candidate(
            id=f"osm:{key}",
            name=name,
            display_name=display,
            feature_class=fclass,  # type: ignore[arg-type]
            class_label=label,
            shape_hint=SHAPE_BY_CLASS.get(fclass, "point"),
            context=ctx,
            latitude=lat,
            longitude=lon,
            position_kind="provider_point",
            provider="openstreetmap",
            provider_name="OpenStreetMap Nominatim",
            provider_importance=_floatp(item.get("importance")),
            bbox=_bbox_from(item),
        )

    # ------------------------------------------------------------------------------ lookup
    def lookup(self, key: str, language: str = "en") -> ResolvedLocation:
        """Full details (including outline when the object has one) for an id like ``R1234``."""
        if not key or key[0] not in LETTER_TYPE or not key[1:].isdigit():
            from app.errors import AppError

            raise AppError(400, "invalid_location_id", f"'{key}' is not a valid OpenStreetMap object id (expected N…, W… or R…).")
        probe = self._get("/lookup", {"osm_ids": key, "format": "jsonv2", "addressdetails": 1, "extratags": 1, "accept-language": language})
        if not isinstance(probe, list) or not probe:
            from app.errors import AppError

            raise AppError(404, "location_not_found", f"OpenStreetMap has no object '{key}' (it may have been deleted).")
        base = probe[0]
        fclass, _ = classify_osm(base)
        threshold = {"country": 0.05, "continent": 0.05, "ocean_sea": 0.05, "state_province": 0.01}.get(fclass, 0.002)
        if SHAPE_BY_CLASS.get(fclass) in ("area", "line"):
            data = self._get(
                "/lookup",
                {"osm_ids": key, "format": "jsonv2", "addressdetails": 1, "extratags": 1, "polygon_geojson": 1, "polygon_threshold": threshold, "accept-language": language},
            )
            item = data[0] if isinstance(data, list) and data else base
        else:
            item = base
        return self._resolved(item, key, threshold)

    def _resolved(self, item: dict[str, Any], key: str, threshold: float) -> ResolvedLocation:
        cand = self._candidate(item)
        if cand is None:
            from app.errors import AppError

            raise AppError(502, "geocoder_bad_data", "The geocoding service returned an object without usable coordinates.")
        fclass, label = cand.feature_class, cand.class_label
        geom_json = item.get("geojson")
        checks = ["latitude and longitude are within WGS84 limits"]
        limitations = ["Position and outline are reported by OpenStreetMap contributors and the geocoder; they are not independently verified."]
        out_geom: dict[str, Any] | None = None
        bbox = cand.bbox
        gtype = "Point"
        want_shape = SHAPE_BY_CLASS.get(fclass) in ("area", "line")
        if isinstance(geom_json, dict) and geom_json.get("type") not in (None, "Point"):
            try:
                geom = G.ensure_valid(shape(geom_json))
            except Exception:  # noqa: BLE001 - malformed geometry from the provider: report as unavailable
                geom = None
            if geom is not None and not geom.is_empty:
                checks.append("geometry is valid (OGC simple features)")
                budget = 20_000 if geom.geom_type in ("LineString", "MultiLineString") else 12_000
                simplified, tol = G.simplify_to_budget(geom, budget)
                gtype = simplified.geom_type
                out_geom = G.to_geojson(simplified)
                bbox = G.geometry_bbox(geom)
                area, length = G.geodesic_area_km2(geom), G.geodesic_length_km(geom)
                gen = f"OpenStreetMap outline simplified by the geocoder to about {threshold:g}° tolerance" + (f", then to about {tol:g}° to limit size" if tol else "")
                gi = GeometryInfo(
                    available=True,
                    type=gtype,  # type: ignore[arg-type]
                    quality="generalized",
                    generalization=gen,
                    simplify_tolerance_deg=max(threshold, tol or 0.0),
                    vertex_count=G.vertex_count(simplified),
                    crosses_antimeridian=bbox.crosses_antimeridian,
                    area_km2=round(area, 1) if area is not None else None,
                    length_km=round(length, 1) if length is not None else None,
                )
                limitations.append("The outline is generalized; do not use it for measurement or legal purposes.")
            else:
                gi = GeometryInfo(available=False, quality="unavailable", note="The provider's outline could not be used.")
        elif want_shape:
            gi = GeometryInfo(available=False, quality="unavailable", note="OpenStreetMap returned only a point for this area feature, so it is shown as a point.")
        else:
            gi = GeometryInfo(available=False, quality="not_applicable", note="This feature is a single point in OpenStreetMap.")
        if bbox is None:
            bbox = BBox(west=cand.longitude, south=cand.latitude, east=cand.longitude, north=cand.latitude)

        extra = item.get("extratags") or {}
        facts: list[Fact] = []
        pop = _floatp(str(extra.get("population", "")).replace(",", "").replace(" ", ""))
        if pop and pop > 0:
            facts.append(Fact(key="population", label="Population (OpenStreetMap tag)", value=int(pop), source="OpenStreetMap"))
        ele = _floatp(str(extra.get("ele", "")).replace("m", "").strip())
        if ele is not None:
            facts.append(Fact(key="elevation", label="Elevation (OpenStreetMap tag)", value=round(ele, 1), unit="m", source="OpenStreetMap"))
        for k, lbl in (("wikidata", "Wikidata ID"), ("wikipedia", "Wikipedia article")):
            if extra.get(k):
                facts.append(Fact(key=k, label=lbl, value=str(extra[k]), source="OpenStreetMap"))
        cat, typ = item.get("category") or item.get("class"), item.get("type")
        if cat and typ:
            facts.append(Fact(key="osm_tag", label="OpenStreetMap tag", value=f"{cat}={typ}", source="OpenStreetMap"))

        if out_geom is not None:
            pnote = "Position chosen by the geocoder for this area (usually its centre or administrative centre). It can lie outside an irregular outline."
        else:
            pnote = "Position of this OpenStreetMap object as reported by the geocoder."
        return ResolvedLocation(
            id=cand.id,
            name=cand.name,
            display_name=cand.display_name,
            feature_class=fclass,
            class_label=label,
            geometry_type=gtype if out_geom else "Point",  # type: ignore[arg-type]
            context=cand.context,
            point=PointInfo(latitude=cand.latitude, longitude=cand.longitude, kind="provider_point", note=pnote),
            bbox=bbox,
            geometry=out_geom,
            geometry_info=gi,
            source=SourceInfo(
                provider="openstreetmap",
                provider_name="OpenStreetMap Nominatim",
                dataset="OpenStreetMap",
                source_id=key,
                license="ODbL 1.0",
                attribution=ATTRIBUTION,
                url=OSM_COPYRIGHT_URL,
            ),
            validation=Validation(status="validated_with_limits", checks=checks, limitations=limitations),
            facts=facts,
        )

    def close(self) -> None:
        self._client.close()
