"""Earth Explorer API: geocoding, location resolution, visualization preview / confirmation, reference geography."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from app.errors import AppError
from app.geo.coords import parse_coordinates
from app.geo.resolver import check_location_id
from app.geo.schemas import (
    ConfirmRequest,
    GeneratedVisualization,
    GeocodeResponse,
    PreviewRequest,
    PreviewResponse,
    ResolvedLocation,
    ResolveRequest,
    ResolveResponse,
)
from app.geo.services import GeoServices
from app.geo.terrain import ElevationResult

router = APIRouter(prefix="/api", tags=["earth-explorer"])

LANGUAGE_PATTERN = r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$"
GEOCODER_FAILURES = {"geocoder_unavailable", "geocoder_rate_limited", "geocoder_blocked"}


def get_geo(request: Request) -> GeoServices:
    return request.app.state.geo


Geo = Annotated[GeoServices, Depends(get_geo)]
Language = Annotated[str, Query(pattern=LANGUAGE_PATTERN, description="Preferred language for place names (ISO 639-1 code).")]


@router.get("/geocode", response_model=GeocodeResponse, summary="Find places by name or coordinates")
def geocode(
    geo: Geo,
    q: Annotated[str, Query(min_length=1, max_length=200, description="A place name, or coordinates such as '48.8584, 2.2945'.")],
    limit: Annotated[int, Query(ge=1, le=10)] = 8,
    online: Annotated[bool, Query(description="Also search OpenStreetMap (ignored when suggest=true).")] = True,
    suggest: Annotated[bool, Query(description="Offline type-ahead from the reference atlas only; partial names match.")] = False,
    language: Language = "en",
) -> GeocodeResponse:
    query = re.sub(r"\s+", " ", q).strip()
    if not query:
        raise AppError(422, "empty_query", "Type a place name or coordinates to search.")
    parsed = parse_coordinates(query)  # coordinate-shaped text with impossible values raises a 422 here
    if parsed is not None:
        cand = geo.resolver.coordinate_candidate(*parsed)
        return GeocodeResponse(query=query, candidates=[cand], sources={"user": "coordinates parsed from the text"})
    cands, sources, messages = geo.resolver.candidates(query, online=online, language=language, limit=limit, suggest=suggest)
    attributions: list[str] = []
    if any(c.provider in ("natural_earth", "builtin") for c in cands):
        attributions.append("Made with Natural Earth (public domain)")
    if any(c.provider == "openstreetmap" for c in cands):
        attributions.append("© OpenStreetMap contributors (ODbL 1.0)")
    return GeocodeResponse(query=query, candidates=cands, sources=sources, messages=messages, attributions=attributions)


@router.get("/locations/{location_id}", response_model=ResolvedLocation, summary="Full details and geometry of one location")
def get_location(geo: Geo, location_id: str, language: Language = "en") -> ResolvedLocation:
    return geo.resolver.resolve_id(check_location_id(location_id), language)


@router.post("/locations/resolve", response_model=ResolveResponse, summary="Resolve names, coordinates or chosen candidates")
def resolve_locations(body: ResolveRequest, geo: Geo) -> ResolveResponse:
    """Every item comes back ``resolved`` or with a reason it is not.

    A name with more than one possible place is returned as ``ambiguous`` together with its candidates; it is
    never resolved on the caller's behalf. Send the chosen ``candidate_id`` back to resolve it.
    """
    results = [geo.resolver.resolve_item(item, online=body.online, language=body.language) for item in body.items]
    codes = {m.code for r in results for m in r.messages}
    if not geo.nominatim.enabled or not body.online:
        online_state: Literal["used", "disabled", "unavailable"] = "disabled"
    elif codes & GEOCODER_FAILURES:
        online_state = "unavailable"
    else:
        online_state = "used"
    return ResolveResponse(results=results, online_geocoder=online_state, all_resolved=all(r.status == "resolved" for r in results))


@router.post("/visualization/preview", response_model=PreviewResponse, summary="Confirmation summary for the chosen locations and settings")
def preview(body: PreviewRequest, geo: Geo) -> PreviewResponse:
    return geo.viz.preview(body)


@router.post("/visualization/confirm", response_model=GeneratedVisualization, summary="Generate the visualization after explicit confirmation")
def confirm(body: ConfirmRequest, geo: Geo) -> GeneratedVisualization:
    return geo.viz.confirm(body)


@router.get("/geography/boundaries", summary="Natural Earth boundaries as GeoJSON")
def boundaries(
    geo: Geo,
    response: Response,
    layer: Literal["countries", "admin1", "marine", "regions", "rivers", "lakes"] = "countries",
    ids: Annotated[str | None, Query(max_length=2000, description="Comma-separated location ids (required unless layer=countries).")] = None,
    simplify: Annotated[float, Query(ge=0, le=5, description="Simplification tolerance in degrees (0 = as stored).")] = 0.0,
) -> dict[str, Any]:
    id_list: list[str] | None = None
    if ids:
        id_list = [check_location_id(i.strip()) for i in ids.split(",") if i.strip()]
        if len(id_list) > 50:
            raise AppError(422, "too_many_ids", "Request at most 50 features at a time.")
    collection = geo.gazetteer.feature_collection(layer, id_list, simplify)
    collection["source"] = {
        "provider": "Natural Earth",
        "license": "Public domain",
        "url": "https://www.naturalearthdata.com",
        "scale": "1:50 million (countries) / 1:10 million (other layers)",
        "note": "Generalized cartographic outlines. They are not survey-grade and not legal borders; disputed areas follow Natural Earth's de facto treatment.",
        "simplify_tolerance_deg": simplify,
    }
    response.headers["Cache-Control"] = "public, max-age=3600"
    return collection


@router.get("/geography/terrain", summary="How to load the elevation data used for terrain shading")
def terrain(geo: Geo, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=3600"
    return geo.terrain.descriptor()


@router.get("/geography/elevation", response_model=ElevationResult, summary="Sample the terrain elevation at a point")
def elevation(
    geo: Geo,
    lat: float,
    lon: float,
    zoom: Annotated[int | None, Query(ge=0, le=14)] = None,
) -> ElevationResult:
    return geo.terrain.elevation(lat, lon, zoom)
