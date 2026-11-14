"""Turn user input (place names, coordinates, candidate ids) into resolved locations.

The central rule: **a name that matches more than one place is never resolved on the user's behalf.**
Exactly one candidate resolves automatically (and is reported as ``only_match``); two or more produce an
``ambiguous`` result with the candidates and their geographic context, and nothing proceeds until the
caller sends back the chosen ``candidate_id``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.config import Settings
from app.errors import AppError
from app.geo import geometry as G
from app.geo.coords import coordinate_id, format_coordinates, parse_coordinate_id, parse_coordinates, validate_latlon
from app.geo.naturalearth import Gazetteer
from app.geo.nominatim import GeocoderUnavailable, NominatimClient, TTLCache
from app.geo.schemas import (
    BBox,
    Candidate,
    Context,
    GeometryInfo,
    Message,
    PointInfo,
    ResolvedLocation,
    ResolveItem,
    ResolveItemResult,
    SourceInfo,
    Validation,
)
from app.geo.text import fold

log = logging.getLogger("earthtrend.geo")

# Sources whose geometry / metadata is better for each class when the same place is found twice.
PREFER_LOCAL = {"country", "state_province", "continent", "ocean_sea", "mountain_range", "desert", "river", "lake", "island", "region"}
# Maximum distance (km) between two candidates for them to count as the same place.
SAME_PLACE_KM = {
    "city": 50.0,
    "mountain_peak": 25.0,
    "landmark": 5.0,
    "country": 2500.0,
    "continent": 6000.0,
    "ocean_sea": 6000.0,
    "state_province": 900.0,
    "desert": 3500.0,
    "mountain_range": 3500.0,
    "river": 3500.0,
    "lake": 600.0,
    "island": 800.0,
    "region": 1500.0,
}
KM_PER_DEGREE = 111.195


def _km(a: Candidate, b: Candidate) -> float:
    return G.angular_distance_deg(a.latitude, a.longitude, b.latitude, b.longitude) * KM_PER_DEGREE


def _same_place(a: Candidate, b: Candidate) -> bool:
    if a.feature_class != b.feature_class:
        return False
    fa, fb = fold(a.name), fold(b.name)
    if a.feature_class == "country":
        ca, cb = a.context.country_code, b.context.country_code
        if ca and cb:
            return ca == cb
    name_match = fa == fb or (len(fa) >= 4 and len(fb) >= 4 and (fa in fb or fb in fa))
    if not name_match:
        return False
    if a.feature_class in ("city", "state_province") and a.context.country_code and b.context.country_code and a.context.country_code != b.context.country_code:
        return False
    return _km(a, b) <= SAME_PLACE_KM.get(a.feature_class, 100.0)


def merge_candidates(local: list[Candidate], online: list[Candidate]) -> list[Candidate]:
    """Combine reference-atlas and OpenStreetMap candidates, collapsing the same place found in both.

    For classes where Natural Earth carries trusted outlines (countries, states, oceans, ranges, rivers, lakes ...)
    the Natural Earth candidate is kept; for cities, peaks and landmarks the OpenStreetMap candidate is kept
    because its point is far more precise. The dropped duplicate is noted in ``also_matched``.
    """
    kept: list[Candidate] = list(local)
    for o in online:
        match_idx = next((i for i, k in enumerate(kept) if _same_place(k, o)), None)
        if match_idx is None:
            kept.append(o)
            continue
        k = kept[match_idx]
        if k.feature_class in PREFER_LOCAL:
            k.also_matched = sorted(set(k.also_matched + [o.provider_name]))
        else:
            o.also_matched = sorted(set(o.also_matched + [k.provider_name] + k.also_matched))
            # keep the Natural Earth population / capital info in the OSM candidate's note
            kept[match_idx] = o
    return kept


def _name_rank(c: Candidate, q: str) -> int:
    n = fold(c.name)
    if n == q:
        return 0
    if n.startswith(q):
        return 1
    return 2


class Resolver:
    def __init__(self, gazetteer: Gazetteer, nominatim: NominatimClient, settings: Settings):
        self.gazetteer = gazetteer
        self.nominatim = nominatim
        self._cache = TTLCache(2 * 3600, 512)

    # --------------------------------------------------------------------------- candidates
    def candidates(self, query: str, *, online: bool = True, language: str = "en", limit: int = 8, suggest: bool = False) -> tuple[list[Candidate], dict[str, str], list[Message]]:
        """(candidates, per-source status, messages). ``suggest`` lists partial matches too (autocomplete)."""
        sources: dict[str, str] = {}
        messages: list[Message] = []
        local: list[Candidate] = []
        try:
            local = self.gazetteer.search(query, limit=12 if suggest else 10, exact_if_any=not suggest)
            sources["natural_earth"] = f"{len(local)} match(es)"
        except AppError as exc:
            sources["natural_earth"] = "unavailable"
            messages.append(Message(code=exc.code, severity="warning", text=exc.message))
        remote: list[Candidate] = []
        if online and not suggest:
            try:
                remote = self.nominatim.search(query, limit=limit, language=language)
                sources["openstreetmap"] = f"{len(remote)} match(es)"
            except GeocoderUnavailable as exc:
                sources["openstreetmap"] = "unavailable" if exc.code != "geocoder_disabled" else "disabled"
                messages.append(Message(code=exc.code, severity="warning", text=exc.message + " Only the offline reference atlas was searched."))
        elif not online:
            sources["openstreetmap"] = "not searched"
        merged = merge_candidates(local, remote)
        q = fold(query.split(",")[0])
        merged.sort(key=lambda c: (_name_rank(c, q), -(c.provider_importance or 0.0)))
        return merged[:limit], sources, messages

    # ------------------------------------------------------------------------------ by id
    def resolve_id(self, location_id: str, language: str = "en") -> ResolvedLocation:
        key = (location_id, language)
        cached = self._cache.get(key)
        if cached is not None:
            return cached.model_copy(deep=True)
        loc = self._resolve_id_uncached(location_id, language)
        self._cache.set(key, loc)
        return loc.model_copy(deep=True)

    def _resolve_id_uncached(self, location_id: str, language: str) -> ResolvedLocation:
        if location_id.startswith("coord:"):
            latlon = parse_coordinate_id(location_id)
            if latlon is None:
                raise AppError(400, "invalid_location_id", f"'{location_id}' is not a valid coordinate id (expected coord:<lat>,<lon>).")
            return self.resolve_coordinates(*latlon)
        if location_id.startswith(("ne:", "builtin:")):
            return self.gazetteer.get(location_id)
        if location_id.startswith("osm:"):
            try:
                return self.nominatim.lookup(location_id[4:], language)
            except GeocoderUnavailable as exc:
                raise AppError(503, exc.code, exc.message) from exc
        raise AppError(400, "invalid_location_id", f"'{location_id}' is not a recognised location id.")

    # ------------------------------------------------------------------------ coordinates
    def resolve_coordinates(self, lat: float, lon: float, label: str | None = None) -> ResolvedLocation:
        lat, lon = validate_latlon(lat, lon)
        lat, lon = round(lat, 6), round(lon, 6)
        try:
            ctx = self.gazetteer.locate(lat, lon)
        except AppError:
            ctx = Context(source_note="Country lookup is unavailable because the reference atlas is not installed.")
        name = label.strip() if label and label.strip() else format_coordinates(lat, lon)
        return ResolvedLocation(
            id=coordinate_id(lat, lon),
            name=name,
            display_name=name,
            feature_class="coordinate",
            class_label="Custom coordinates",
            geometry_type="Point",
            context=ctx,
            point=PointInfo(latitude=lat, longitude=lon, kind="user_supplied", note="Coordinates exactly as entered (WGS84 latitude / longitude)."),
            bbox=BBox(west=lon, south=lat, east=lon, north=lat),
            geometry=None,
            geometry_info=GeometryInfo(available=False, quality="not_applicable", note="A single point entered by the user."),
            source=SourceInfo(
                provider="user",
                provider_name="Entered by you",
                license="Not applicable",
                attribution="Coordinates supplied by the user; not verified.",
            ),
            validation=Validation(
                status="user_supplied_unverified",
                checks=["latitude is within -90 to 90", "longitude is within -180 to 180"],
                limitations=["Whether these coordinates are the place you meant is not checked.", "Country and region come from Natural Earth polygons and may be wrong near coasts and borders."],
            ),
            resolution="coordinates",
        )

    def coordinate_candidate(self, lat: float, lon: float) -> Candidate:
        """A candidate for coordinate text, so the search box can offer it like any other match."""
        loc = self.resolve_coordinates(lat, lon)
        return Candidate(
            id=loc.id,
            name=loc.name,
            display_name=loc.display_name,
            feature_class="coordinate",
            class_label=loc.class_label,
            shape_hint="point",
            context=loc.context,
            latitude=loc.point.latitude,
            longitude=loc.point.longitude,
            position_kind="user_supplied",
            provider="user",
            provider_name="Entered by you",
            bbox=loc.bbox,
            note="Plotted exactly where entered; whether it is the place you meant is not checked.",
        )

    # ---------------------------------------------------------------------------- items
    def resolve_item(self, item: ResolveItem, *, online: bool = True, language: str = "en") -> ResolveItemResult:
        try:
            return self._resolve_item(item, online, language)
        except AppError as exc:
            status = "invalid" if exc.status_code in (400, 422) else ("not_found" if exc.status_code == 404 else "error")
            return ResolveItemResult(
                ref=item.ref,
                status=status,  # type: ignore[arg-type]
                query=item.query,
                messages=[Message(code=exc.code, severity="error", text=exc.message)],
            )

    def _resolve_item(self, item: ResolveItem, online: bool, language: str) -> ResolveItemResult:
        if item.coordinates is not None:
            c = item.coordinates
            loc = self.resolve_coordinates(c.lat, c.lon, c.label)
            return ResolveItemResult(ref=item.ref, status="resolved", resolved=loc)

        if item.candidate_id is not None:
            loc = self.resolve_id(item.candidate_id, language)
            loc.resolution = "user_selected"
            return ResolveItemResult(ref=item.ref, status="resolved", resolved=loc)

        query = item.query or ""
        parsed = parse_coordinates(query)  # raises a 422 for coordinate-shaped but invalid text
        if parsed is not None:
            loc = self.resolve_coordinates(*parsed)
            return ResolveItemResult(ref=item.ref, status="resolved", query=query, resolved=loc)

        cands, sources, messages = self.candidates(query, online=online, language=language)
        if not cands:
            if any(v == "unavailable" for v in sources.values()):
                # A search source failed, so "not found" would be a guess: report an error the user can retry.
                messages.append(Message(code="search_incomplete", severity="warning", text=f"'{query}' was not found, but a search source was unavailable, so a match may exist. Try again, or enter coordinates."))
                return ResolveItemResult(ref=item.ref, status="error", query=query, messages=messages)
            messages.append(Message(code="no_match", severity="warning", text=f"No place named '{query}' was found. Check the spelling, add a country (for example 'Paris, France') or enter coordinates."))
            return ResolveItemResult(ref=item.ref, status="not_found", query=query, messages=messages)
        if len(cands) == 1:
            try:
                loc = self.resolve_id(cands[0].id, language)
            except AppError as exc:
                messages.append(Message(code=exc.code, severity="error", text=exc.message))
                return ResolveItemResult(ref=item.ref, status="error", query=query, candidates=cands, messages=messages)
            loc.query = query
            loc.resolution = "only_match"
            loc.also_matched = sorted(set(loc.also_matched + cands[0].also_matched))
            return ResolveItemResult(ref=item.ref, status="resolved", query=query, resolved=loc, candidates=cands, messages=messages)
        messages.append(Message(code="ambiguous", severity="warning", text=f"'{query}' matches {len(cands)} different places. Choose the one you mean."))
        return ResolveItemResult(ref=item.ref, status="ambiguous", query=query, candidates=cands, messages=messages)


SAFE_ID = re.compile(r"^[A-Za-z0-9:_.,+\-]+$")


def check_location_id(location_id: str) -> str:
    """Reject ids with characters that could never be produced by this service."""
    if not SAFE_ID.match(location_id) or len(location_id) > 128:
        raise AppError(400, "invalid_location_id", "That is not a valid location id.")
    return location_id


def describe(loc: ResolvedLocation) -> dict[str, Any]:
    return {"id": loc.id, "name": loc.name}
