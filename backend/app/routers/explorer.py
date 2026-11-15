"""Earth Time Machine API: locations, sessions, datasets, observation layers, change detection, AI explanation."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from app.errors import AppError, not_found, unprocessable
from app.explorer.change import ChangeDetectionService, check_period, dataset_info
from app.explorer.datasets import inspect_file
from app.explorer.rendering import difference_geotiff
from app.explorer.schemas import (
    ChangeSummary, ChatAnswer, ChatRequest, DatasetInfo, DetectRequest, Explanation, Insufficient, LocationOut, ObservationInfo, SessionRequest, SessionResponse,
)
from app.explorer.services import ExplorerServices

router = APIRouter(prefix="/api/explorer", tags=["explorer"])
PNG_HEADERS = {"Cache-Control": "public, max-age=3600"}


def get_services(request: Request) -> ExplorerServices:
    return request.app.state.explorer


Svc = Annotated[ExplorerServices, Depends(get_services)]


def _need_order(a: int, b: int) -> None:
    if a >= b:
        raise unprocessable("invalid_period", "The start year must be earlier than the end year.")


# ----------------------------------------------------------------------------------- locations
@router.get("/locations/search", response_model=list[LocationOut])
def search_locations(svc: Svc, q: Annotated[str, Query(min_length=1, max_length=200)], online: bool = True) -> list[LocationOut]:
    return svc.locations.search(q, online=online)


@router.get("/locations/{location_id:path}", response_model=LocationOut)
def get_location(location_id: str, svc: Svc) -> LocationOut:
    loc = svc.locations.get(location_id)
    if loc is None:
        raise not_found("location_not_found", f"No location with id '{location_id}'.")
    return loc


# ------------------------------------------------------------------------------------- session
@router.post("/session", response_model=SessionResponse)
def start_session(body: SessionRequest, svc: Svc) -> SessionResponse:
    _need_order(body.start_year, body.end_year)
    examples = svc.locations.examples()
    alternatives: list[LocationOut] = []
    if body.lat is not None and body.lon is not None:
        loc = svc.locations.from_point(body.lat, body.lon)
    elif body.location_id:
        loc = svc.locations.get(body.location_id)
        if loc is None:
            return SessionResponse(status="not_found", message=f"The location id '{body.location_id}' is not known.", examples=examples)
    elif body.query and body.query.strip():
        found = svc.locations.search(body.query, online=body.online)
        if not found:
            return SessionResponse(
                status="not_found", examples=examples,
                message=f"No place called \"{body.query.strip()}\" could be found. Check the spelling, add the city or country, or try one of the examples.",
            )
        loc, alternatives = found[0], found[1:]
    else:
        raise unprocessable("missing_location", "Give a place name, a location id, or coordinates.")

    datasets = svc.datasets.covering(loc.lat, loc.lon)
    if not datasets:
        ins = Insufficient(
            code="no_dataset", reason=f"No loaded dataset covers {loc.name}. The globe can show the place, but there are no observations to compare over time.",
            missing=["a dataset whose footprint contains this location"],
        )
        return SessionResponse(
            status="no_dataset", location=loc, alternatives=alternatives, examples=examples, insufficient=ins,
            message=f"Found {loc.display_name}, but no dataset covers it. Places with data: " + ", ".join(d.meta["name"] for d in svc.datasets.list()) + ".",
        )
    infos = [dataset_info(svc.datasets, d) for d in datasets]
    ds = datasets[0]
    period = check_period(ds, body.start_year, body.end_year)
    latest = svc.history.latest(ds, loc.name)
    base: dict[str, Any] = dict(location=loc, alternatives=alternatives, examples=examples, datasets=infos, dataset=infos[0], period=period, latest=latest, is_synthetic=ds.is_synthetic, simulated_label=ds.meta.get("simulated_label"))
    if period.status in ("outside", "too_short"):
        ins = Insufficient(code=f"period_{period.status}", reason=" ".join(period.messages), missing=["observations inside the requested period"], suggested_period={"start_year": int(ds.meta["coverage"]["start"][:4]), "end_year": int(ds.meta["coverage"]["end"][:4])})
        return SessionResponse(status="period_unsupported", message=" ".join(period.messages), insufficient=ins, **base)
    return SessionResponse(status="ready", message=" ".join(period.messages) or f"Dataset {ds.meta['name']} covers this location.", **base)


# ------------------------------------------------------------------------------------ datasets
@router.get("/datasets", response_model=list[DatasetInfo])
def list_datasets(svc: Svc) -> list[DatasetInfo]:
    return [dataset_info(svc.datasets, d) for d in svc.datasets.list()]


@router.get("/datasets/{dataset_id}", response_model=DatasetInfo)
def get_dataset(dataset_id: str, svc: Svc) -> DatasetInfo:
    return dataset_info(svc.datasets, svc.datasets.get(dataset_id))


@router.get("/datasets/{dataset_id}/observations", response_model=list[ObservationInfo])
def list_observations(dataset_id: str, svc: Svc, start_year: int | None = None, end_year: int | None = None) -> list[ObservationInfo]:
    ds = svc.datasets.get(dataset_id)
    obs = svc.history.timeline(ds)
    return [o for o in obs if (start_year is None or int(o.date[:4]) >= start_year) and (end_year is None or int(o.date[:4]) <= end_year)]


@router.get("/datasets/{dataset_id}/validate")
def validate_dataset(dataset_id: str, svc: Svc) -> dict[str, Any]:
    ds = svc.datasets.get(dataset_id)
    files = [inspect_file(ds.root / o.file) for o in ds.observations[:3]]
    return {"id": ds.id, "metadata_valid": True, "issues": ds.issues, "sample_files": files, "grid": {"width": ds.width, "height": ds.height, "crs": ds.crs.to_string()}}


@router.get("/datasets/{dataset_id}/observations/{iso}/layer.png")
def observation_layer(dataset_id: str, iso: str, svc: Svc) -> Response:
    ds = svc.datasets.get(dataset_id)
    o = ds.obs_by_date(iso)
    if o is None:
        raise not_found("observation_not_found", f"{ds.meta['name']} has no observation dated {iso}. Observations are never interpolated.")
    arr = svc.datasets.read(ds, o)
    return Response(svc.rendering.observation_png(ds, o.iso, arr), media_type="image/png", headers=PNG_HEADERS)


# ----------------------------------------------------------------------------------- analysis
def _summary(svc: ExplorerServices, body: DetectRequest) -> tuple[ChangeSummary, Any]:
    _need_order(body.start_year, body.end_year)
    if body.dataset_id:
        ds = svc.datasets.get(body.dataset_id)
    elif body.lat is not None and body.lon is not None:
        found = svc.datasets.covering(body.lat, body.lon)
        if not found:
            return svc.changes.no_dataset(None, body.start_year, body.end_year), None
        ds = found[0]
    else:
        raise unprocessable("missing_target", "Give a dataset_id, or lat and lon.")
    loc = ds.meta.get("location", {}).get("name")
    res = svc.changes.detect(ds, body.start_year, body.end_year, body.params, loc)
    return (res.summary, res) if hasattr(res, "summary") else (res, None)


@router.post("/analysis/detect-change", response_model=ChangeSummary)
def detect_change(body: DetectRequest, svc: Svc) -> ChangeSummary:
    return _summary(svc, body)[0]


@router.get("/analysis/{analysis_id}/change-summary", response_model=ChangeSummary)
def change_summary(analysis_id: str, svc: Svc) -> ChangeSummary:
    return svc.changes.get(analysis_id).summary


@router.get("/analysis/{analysis_id}/hotspots")
def hotspots(analysis_id: str, svc: Svc) -> JSONResponse:
    rec = svc.changes.get(analysis_id)
    return JSONResponse(rec.hotspot_geojson, headers={"Cache-Control": "public, max-age=600"})


@router.get("/analysis/{analysis_id}/change-layers")
def change_layers(analysis_id: str, svc: Svc) -> dict[str, Any]:
    s = svc.changes.get(analysis_id).summary
    return {
        "bbox": s.bbox, "layers": s.layers, "first_observation": s.first_observation, "last_observation": s.last_observation,
        "legend": [
            {"key": "water", "label": "Water (unchanged)", "color": "#388bfd"}, {"key": "loss", "label": "Water lost", "color": "#e63946"},
            {"key": "gain", "label": "Water gained", "color": "#2ecc71"}, {"key": "land", "label": "Unchanged land", "color": "#7a808c"},
            {"key": "uncertain", "label": "Uncertain (cloud / no data)", "color": "#cdd7e8", "hatched": True},
        ],
    }


@router.get("/analysis/{analysis_id}/layers/{name}")
def analysis_layer(analysis_id: str, name: str, svc: Svc) -> Response:
    rec = svc.changes.get(analysis_id)
    ds = svc.datasets.get(rec.dataset_id)
    if rec.diff is None:
        raise not_found("no_layers", "This analysis has no map layers.")
    if name == "difference.png":
        return Response(svc.rendering.difference_png(analysis_id, rec.diff), media_type="image/png", headers=PNG_HEADERS)
    if name in ("before.png", "after.png"):
        w, ok = (rec.w0, rec.ok0) if name == "before.png" else (rec.w1, rec.ok1)
        return Response(svc.rendering.composite_png(analysis_id, name, w, ok), media_type="image/png", headers=PNG_HEADERS)  # type: ignore[arg-type]
    if name == "difference.tif":
        tags = {"CLASSES": "0=uncertain,1=unchanged land,2=unchanged water,3=water lost,4=water gained", "ANALYSIS": analysis_id, "SYNTHETIC": str(ds.is_synthetic).lower()}
        return Response(difference_geotiff(ds, rec.diff, tags), media_type="image/tiff", headers={"Content-Disposition": f'attachment; filename="{analysis_id}-difference.tif"'})
    raise not_found("layer_not_found", f"Unknown layer '{name}'. Use difference.png, before.png, after.png or difference.tif.")


@router.post("/analysis/{analysis_id}/explain", response_model=Explanation)
def explain(analysis_id: str, svc: Svc) -> Explanation:
    return svc.ai.explain(svc.changes.get(analysis_id))


@router.post("/ai/chat", response_model=ChatAnswer)
def ai_chat(body: ChatRequest, svc: Svc) -> ChatAnswer:
    rec = svc.changes.get(body.analysis_id) if body.analysis_id else None
    return svc.ai.chat(body.question, rec, body.history)
