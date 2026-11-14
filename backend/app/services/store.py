"""In-process dataset registry.

Holds the read-only synthetic demo dataset and any user-imported datasets. Uploaded
datasets are persisted as normalized canonical CSV plus a small JSON metadata file
under ``upload_dir`` using server-generated IDs (user-supplied names never become
paths) and reloaded on startup. The demo dataset is never written to.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import Settings
from app.errors import AppError
from app.schemas import DatasetInfo, DatasetStatus, DatasetSummary, PackageCheck, QualityReport
from app.services.ingestion.base import DataSource
from app.services.ingestion.csv_adapter import CSVAdapter, identity_mapping
from app.services.ingestion.package_loader import DEMO_NOTICE_REGIONAL, OBSERVED_NOTICE, load_package
from app.services.ingestion.schema import OPTIONAL_FIELDS, REQUIRED_FIELDS, TRACE_FIELDS

log = logging.getLogger("earthtrend.store")

DEMO_ID = "synthetic-demo"
DEMO_NAME = "Synthetic demo data"
DEMO_NOTICE = (
    "Synthetic demo data: artificial values generated for software demonstration. "
    "This is not NASA data, not satellite data and not an observation of the real Earth system."
)
UPLOAD_NOTICE = (
    "Uploaded dataset: provenance is declared by the uploader and has not been verified by EarthTrend Explorer."
)
NASA_PENDING = (
    "The NASA Earth science dataset has not been supplied yet, so no NASA data is integrated. "
    "Everything shown is either the clearly labelled synthetic demo data or a file you uploaded."
)
NASA_INTEGRATED = "A dataset with verified NASA status is loaded."
NASA_GLOBAL_ONLY = (
    "Observed NASA GPM IMERG V07 global area-averaged series (Giovanni CSV export) are loaded, but they are global only. "
    "No regional NASA observations have been supplied, so real regional analysis is disabled; the India, Amazon and "
    "Central Africa series are synthetic demo data."
)

CANONICAL_COLUMNS = list(REQUIRED_FIELDS) + list(OPTIONAL_FIELDS) + list(TRACE_FIELDS)


@dataclass
class DatasetRecord:
    id: str
    name: str
    status: DatasetStatus
    data: pd.DataFrame
    quality: QualityReport | None
    source_file: str | None = None
    created_at: str | None = None
    read_only: bool = False
    extra: dict = field(default_factory=dict)
    info: DatasetInfo | None = None

    @property
    def checksum(self) -> str:
        """SHA-256 over the canonical rows, cached; changes if any date, region, variable, value or unit changes."""
        cached = self.extra.get("_checksum")
        if cached is None:
            h = hashlib.sha256()
            cols = self.data[["date", "region", "variable", "value", "unit"]]
            h.update(pd.util.hash_pandas_object(cols, index=False).to_numpy().tobytes())
            cached = h.hexdigest()
            self.extra["_checksum"] = cached
        return cached

    @property
    def is_synthetic(self) -> bool:
        return bool(self.data["is_synthetic"].any()) if len(self.data) else False

    @property
    def notice(self) -> str | None:
        if self.status == "synthetic_demo":
            return DEMO_NOTICE
        if self.status == "synthetic_regional_demo":
            return DEMO_NOTICE_REGIONAL
        if self.status == "observed_global":
            return OBSERVED_NOTICE
        if self.status == "uploaded":
            return UPLOAD_NOTICE
        return None


def classify_status(is_demo: bool, verified_nasa: bool = False) -> DatasetStatus:
    """Dataset status. ``nasa_verified`` can never be reached through the upload path:
    it requires a maintainer to register a dataset with ``verified_nasa=True`` after the
    real file has been profiled (see docs/NASA_DATA_INTEGRATION.md)."""
    if is_demo:
        return "synthetic_demo"
    return "nasa_verified" if verified_nasa else "uploaded"


def _read_npz(path):
    from app.services.grid import GridData

    z = np.load(path, allow_pickle=False)
    meta = json.loads(str(z["meta"]))
    return GridData(
        variable=meta["variable"], unit=meta["unit"], long_name=meta["long_name"], lat=z["lat"], lon=z["lon"],
        times=pd.DatetimeIndex(z["times"].astype("datetime64[ns]")), values=z["values"], source_name=meta["source_name"],
    )


class DatasetStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._records: dict[str, DatasetRecord] = {}
        self._lock = threading.RLock()
        self.package_issues: list[PackageCheck] = []

    # ------------------------------------------------------------------ loading
    def load_all(self) -> None:
        self._load_demo()
        self._load_package()
        self._load_uploads()

    def _load_package(self) -> None:
        """Packaged CSVs become separate read-only records; failures are reported, never papered over."""
        result = load_package(self.settings.datasets_dir)
        self.package_issues = result.issues
        for issue in result.issues:
            log.warning("dataset package: [%s] %s", issue.code, issue.message)
        for ds in result.datasets:
            df = self._finalize(ds.data, ds.id, ds.name)
            with self._lock:
                self._records[ds.id] = DatasetRecord(
                    id=ds.id, name=ds.name, status=ds.status, data=df, quality=None, source_file=ds.source_file, read_only=True, info=ds.info
                )

    def _load_demo(self) -> None:
        path = self.settings.demo_csv_path
        if not path.is_file():
            log.warning("Synthetic demo CSV not found at %s; starting without a demo dataset.", path)
            return
        adapter = CSVAdapter()
        result = adapter.load(DataSource(path.name, path.read_bytes()), identity_mapping())
        if result.data is None:
            log.error("Bundled demo CSV failed validation: %s", [i.message for i in result.report.issues])
            return
        df = self._finalize(result.data, DEMO_ID, DEMO_NAME)
        # The bundled file must declare itself synthetic; refuse to serve it otherwise.
        if not bool(df["is_synthetic"].all()):
            log.error("Bundled demo CSV contains rows not flagged is_synthetic; refusing to load it.")
            return
        with self._lock:
            self._records[DEMO_ID] = DatasetRecord(
                id=DEMO_ID,
                name=DEMO_NAME,
                status="synthetic_demo",
                data=df,
                quality=result.report,
                source_file=path.name,
                read_only=True,
            )

    def _load_uploads(self) -> None:
        d = self.settings.upload_dir
        if not d.is_dir():
            return
        for meta_path in sorted(d.glob("*.json")):
            csv_path = meta_path.with_suffix(".csv")
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                df = pd.read_csv(csv_path, parse_dates=["date"])
                df["is_synthetic"] = df["is_synthetic"].astype(bool)
                ds_id = meta["id"]
                if not ds_id.startswith("upload-"):
                    continue
                extra = {}
                npz = meta_path.with_suffix(".npz")
                if npz.is_file():
                    extra["grid"] = _read_npz(npz)
                with self._lock:
                    self._records[ds_id] = DatasetRecord(
                        extra=extra,
                        id=ds_id,
                        name=meta["name"],
                        status="uploaded",
                        data=df,
                        quality=QualityReport(**meta["quality"]) if meta.get("quality") else None,
                        source_file=meta.get("source_file"),
                        created_at=meta.get("created_at"),
                    )
            except Exception as exc:  # noqa: BLE001 - a corrupt upload must not stop the API
                log.warning("Skipping unreadable upload %s: %s", meta_path.name, type(exc).__name__)

    # --------------------------------------------------------------- normalizing
    @staticmethod
    def _finalize(df: pd.DataFrame, dataset_id: str, dataset_name: str) -> pd.DataFrame:
        df = df.copy()
        df["dataset_id"] = dataset_id
        df["dataset_name"] = dataset_name
        for col in CANONICAL_COLUMNS:
            if col not in df.columns:
                df[col] = None
        present_optional = [c for c in OPTIONAL_FIELDS if df[c].notna().any()]
        cols = list(REQUIRED_FIELDS) + present_optional + list(TRACE_FIELDS)
        return df[cols].reset_index(drop=True)

    # ------------------------------------------------------------------ access
    def get(self, dataset_id: str) -> DatasetRecord:
        with self._lock:
            rec = self._records.get(dataset_id)
        if rec is None:
            raise AppError(404, "dataset_not_found", f"Dataset '{dataset_id}' does not exist.")
        return rec

    def list(self) -> list[DatasetRecord]:
        with self._lock:
            # demo first, then uploads in creation order
            return sorted(self._records.values(), key=lambda r: (not r.read_only, r.created_at or ""))

    def default_id(self) -> str | None:
        recs = self.list()
        for r in recs:  # observed data is the default; synthetic data is never preferred over it
            if r.status == "observed_global":
                return r.id
        return recs[0].id if recs else None

    def has_observed_global(self) -> bool:
        return any(r.status == "observed_global" for r in self.list())

    def nasa_integrated(self) -> bool:
        return any(r.status == "nasa_verified" for r in self.list())

    # ------------------------------------------------------------------ import
    def add_upload(
        self, data: pd.DataFrame, name: str, source_file: str, quality: QualityReport, grid=None
    ) -> DatasetRecord:
        with self._lock:
            n_uploads = sum(1 for r in self._records.values() if r.status == "uploaded")
            if n_uploads >= self.settings.max_datasets:
                raise AppError(
                    409,
                    "too_many_datasets",
                    f"At most {self.settings.max_datasets} uploaded datasets can be stored. Delete one first.",
                )
            ds_id = f"upload-{uuid.uuid4().hex[:12]}"
            clean_name = name.strip()[:200] or source_file
            df = self._finalize(data, ds_id, clean_name)
            created = datetime.now(timezone.utc).isoformat(timespec="seconds")
            rec = DatasetRecord(
                id=ds_id,
                name=clean_name,
                status="uploaded",
                data=df,
                quality=quality,
                source_file=source_file,
                created_at=created,
                extra={"grid": grid} if grid is not None else {},
            )
            self._persist(rec)
            self._records[ds_id] = rec
            return rec

    def delete_upload(self, dataset_id: str) -> None:
        with self._lock:
            rec = self.get(dataset_id)
            if rec.read_only or rec.status != "uploaded":
                raise AppError(403, "dataset_read_only", "The bundled demo dataset cannot be deleted.")
            del self._records[dataset_id]
            for suffix in (".csv", ".json", ".npz"):
                try:
                    (self.settings.upload_dir / f"{dataset_id}{suffix}").unlink(missing_ok=True)
                except OSError:
                    log.warning("Could not remove stored file for %s", dataset_id)

    def _persist(self, rec: DatasetRecord) -> None:
        d = self.settings.upload_dir
        try:
            d.mkdir(parents=True, exist_ok=True)
            rec.data.to_csv(d / f"{rec.id}.csv", index=False)
            meta = {
                "id": rec.id,
                "name": rec.name,
                "source_file": rec.source_file,
                "created_at": rec.created_at,
                "quality": json.loads(rec.quality.model_dump_json()) if rec.quality else None,
            }
            (d / f"{rec.id}.json").write_text(json.dumps(meta), encoding="utf-8")
            grid = rec.extra.get("grid")
            if grid is not None:
                np.savez_compressed(
                    d / f"{rec.id}.npz",
                    lat=grid.lat, lon=grid.lon, times=grid.times.values.astype("datetime64[ns]").astype("int64"), values=grid.values,
                    meta=json.dumps({"variable": grid.variable, "unit": grid.unit, "long_name": grid.long_name, "source_name": grid.source_name}),
                )
        except OSError as exc:
            log.warning("Could not persist upload %s (kept in memory only): %s", rec.id, type(exc).__name__)

    # ------------------------------------------------------------------ summary
    def summarize(self, rec: DatasetRecord) -> DatasetSummary:
        df = rec.data
        valid = df["value"].notna()
        return DatasetSummary(
            id=rec.id,
            name=rec.name,
            status=rec.status,
            is_synthetic=rec.is_synthetic,
            n_rows=len(df),
            n_valid=int(valid.sum()),
            n_missing=int((~valid).sum()),
            date_start=df["date"].min().date() if len(df) else None,
            date_end=df["date"].max().date() if len(df) else None,
            n_variables=int(df["variable"].nunique()),
            n_regions=int(df["region"].nunique()),
            n_series=int(df.groupby(["variable", "region"]).ngroups) if len(df) else 0,
            data_sources=sorted(df["data_source"].dropna().unique().tolist()),
            source_file=rec.source_file,
            created_at=rec.created_at,
            notice=rec.notice,
            info=rec.info,
        )
