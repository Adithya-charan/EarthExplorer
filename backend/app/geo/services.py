"""Wiring for the Earth Explorer services (one container per application)."""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.errors import AppError
from app.geo.naturalearth import Gazetteer
from app.geo.nominatim import NominatimClient
from app.geo.resolver import Resolver
from app.geo.terrain import TerrainService
from app.geo.viz import VizService

log = logging.getLogger("earthtrend.geo")


@lru_cache(maxsize=4)
def _shared_gazetteer(data_dir: str) -> Gazetteer:
    """The Natural Earth index is read-only and takes seconds to build, so apps pointing at the same
    folder share one instance (this also keeps repeated ``create_app`` calls in tests cheap)."""
    return Gazetteer(Path(data_dir))


class GeoServices:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.gazetteer = _shared_gazetteer(str(Path(settings.geo_data_dir).resolve()))
        self.nominatim = NominatimClient(settings, transport=transport)
        self.terrain = TerrainService(settings, transport=transport)
        self.resolver = Resolver(self.gazetteer, self.nominatim, settings)
        self.viz = VizService(self.resolver)
        self._warm_thread: threading.Thread | None = None

    # ------------------------------------------------------------------------------ lifecycle
    def start_warmup(self) -> None:
        """Build the Natural Earth index in the background so the first search is not slow."""
        if not self.settings.geo_warm_on_start or not self.gazetteer.available or self._warm_thread is not None:
            return

        def _run() -> None:
            try:
                self.gazetteer.warm()
            except AppError as exc:  # data missing or unreadable: reported by /api/health, not fatal
                log.warning("Natural Earth warm-up failed: %s", exc.message)
            except Exception:  # noqa: BLE001 - never crash the server because of a warm-up
                log.exception("Natural Earth warm-up failed")

        self._warm_thread = threading.Thread(target=_run, name="geo-warmup", daemon=True)
        self._warm_thread.start()

    def close(self) -> None:
        self.nominatim.close()
        self.terrain.close()

    # --------------------------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        return {
            "reference_atlas": self.gazetteer.status(),
            "geocoder": {
                "provider": "OpenStreetMap Nominatim",
                "enabled": self.nominatim.enabled,
                "min_interval_s": self.nominatim.min_interval,
            },
            "terrain": {"provider": "Terrain Tiles on AWS (Terrarium encoding)", "sample_zoom": self.terrain.default_zoom},
        }
