"""Trend analysis, regional comparison, explanation and methodology."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from app.deps import get_store
from app.errors import unprocessable
from app.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    CompareRequest,
    CompareResponse,
    ExplainRequest,
    ExplainResponse,
    MethodologyResponse,
)
from app.schemas_diagnostics import DiagnosticsResponse
from app.services import analysis, diagnostics_report
from app.services.explain import explain_analysis, explain_comparison
from app.services.methodology import methodology
from app.services.store import DatasetStore

router = APIRouter(prefix="/api", tags=["analysis"])

Store = Annotated[DatasetStore, Depends(get_store)]


@router.post("/analyze", response_model=AnalyzeResponse, summary="Trend analysis of one variable in one region")
async def analyze(req: AnalyzeRequest, store: Store) -> AnalyzeResponse:
    record = store.get(req.dataset_id)
    return await run_in_threadpool(analysis.analyze_series, record, req)


@router.post("/compare", response_model=CompareResponse, summary="Compare one variable across several regions")
async def compare(req: CompareRequest, store: Store) -> CompareResponse:
    record = store.get(req.dataset_id)
    return await run_in_threadpool(analysis.compare_regions, record, req)


@router.get("/diagnostics", response_model=DiagnosticsResponse, summary="Missingness, month-of-year, autocorrelation and random-error diagnostics")
async def diagnostics(
    store: Store,
    dataset_id: Annotated[str, Query(min_length=1, max_length=100)],
    variable: Annotated[str, Query(min_length=1, max_length=200)],
    region: Annotated[str, Query(min_length=1, max_length=200)],
    start: date | None = None,
    end: date | None = None,
) -> DiagnosticsResponse:
    record = store.get(dataset_id)
    return await run_in_threadpool(diagnostics_report.build_diagnostics, record, variable, region, start, end)


@router.post(
    "/explain",
    response_model=ExplainResponse,
    summary="Rule-based explanation of a computed analysis or comparison (no external AI)",
)
def explain(req: ExplainRequest) -> ExplainResponse:
    if (req.analysis is None) == (req.comparison is None):
        raise unprocessable("invalid_explain_request", "Provide exactly one of 'analysis' or 'comparison'.")
    if req.analysis is not None:
        return ExplainResponse(explanation=explain_analysis(req.analysis))
    return ExplainResponse(explanation=explain_comparison(req.comparison))  # type: ignore[arg-type]


@router.get("/methodology", response_model=MethodologyResponse, summary="Methods, defaults and references")
def get_methodology() -> MethodologyResponse:
    return methodology()
