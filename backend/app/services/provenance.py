"""Provenance blocks attached to every data-bearing response."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from app.schemas import Provenance
from app.services.store import DEMO_NOTICE, UPLOAD_NOTICE, DatasetRecord

ROW_SYNTHETIC_NOTICE = "This selection contains rows flagged is_synthetic = true (synthetic data, not real observations)."


def build_provenance(record: DatasetRecord, subset: pd.DataFrame | None = None) -> Provenance:
    df = record.data if subset is None else subset
    n = len(df)
    frac = float(df["is_synthetic"].mean()) if n else 0.0
    is_synth = bool(df["is_synthetic"].any()) if n else False
    if record.status == "synthetic_demo":
        notice = DEMO_NOTICE
    elif record.status in ("synthetic_regional_demo", "observed_global"):
        notice = record.notice
    elif is_synth:
        notice = ROW_SYNTHETIC_NOTICE
    elif record.status == "uploaded":
        notice = UPLOAD_NOTICE
    else:
        notice = None
    return Provenance(
        dataset_id=record.id,
        dataset_name=record.name,
        status=record.status,
        is_synthetic=is_synth,
        synthetic_row_fraction=frac,
        data_sources=sorted(df["data_source"].dropna().unique().tolist()) if n else [],
        source_file=record.source_file,
        notice=notice,
        dataset_checksum=record.checksum,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
