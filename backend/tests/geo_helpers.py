"""Shared fixtures for the Earth Explorer tests: a fake network so no test touches the internet."""

from __future__ import annotations

import io
from typing import Any

import httpx
import numpy as np
from PIL import Image

NOMINATIM_HOST = "nominatim.test"
TILE_HOST = "tiles.test"

EIFFEL = {
    "place_id": 1,
    "osm_type": "way",
    "osm_id": 5013364,
    "lat": "48.8582599",
    "lon": "2.2945006",
    "category": "man_made",
    "type": "tower",
    "importance": 0.8,
    "name": "Eiffel Tower",
    "display_name": "Eiffel Tower, Paris, France",
    "addresstype": "man_made",
    "address": {"man_made": "Eiffel Tower", "city": "Paris", "state": "Île-de-France", "country": "France", "country_code": "fr"},
    "boundingbox": ["48.8574753", "48.8590453", "2.2933118", "2.2956897"],
}


def terrarium_png(elevation_at: Any) -> bytes:
    """A 256×256 Terrarium tile whose elevation at pixel (x, y) is ``elevation_at(x, y)`` metres."""
    ys, xs = np.mgrid[0:256, 0:256]
    v = np.asarray(elevation_at(xs, ys), dtype=np.float64) + 32768.0
    r = np.floor(v / 256.0)
    g = np.floor(v) % 256
    b = np.floor((v - np.floor(v)) * 256.0)
    img = Image.fromarray(np.stack([r, g, b], axis=-1).astype(np.uint8), "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class FakeNet:
    """An ``httpx`` transport handler that records requests and serves canned geocoder / tile responses."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.search_results: dict[str, list[dict[str, Any]]] = {}
        self.lookup_results: dict[str, list[dict[str, Any]]] = {}
        self.geocoder_status: int | None = None  # force an HTTP status from the geocoder
        self.geocoder_timeout = False
        self.tile_png: bytes | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        host = request.url.host
        if host == NOMINATIM_HOST:
            if self.geocoder_timeout:
                raise httpx.ReadTimeout("slow", request=request)
            if self.geocoder_status:
                return httpx.Response(self.geocoder_status, json={"error": "forced"})
            params = request.url.params
            if request.url.path == "/search":
                return httpx.Response(200, json=self.search_results.get(params.get("q", ""), []))
            if request.url.path == "/lookup":
                return httpx.Response(200, json=self.lookup_results.get(params.get("osm_ids", ""), []))
        if host == TILE_HOST:
            if self.tile_png is None:
                return httpx.Response(404)
            return httpx.Response(200, content=self.tile_png, headers={"content-type": "image/png"})
        return httpx.Response(500, json={"error": "unexpected host"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def geocoder_calls(self) -> list[httpx.Request]:
        return [c for c in self.calls if c.url.host == NOMINATIM_HOST]
