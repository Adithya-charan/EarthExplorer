"""HistoricalAnalysisService: dataset timelines (only dates that exist) and observation summaries."""

from __future__ import annotations

from app.explorer.datasets import Dataset, DatasetService
from app.explorer.schemas import LatestObservation, ObservationInfo


class HistoricalAnalysisService:
    def __init__(self, datasets: DatasetService):
        self.datasets = datasets

    def timeline(self, ds: Dataset, with_share: bool = True, min_valid: float = 0.5) -> list[ObservationInfo]:
        shares = self.datasets.water_shares(ds) if with_share else {}
        return [
            ObservationInfo(date=o.iso, quality=o.quality, valid_fraction=round(o.valid_fraction, 3), usable=ds.usable(o, min_valid), water_share=None if shares.get(o.iso) is None else round(shares[o.iso], 4), sensor=o.sensor)  # type: ignore[arg-type]
            for o in ds.observations
        ]

    def latest(self, ds: Dataset, location: str, min_valid: float = 0.5) -> LatestObservation:
        usable = [o for o in ds.observations if ds.usable(o, min_valid)]
        o = usable[-1] if usable else ds.observations[-1]
        m = ds.meta
        note = "The most recent observation in this dataset. Satellite products are processed after acquisition, so this is not live or real-time." + (" It is simulated." if ds.is_synthetic else "")
        if not usable:
            note += " No observation meets the quality minimum; the newest is shown with its quality."
        return LatestObservation(
            date=o.iso, location=location, source=m.get("source", "unknown"), spatial_resolution_m=float(m.get("resolution_m", 0.0)), quality=o.quality,  # type: ignore[arg-type]
            valid_fraction=round(o.valid_fraction, 3), temporal_resolution=ds.temporal, historical_coverage=dict(m["coverage"]),
            is_synthetic=ds.is_synthetic, simulated_label=m.get("simulated_label"), note=note,
        )
