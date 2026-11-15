"""Wiring for the explorer services (one instance per app)."""

from __future__ import annotations

import httpx

from app.config import Settings
from app.explorer.ai import AIExplanationService
from app.explorer.change import ChangeDetectionService
from app.explorer.datasets import DatasetService
from app.explorer.history import HistoricalAnalysisService
from app.explorer.locations import LocationService
from app.explorer.rendering import RenderingService
from app.explorer.synthetic import ensure_demo_data


class ExplorerServices:
    def __init__(self, settings: Settings, geo=None, ai_transport: httpx.BaseTransport | None = None):
        if settings.explorer_generate_demo:
            ensure_demo_data(settings.explorer_dir)
        self.datasets = DatasetService(settings.explorer_dir)
        self.locations = LocationService(self.datasets, geo)
        self.rendering = RenderingService()
        self.changes = ChangeDetectionService(self.datasets)
        self.history = HistoricalAnalysisService(self.datasets)
        self.ai = AIExplanationService(settings, self.changes, transport=ai_transport)
