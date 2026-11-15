"""AtlasGazetteer: place recognition and boundaries from the GeoJSON files built by scripts/build_geographical_boundaries.py.

Only properties are kept in memory. A geometry is read from its file when a boundary is requested (and cached), so the
roughly 8 MB of state and district polygons never sit in memory together.

``boundary_status`` tells the user what kind of outline they are looking at:
    authoritative_simplified   geoBoundaries administrative polygon (simplified)
    derived_from_official_data outline computed from a downloaded official dataset
    administrative_proxy       a city has no polygon of its own; the containing district is shown
    analysis_window            the rectangle used for the atlas data (not a natural boundary)
    approximate_bbox           a rough rectangle for orientation
    approximate_point          a reference point; the circle drawn around it is an approximate area
"""

from __future__ import annotations

import json
import math
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from pyproj import Geod
from shapely.geometry import shape

from app.explorer.schemas import BoundaryOut, LocationOut
from app.geo.text import fold

LEVEL_RANK = {"country": 0, "state": 1, "city": 2, "lake": 3, "forest": 3, "mountain": 3, "glacier": 3, "river": 3, "island": 3, "coast": 3, "district": 4, "locality": 5, "landmark": 5}
LEVEL_LABEL = {"country": "Country", "state": "State", "district": "District", "city": "City", "locality": "Locality", "landmark": "Landmark", "lake": "Lake", "river": "River / catchment", "forest": "Forest / mangrove", "mountain": "Mountain range", "glacier": "Glacier", "island": "Island", "coast": "Coast"}
FILES = [("countries", "india.geojson"), ("states", "india_states.geojson"), ("districts", "india_districts.geojson"), ("cities", "cities.geojson"), ("localities", "localities.geojson"), ("geographical_features", "features.geojson")]
NOTES = {
    "authoritative_simplified": "Administrative boundary from geoBoundaries (simplified). Not an official survey line.",
    "derived_from_official_data": "Outline computed from a downloaded official dataset.",
    "administrative_proxy": "No city-limit polygon is available; the containing district is shown instead.",
    "analysis_window": "The rectangle used for the atlas data, not a natural boundary.",
    "approximate_bbox": "A rough rectangle for orientation, not an authoritative boundary.",
    "approximate_point": "Only a reference point is available. The circle is an approximate area, not a boundary.",
}


_GEOD = Geod(ellps="WGS84")


def geodesic_area_km2(geometry: dict[str, Any]) -> float | None:
    try:
        g = shape(geometry)
        if g.is_empty or g.geom_type not in ("Polygon", "MultiPolygon"):
            return None
        return round(abs(_GEOD.geometry_area_perimeter(g)[0]) / 1e6, 3)
    except Exception:
        return None


def span_altitude(bbox: list[float] | None, default: float = 14_000.0) -> float:
    if not bbox:
        return default
    span = max(bbox[2] - bbox[0], (bbox[3] - bbox[1]) * 1.2)
    return float(min(6_500_000.0, max(3_500.0, span * 111_000 * 2.1)))


def circle_geometry(lon: float, lat: float, km: float) -> dict[str, Any]:
    pts = [[round(lon + (km / (111.32 * math.cos(math.radians(lat)))) * math.cos(t), 5), round(lat + (km / 110.57) * math.sin(t), 5)] for t in [i * 2 * math.pi / 48 for i in range(49)]]
    return {"type": "Polygon", "coordinates": [pts]}


class AtlasGazetteer:
    def __init__(self, atlas_dir: Path):
        self.dir = Path(atlas_dir) / "geographical_boundaries"
        self._lock = threading.RLock()
        self._entries: list[dict[str, Any]] | None = None
        self._by_id: dict[str, dict[str, Any]] = {}
        self._geom_cache: OrderedDict[str, dict[str, Any] | None] = OrderedDict()

    # ------------------------------------------------------------------------------------ load
    @property
    def available(self) -> bool:
        return (self.dir / "states" / "india_states.geojson").exists()

    def _load(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._entries is not None:
                return self._entries
            out: list[dict[str, Any]] = []
            for folder, name in FILES:
                path = self.dir / folder / name
                if not path.exists():
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                for f in data["features"]:
                    p = dict(f["properties"])
                    p["_file"] = f"{folder}/{name}"
                    p["_geom_type"] = (f.get("geometry") or {}).get("type")
                    p["_names"] = [fold(p["name"])] + [fold(a) for a in p.get("aliases", [])]
                    p["_ctx"] = {fold(h) for h in p.get("hierarchy", [])}
                    out.append(p)
                    if p["_geom_type"] == "Point":
                        self._geom_cache[p["id"]] = f["geometry"]
                del data
            self._entries = out
            self._by_id = {e["id"]: e for e in out}
            return out

    # ---------------------------------------------------------------------------------- search
    def search(self, query: str, limit: int = 8, suggest: bool = False) -> list[dict[str, Any]]:
        entries = self._load()
        parts = [fold(x) for x in query.split(",") if x.strip()]
        if not parts:
            return []
        q, ctx = parts[0], set(parts[1:]) | {t for part in parts[1:] for t in part.split()}
        scored: list[tuple[float, int, str, dict[str, Any]]] = []
        for e in entries:
            best = 0.0
            for n in e["_names"]:
                if n == q:
                    s = 100.0 if n == e["_names"][0] else 95.0
                elif suggest and n.startswith(q) and len(q) >= 2:
                    s = 70.0 - min(20.0, (len(n) - len(q)) * 0.6)
                elif (" " + q + " ") in (" " + n + " ") and len(q) >= 3:
                    s = 55.0
                elif len(q) >= 3 and set(q.split()) <= set(n.split()) and not suggest:
                    s = 45.0
                elif suggest and len(q) >= 3 and q in n:
                    s = 40.0
                else:
                    continue
                best = max(best, s)
            if best <= 0:
                continue
            if ctx:
                hits = len(ctx & e["_ctx"]) + (1 if any(c in n for c in ctx for n in e["_names"][1:]) else 0)
                best += 8.0 * hits
            if e["level"] in ("country", "state", "city"):
                best += 4.0  # prefer the main place over a same-named minor one
            scored.append((best, LEVEL_RANK.get(e["level"], 6), e["name"], e))
        scored.sort(key=lambda t: (-t[0], t[1], t[2]))
        return [e for *_, e in scored[:limit]]

    def get(self, location_id: str) -> dict[str, Any] | None:
        self._load()
        return self._by_id.get(location_id)

    # ------------------------------------------------------------------------------- location
    @staticmethod
    def to_location(e: dict[str, Any]) -> LocationOut:
        bb = e.get("bbox")
        hier = list(e.get("hierarchy", []))
        label = LEVEL_LABEL.get(e["level"], e["level"].title())
        display = ", ".join([e["name"]] + list(reversed(hier)))
        return LocationOut(
            id=e["id"], name=e["name"], display_name=display, lat=float(e["lat"]), lon=float(e["lon"]), kind=label.lower(), level=e["level"], hierarchy=hier, source=e.get("source", "atlas gazetteer"),
            bbox=[float(v) for v in bb] if bb else None, zoom_altitude_m=span_altitude([float(v) for v in bb] if bb else None), boundary_status=e.get("boundary_status"),
        )

    # ------------------------------------------------------------------------------ boundary
    def _geometry(self, e: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            if e["id"] in self._geom_cache:
                self._geom_cache.move_to_end(e["id"])
                return self._geom_cache[e["id"]]
        data = json.loads((self.dir / e["_file"].split("/")[0] / e["_file"].split("/")[1]).read_text(encoding="utf-8"))
        geom = next((f["geometry"] for f in data["features"] if f["properties"]["id"] == e["id"]), None)
        with self._lock:
            self._geom_cache[e["id"]] = geom
            while len(self._geom_cache) > 24:
                k, v = next(iter(self._geom_cache.items()))
                if v is not None and v.get("type") == "Point":
                    self._geom_cache.move_to_end(k)
                    if all((x or {}).get("type") == "Point" for x in self._geom_cache.values()):
                        break
                    continue
                self._geom_cache.popitem(last=False)
        return geom

    def boundary(self, e: dict[str, Any]) -> BoundaryOut:
        status = e.get("boundary_status", "approximate_point")
        geom = self._geometry(e)
        note = e.get("boundary_note") or NOTES.get(status, "")
        src = e.get("source", "")
        if status == "administrative_proxy" and e.get("boundary_ref"):
            ref = self._by_id.get(e["boundary_ref"])
            geom = self._geometry(ref) if ref else None
            if geom is None:
                status, note = "approximate_point", NOTES["approximate_point"]
        if geom is None or geom.get("type") == "Point":
            geom = circle_geometry(float(e["lon"]), float(e["lat"]), float(e.get("approx_radius_km", 2.0)))
            if status not in ("approximate_point",):
                status = "approximate_point"
            note = e.get("boundary_note") or NOTES["approximate_point"]
        return BoundaryOut(
            location_id=e["id"], name=e["name"], level=e["level"], status=status, authoritative=status in ("authoritative_simplified", "derived_from_official_data"), note=note, source=src, license=e.get("license", ""),
            bbox=[float(v) for v in e["bbox"]] if e.get("bbox") else None, geometry=geom, source_id=e.get("source_id"), area_km2=geodesic_area_km2(geom), area_is_approximate=status not in ("authoritative_simplified", "derived_from_official_data"),
        )
