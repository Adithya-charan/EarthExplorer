"""LocationService: place name -> coordinates. A small offline demo gazetteer first, then the app's geocoder (tolerating failure)."""

from __future__ import annotations

import logging
import re
import unicodedata

from app.explorer.datasets import DatasetService
from app.explorer.gazetteer import AtlasGazetteer, geodesic_area_km2, span_altitude
from app.explorer.schemas import BoundaryOut, LocationOut

log = logging.getLogger("earthtrend.explorer")

# (id, display name, lat, lon, kind, camera altitude m, bbox west/south/east/north or None, aliases)
DEMO_PLACES: list[tuple[str, str, float, float, str, float, list[float] | None, list[str]]] = [
    ("demo:amazon-rainforest", "Amazon Rainforest", -3.4653, -62.2159, "region", 2_600_000.0, [-73.0, -16.0, -48.0, 5.0], ["amazon rainforest", "amazon", "amazonia", "amazon basin"]),
    ("demo:mumbai", "Mumbai, Maharashtra, India", 19.0760, 72.8777, "city", 60_000.0, [72.77, 18.89, 72.99, 19.27], ["mumbai", "bombay", "mumbai india"]),
    ("demo:bengaluru", "Bengaluru, Karnataka, India", 12.9716, 77.5946, "city", 55_000.0, [77.45, 12.83, 77.75, 13.14], ["bengaluru", "bangalore", "bengaluru india"]),
    ("demo:hyderabad", "Hyderabad, Telangana, India", 17.3850, 78.4867, "city", 60_000.0, [78.25, 17.2, 78.65, 17.6], ["hyderabad", "hyderabad india"]),
    ("demo:odisha", "Odisha, India", 20.9517, 85.0985, "region", 900_000.0, None, ["odisha", "orissa"]),
]


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


class LocationService:
    def __init__(self, datasets: DatasetService, geo=None, gazetteer: AtlasGazetteer | None = None):
        self.datasets = datasets
        self.geo = geo
        self.gazetteer = gazetteer if gazetteer is not None and gazetteer.available else None

    def examples(self) -> list[str]:
        if self.gazetteer:
            return ["Bellandur Lake, Bengaluru", "Hyderabad", "Sundarbans", "Himalayas", "Uttarakhand"]
        return ["Bellandur Lake, Bengaluru", "Hussain Sagar, Hyderabad", "Chilika Lake, Odisha", "Amazon Rainforest", "Mumbai"]

    def _demo(self) -> list[tuple[LocationOut, list[str]]]:
        out: list[tuple[LocationOut, list[str]]] = []
        for ds in self.datasets.list():
            loc = ds.meta.get("location") or {}
            if "lat" not in loc or "lon" not in loc:
                continue
            name = loc.get("name") or ds.meta["name"]
            hint = loc.get("hint")
            out.append((
                LocationOut(id=f"dataset:{ds.id}", name=name, display_name=f"{name}, {hint}" if hint else name, lat=float(loc["lat"]), lon=float(loc["lon"]), kind="water body", source="dataset footprint", bbox=ds.bbox, zoom_altitude_m=14_000.0),
                [fold(a) for a in loc.get("aliases", [])] + [fold(name)],
            ))
        for pid, name, lat, lon, kind, alt, bb, aliases in DEMO_PLACES:
            out.append((LocationOut(id=pid, name=name.split(",")[0], display_name=name, lat=lat, lon=lon, kind=kind, source="built-in gazetteer", bbox=bb, zoom_altitude_m=alt), [fold(a) for a in aliases]))
        return out

    @staticmethod
    def _from_candidate(c) -> LocationOut:
        bb = None
        if c.bbox is not None and not c.bbox.crosses_antimeridian:
            bb = [c.bbox.west, c.bbox.south, c.bbox.east, c.bbox.north]
        ctx = c.context
        hier = [x for x in (ctx.country, ctx.admin1, ctx.admin2) if x]
        level = c.class_label.lower()
        return LocationOut(id=c.id, name=c.name, display_name=c.display_name, lat=c.latitude, lon=c.longitude, kind=level, level=level, hierarchy=hier, source=c.provider_name, bbox=bb, zoom_altitude_m=span_altitude(bb, 12_000.0))

    def suggest(self, query: str, limit: int = 8) -> list[LocationOut]:
        """Fast, offline suggestions while typing: the atlas gazetteer first, then the Natural Earth reference atlas."""
        if len(fold(query)) < 2:
            return []
        out: list[LocationOut] = []
        seen: set[tuple[str, str]] = set()
        if self.gazetteer:
            for e in self.gazetteer.search(query, limit=limit, suggest=True):
                loc = AtlasGazetteer.to_location(e)
                out.append(loc)
                seen.add((fold(loc.name), loc.level))
        if len(out) < limit and self.geo is not None:
            try:
                cands, _, _ = self.geo.resolver.candidates(query, online=False, limit=limit, suggest=True)
            except Exception as exc:
                log.info("Reference atlas unavailable for suggestions: %s", exc)
                cands = []
            for c in cands:
                loc = self._from_candidate(c)
                # The same place from two sources (same name within ~30 km) is listed once, preferring the atlas entry.
                dup = any(fold(o.name) == fold(loc.name) and abs(o.lat - loc.lat) < 0.3 and abs(o.lon - loc.lon) < 0.3 for o in out)
                if (fold(loc.name), loc.level) not in seen and not dup and len(out) < limit:
                    out.append(loc)
                    seen.add((fold(loc.name), loc.level))
        return out

    def search(self, query: str, *, online: bool = True, limit: int = 6) -> list[LocationOut]:
        q = fold(query)
        if not q:
            return []
        if self.gazetteer:
            hits = self.gazetteer.search(query, limit=limit)
            if hits:
                return [AtlasGazetteer.to_location(e) for e in hits]
        exact, partial = [], []
        for loc, names in self._demo():
            if q in names:
                exact.append(loc)
            elif any(q in n or n in q for n in names if len(n) >= 4) or q.split(" ")[0] in {n.split(" ")[0] for n in names if len(q.split(" ")[0]) >= 4}:
                partial.append(loc)
        found = exact or partial
        if found:
            return found[:limit]
        if self.geo is None:
            return []
        try:
            cands, _, _ = self.geo.resolver.candidates(query, online=online, limit=limit)
        except Exception as exc:  # network down, geocoder disabled, atlas missing: report "not found" gracefully
            log.info("Geocoder unavailable for %r: %s", query, exc)
            return []
        return [self._from_candidate(c) for c in cands]

    def get(self, location_id: str) -> LocationOut | None:
        if self.gazetteer:
            e = self.gazetteer.get(location_id)
            if e:
                return AtlasGazetteer.to_location(e)
        for loc, _ in self._demo():
            if loc.id == location_id:
                return loc
        if self.geo is not None:
            try:
                r = self.geo.resolver.resolve_id(location_id)
                return LocationOut(id=r.id, name=r.name, display_name=r.display_name, lat=r.latitude, lon=r.longitude, source="geocoder")
            except Exception:
                return None
        return None

    def boundary(self, location_id: str) -> BoundaryOut | None:
        """Outline for a location: the atlas gazetteer first, then the geocoder's geometry, then a rough rectangle. Never invented."""
        if self.gazetteer:
            e = self.gazetteer.get(location_id)
            if e:
                return self.gazetteer.boundary(e)
        loc = self.get(location_id)
        if loc is None:
            return None
        geom, note, status, src = None, "", "unavailable", loc.source
        if self.geo is not None and not location_id.startswith(("demo:", "dataset:", "coord:")):
            try:
                r = self.geo.resolver.resolve_id(location_id)
                if r.geometry and r.geometry.get("type") in ("Polygon", "MultiPolygon"):
                    geom, status, note, src = r.geometry, "geocoder_geometry", "Outline returned by the geocoding source for this place.", r.source.provider_name
            except Exception as exc:
                log.info("No geocoder geometry for %s: %s", location_id, exc)
        if geom is None and loc.bbox:
            w, s, e, n = loc.bbox
            geom = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
            status, note = "approximate_bbox", "Only an extent is known for this place; the rectangle is approximate, not a boundary."
        return BoundaryOut(location_id=location_id, name=loc.name, level=loc.level, status=status, authoritative=status == "geocoder_geometry", note=note or "No outline is available for this place.", source=src, bbox=loc.bbox, geometry=geom,
                           area_km2=geodesic_area_km2(geom) if geom else None, area_is_approximate=status != "geocoder_geometry")

    @staticmethod
    def from_point(lat: float, lon: float) -> LocationOut:
        return LocationOut(id=f"coord:{lat:.5f},{lon:.5f}", name=f"{lat:.4f}, {lon:.4f}", display_name=f"{lat:.4f}°, {lon:.4f}°", lat=lat, lon=lon, kind="point", source="coordinates", zoom_altitude_m=20_000.0)
