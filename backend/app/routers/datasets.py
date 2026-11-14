"""Health, dataset catalogue, metadata and observations."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from app.config import APP_VERSION
from app.deps import get_store
from app.errors import AppError
from app.schemas import DatasetListResponse, HealthResponse, MetadataResponse, NasaDatasetStatus, ObservationsResponse
from app.services import metadata as md
from app.services.store import NASA_GLOBAL_ONLY, NASA_INTEGRATED, NASA_PENDING, DatasetStore

router = APIRouter(prefix="/api", tags=["datasets"])

Store = Annotated[DatasetStore, Depends(get_store)]
MAX_CSV_ROWS = 500_000


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health(store: Store, request: Request) -> HealthResponse:
    geo = getattr(request.app.state, "geo", None)
    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        datasets_loaded=len(store.list()),
        nasa_dataset_integrated=store.nasa_integrated(),
        geo=geo.status() if geo is not None else None,
    )


@router.get("/datasets", response_model=DatasetListResponse, summary="List available datasets")
def list_datasets(store: Store) -> DatasetListResponse:
    records = store.list()
    integrated = store.nasa_integrated()
    return DatasetListResponse(
        datasets=[store.summarize(r) for r in records],
        default_dataset_id=store.default_id(),
        nasa_dataset=NasaDatasetStatus(integrated=integrated, message=NASA_INTEGRATED if integrated else NASA_GLOBAL_ONLY if store.has_observed_global() else NASA_PENDING),
        package_issues=store.package_issues,
    )


@router.delete("/datasets/{dataset_id}", status_code=204, summary="Delete an uploaded dataset")
def delete_dataset(dataset_id: str, store: Store) -> Response:
    store.delete_upload(dataset_id)
    return Response(status_code=204)


@router.get("/metadata", response_model=MetadataResponse, summary="Variables, regions, units and coverage of a dataset")
def metadata(store: Store, dataset_id: str | None = Query(default=None, max_length=100)) -> MetadataResponse:
    ds_id = dataset_id or store.default_id()
    if ds_id is None:
        raise AppError(404, "no_datasets", "No dataset is loaded. The bundled synthetic demo file is missing.")
    return md.build_metadata(store, store.get(ds_id))


@router.get("/observations", response_model=ObservationsResponse, summary="Paginated observations (JSON) or CSV export")
def observations(
    store: Store,
    dataset_id: Annotated[str, Query(min_length=1, max_length=100)],
    variable: Annotated[str | None, Query(max_length=200)] = None,
    region: Annotated[str | None, Query(max_length=200)] = None,
    start: date | None = None,
    end: date | None = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_missing: bool = True,
    format: Literal["json", "csv"] = "json",
):
    record = store.get(dataset_id)
    df = md.filter_observations(record.data, variable, region, start, end, include_missing)
    if format == "csv":
        if len(df) > MAX_CSV_ROWS:
            raise AppError(413, "export_too_large", f"The export would have {len(df):,} rows; narrow it with variable, region or dates.")
        body = md.observations_csv(record, df)
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="earthtrend_observations.csv"'},
        )
    return md.page_observations(record, df, limit, offset)
