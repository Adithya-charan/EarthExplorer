"""Story (period summary), region list and rule-based chat."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from app.deps import get_store
from app.schemas_story import ChatRequest, ChatResponse, RegionsResponse, StoryRequest, StoryResponse
from app.services import chat as chat_service
from app.services import story as story_service
from app.services.store import DatasetStore

router = APIRouter(prefix="/api", tags=["story"])
Store = Annotated[DatasetStore, Depends(get_store)]


@router.get("/regions", response_model=RegionsResponse, summary="Regions in a dataset with map extents")
def regions(store: Store, dataset_id: Annotated[str, Query(min_length=1, max_length=100)]) -> RegionsResponse:
    return story_service.list_regions(store.get(dataset_id))


@router.post("/story", response_model=StoryResponse, summary="Evidence-tagged text summary of one region and period")
async def story(req: StoryRequest, store: Store) -> StoryResponse:
    return await run_in_threadpool(story_service.build_story, store.get(req.dataset_id), req)


@router.post("/chat", response_model=ChatResponse, summary="Rule-based chat about the loaded dataset (no external AI)")
async def chat(req: ChatRequest, store: Store) -> ChatResponse:
    return await run_in_threadpool(chat_service.answer, store.get(req.dataset_id), req)


# ---- Gridded datasets -------------------------------------------------------------------------
from datetime import date as _date  # noqa: E402
from pathlib import PurePath  # noqa: E402

import pandas as pd  # noqa: E402
from fastapi import File, Form, UploadFile  # noqa: E402

from app.config import Settings  # noqa: E402
from app.deps import get_app_settings  # noqa: E402
from app.errors import not_found  # noqa: E402
from app.routers.ingest import read_limited  # noqa: E402
from app.schemas import QualityReport  # noqa: E402
from app.schemas_story import GridFrame, GridUploadResponse  # noqa: E402
from app.services import grid as grid_service  # noqa: E402
from app.services.ingestion.base import safe_filename  # noqa: E402
from app.services.provenance import build_provenance  # noqa: E402

Cfg = Annotated[Settings, Depends(get_app_settings)]


@router.post("/upload-grid", response_model=GridUploadResponse, summary="Import a NetCDF grid (time, latitude, longitude)")
async def upload_grid(
    store: Store,
    cfg: Cfg,
    file: Annotated[UploadFile, File(description="NetCDF file")],
    variable: Annotated[str | None, Form(max_length=200)] = None,
    dataset_name: Annotated[str | None, Form(max_length=200)] = None,
    region_label: Annotated[str, Form(max_length=200)] = "Whole grid area",
) -> GridUploadResponse:
    name = safe_filename(file.filename)
    content = await read_limited(file, cfg.max_upload_bytes, cfg.max_upload_mb)
    g = await run_in_threadpool(grid_service.read_netcdf, content, variable, name)
    rows = grid_service.regional_mean_rows(g, region_label.strip() or "Whole grid area")
    n_missing = int(rows["value"].isna().sum())
    quality = QualityReport(
        n_source_rows=len(rows), n_rows_retained=len(rows), n_rows_dropped=0, n_invalid_dates=0, n_invalid_values=0,
        n_invalid_labels=0, n_missing_values=n_missing, n_duplicate_identical=0, n_duplicate_conflicting=0,
        duplicate_policy="error", n_series=1, variables=[g.variable], regions=[region_label],
        units_by_variable={g.variable: [g.unit or "unspecified"]}, date_min=g.times.min().date(), date_max=g.times.max().date(),
        issues=[], ambiguities=[], can_import=True, requires_confirmation=False,
    )
    rec = store.add_upload(rows, dataset_name or PurePath(name).stem, name, quality, grid=g)
    pct = float(100 * (~pd.notna(g.values)).mean())
    return GridUploadResponse(
        dataset_id=rec.id, name=rec.name, variable=g.variable, unit=g.unit or "unspecified", n_times=len(g.times),
        n_lat=len(g.lat), n_lon=len(g.lon), date_start=g.times.min().date(), date_end=g.times.max().date(),
        n_missing_cells_pct=pct,
        message=f"Imported a {len(g.lat)}×{len(g.lon)} grid with {len(g.times)} time steps. The regional series is an area-weighted mean over valid cells.",
    )


@router.get("/grid", response_model=GridFrame, summary="Per-cell values for one month of a gridded dataset")
def grid_frame(store: Store, dataset_id: Annotated[str, Query(min_length=1, max_length=100)], month: _date) -> GridFrame:
    rec = store.get(dataset_id)
    g = rec.extra.get("grid")
    if g is None:
        raise not_found("not_gridded", "This dataset has no per-cell grid; only region-level values exist.")
    f = grid_service.frame(g, pd.Timestamp(month))
    return GridFrame(
        provenance=build_provenance(rec), dataset_id=rec.id, variable=g.variable, unit=g.unit or "unspecified",
        note="Per-cell values exactly as in the uploaded file (missing cells stay empty).", **f,
    )


# ---- Whole-record overview and atlas ---------------------------------------------------------
from app.schemas_story import AtlasResponse, OverviewResponse, SnapshotResponse  # noqa: E402
from app.services import overview as overview_service  # noqa: E402


@router.get("/overview", response_model=OverviewResponse, summary="Whole-record overview of one region")
async def overview(
    store: Store,
    dataset_id: Annotated[str, Query(min_length=1, max_length=100)],
    region: Annotated[str, Query(min_length=1, max_length=200)],
    variable: Annotated[str | None, Query(max_length=200)] = None,
) -> OverviewResponse:
    return await run_in_threadpool(overview_service.build_overview, store.get(dataset_id), region, variable)


@router.get("/atlas", response_model=AtlasResponse, summary="Year-by-year standardised anomaly for every region")
async def atlas(
    store: Store,
    dataset_id: Annotated[str, Query(min_length=1, max_length=100)],
    variable: Annotated[str | None, Query(max_length=200)] = None,
) -> AtlasResponse:
    return await run_in_threadpool(overview_service.build_atlas, store.get(dataset_id), variable)


@router.get("/snapshot", response_model=SnapshotResponse, summary="Every region with a known position, for one month or year")
async def snapshot(
    store: Store,
    dataset_id: Annotated[str, Query(min_length=1, max_length=100)],
    year: Annotated[int, Query(ge=1, le=9999)],
    month: Annotated[int, Query(ge=0, le=12)] = 0,
    variable: Annotated[str | None, Query(max_length=200)] = None,
) -> SnapshotResponse:
    return await run_in_threadpool(overview_service.build_snapshot, store.get(dataset_id), variable, year, month)
