"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.services.store import DatasetStore


def get_store(request: Request) -> DatasetStore:
    return request.app.state.store


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings
