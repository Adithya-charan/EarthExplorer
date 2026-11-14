"""CSV profiling and import."""

from __future__ import annotations

from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.deps import get_app_settings, get_store
from app.errors import AppError, unprocessable
from app.schemas import ColumnMapping, SourceProfile, UploadResponse
from app.services.ingestion.base import DataSource, safe_filename
from app.services.ingestion.registry import adapter_for
from app.services.store import DatasetStore

router = APIRouter(prefix="/api", tags=["upload"])

Store = Annotated[DatasetStore, Depends(get_store)]
Cfg = Annotated[Settings, Depends(get_app_settings)]


async def read_limited(file: UploadFile, limit_bytes: int, limit_mb: int) -> bytes:
    """Read an upload in chunks and stop as soon as the size limit is exceeded."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit_bytes:
            raise AppError(413, "file_too_large", f"The file is larger than the {limit_mb} MB upload limit.")
        chunks.append(chunk)
    if total == 0:
        raise AppError(400, "empty_file", "The uploaded file is empty.")
    return b"".join(chunks)


def parse_mapping(raw: str) -> ColumnMapping:
    try:
        return ColumnMapping.model_validate_json(raw)
    except ValidationError as exc:
        msg = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'mapping'}: {e['msg']}" for e in exc.errors()[:5])
        raise unprocessable("invalid_mapping", f"The column mapping is not valid: {msg}") from exc


@router.post("/profile", response_model=SourceProfile, summary="Inspect a CSV and propose a column mapping")
async def profile(file: Annotated[UploadFile, File(description="CSV file")], cfg: Cfg) -> SourceProfile:
    name = safe_filename(file.filename)
    adapter = adapter_for(name)
    content = await read_limited(file, cfg.max_upload_bytes, cfg.max_upload_mb)
    return await run_in_threadpool(adapter.profile, DataSource(name, content))


@router.post(
    "/upload",
    response_model=UploadResponse,
    summary="Validate (dry run) or import a CSV using a confirmed column mapping",
)
async def upload(
    store: Store,
    cfg: Cfg,
    file: Annotated[UploadFile, File(description="CSV file")],
    mapping: Annotated[str, Form(description="JSON ColumnMapping", max_length=20000)],
    dataset_name: Annotated[str | None, Form(max_length=200)] = None,
    dry_run: Annotated[bool, Form()] = True,
    confirmed: Annotated[bool, Form()] = False,
) -> UploadResponse:
    name = safe_filename(file.filename)
    adapter = adapter_for(name)
    col_map = parse_mapping(mapping)
    content = await read_limited(file, cfg.max_upload_bytes, cfg.max_upload_mb)
    result = await run_in_threadpool(adapter.load, DataSource(name, content), col_map)
    report = result.report

    if dry_run:
        message = (
            "Validation passed. Review the quality report, then confirm to import."
            if report.can_import
            else "The file cannot be imported with this mapping. See the errors below."
        )
        return UploadResponse(imported=False, dry_run=True, quality=report, message=message)

    if not report.can_import or result.data is None:
        raise AppError(
            422,
            "import_blocked",
            "The file cannot be imported with this mapping: " + "; ".join(i.message for i in report.issues if i.severity == "error"),
            details=report.model_dump(mode="json"),
        )
    if report.requires_confirmation and not confirmed:
        raise AppError(
            409,
            "confirmation_required",
            "This import has ambiguities that must be confirmed first: " + " ".join(report.ambiguities),
            details=report.model_dump(mode="json"),
        )
    label = dataset_name or col_map.defaults.dataset_name or PurePath(name).stem
    record = store.add_upload(result.data, label, name, report)
    return UploadResponse(
        imported=True,
        dry_run=False,
        quality=report,
        dataset=store.summarize(record),
        message=f"Imported {len(record.data):,} rows as '{record.name}'. It is kept separate from the synthetic demo data.",
    )
