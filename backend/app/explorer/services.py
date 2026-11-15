"""Wiring for the explorer services (one instance per app)."""

from __future__ import annotations

import json

import httpx

from app.config import Settings
from app.explorer.ai import AIExplanationService
from app.explorer.change import ChangeDetectionService
from app.explorer.datasets import DatasetService
from app.explorer.gazetteer import AtlasGazetteer
from app.explorer.history import HistoricalAnalysisService
from app.explorer.locations import LocationService
from app.explorer.rendering import RenderingService
from app.explorer.stats import dataset_statistics
from app.explorer.synthetic import ensure_demo_data


class ExplorerServices:
    def registry(self) -> dict:
        """Source registry entries by id (empty when the atlas documentation is absent)."""
        path = self.atlas_dir / "documentation" / "source_registry.json"
        try:
            return {e["id"]: e for e in json.loads(path.read_text(encoding="utf-8")).get("entries", [])}
        except (OSError, ValueError):
            return {}

    def statistics(self, ds) -> dict:
        key = (ds.id, len(ds.observations))
        if key not in self._stats:
            self._stats[key] = dataset_statistics(self.datasets, ds)
        return self._stats[key]

    def __init__(self, settings: Settings, geo=None, ai_transport: httpx.BaseTransport | None = None):
        self.atlas_dir = settings.atlas_dir
        self._stats: dict = {}
        if settings.explorer_generate_demo:
            ensure_demo_data(settings.explorer_dir)
        self.datasets = DatasetService(settings.explorer_dir)
        self.gazetteer = AtlasGazetteer(settings.atlas_dir)
        self.locations = LocationService(self.datasets, geo, self.gazetteer)
        self.rendering = RenderingService()
        self.changes = ChangeDetectionService(self.datasets)
        self.history = HistoricalAnalysisService(self.datasets)
        self.ai = AIExplanationService(settings, self.changes, transport=ai_transport)
