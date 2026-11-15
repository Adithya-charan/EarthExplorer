"""Application settings (environment-driven, no secrets required)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

APP_NAME = "EarthTrend Explorer API"
APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    """Runtime configuration. Every value can be overridden with an
    ``EARTHTREND_``-prefixed environment variable or a ``.env`` file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="EARTHTREND_", extra="ignore")

    # Comma-separated list of allowed browser origins for CORS.
    cors_origins: str = "http://localhost:5174,http://127.0.0.1:5174,http://localhost:3000,http://127.0.0.1:3000"

    # Upload limits.
    max_upload_mb: int = 25
    max_rows: int = 2_000_000
    max_datasets: int = 25

    # Locations. The bundled synthetic demo file is read-only; uploads are
    # written (as normalized canonical CSV + JSON metadata) to ``upload_dir``.
    demo_csv_path: Path = BACKEND_DIR / "data" / "earth_science_trend_demo.csv"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    # Packaged CSVs: observed_global/ (NASA Giovanni) and synthetic_regional_demo/ (labelled synthetic). Read-only.
    datasets_dir: Path = REPO_DIR / "datasets"

    # --- Earth Explorer (geography) -----------------------------------------------------------
    # Natural Earth files fetched by ``scripts/fetch_natural_earth.py``.
    geo_data_dir: Path = BACKEND_DIR / "data" / "naturalearth"
    # Load the Natural Earth index in a background thread at start-up (disable in tests).
    geo_warm_on_start: bool = True
    # Live geocoding. Nominatim's usage policy asks for an identifying User-Agent, at most one request
    # per second and cached results. Set your own contact in the user agent if you run this for others.
    geocoder_enabled: bool = True
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    geocoder_user_agent: str = "geo-explorer-dev/0.1 (local development)"
    geocoder_min_interval_s: float = 1.1
    geocoder_timeout_s: float = 10.0
    geocoder_cache_ttl_s: int = 24 * 3600
    geocoder_max_results: int = 8
    # Elevation sampling uses the same Terrarium tiles the map displays.
    terrain_tile_url: str = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
    terrain_sample_zoom: int = 10

    # --- Earth Time Machine (explorer) ---------------------------------------------------------
    # One folder per dataset: dataset.json plus observations/*.tif. Synthetic demo datasets are generated into it.
    explorer_dir: Path = BACKEND_DIR / "data" / "explorer"
    explorer_generate_demo: bool = True  # create the synthetic demo datasets on first start when missing
    # Groq (optional). Without a key the explanation is produced deterministically from the measurements.
    groq_api_key: str | None = Field(default=None, validation_alias=AliasChoices("GROQ_API_KEY", "EARTHTREND_GROQ_API_KEY"))
    groq_model: str = Field(default="llama-3.3-70b-versatile", validation_alias=AliasChoices("GROQ_MODEL", "EARTHTREND_GROQ_MODEL"))
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_s: float = 20.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
