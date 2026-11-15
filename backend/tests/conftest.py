from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Starlette's test client nudges towards httpx2; the installed httpx works and the notice is not a test failure.
warnings.filterwarnings("ignore", message=".*httpx.*starlette.testclient.*")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        upload_dir=tmp_path / "uploads",
        max_upload_mb=1,
        max_rows=50_000,
        max_datasets=3,
        demo_csv_path=BACKEND / "data" / "earth_science_trend_demo.csv",
        datasets_dir=tmp_path / "no-package",  # packaged CSVs are opt-in per test (see package_client)
        explorer_dir=tmp_path / "explorer",  # explorer datasets are opt-in per test (see tests/test_explorer.py)
        explorer_generate_demo=False,
        groq_api_key=None,
    )


@pytest.fixture()
def client(settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture()
def app_store(client):
    return client.app.state.store


DEMO = "synthetic-demo"


REPO_DATASETS = BACKEND.parent / "datasets"


@pytest.fixture()
def package_client(tmp_path) -> TestClient:
    s = Settings(
        upload_dir=tmp_path / "uploads",
        max_upload_mb=1,
        max_rows=50_000,
        max_datasets=3,
        demo_csv_path=BACKEND / "data" / "earth_science_trend_demo.csv",
        datasets_dir=REPO_DATASETS,
        geo_warm_on_start=False,
    )
    return TestClient(create_app(s))
