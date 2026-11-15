"""LocationService: place name -> coordinates. A small offline demo gazetteer first, then the app's geocoder (tolerating failure)."""

from __future__ import annotations

import logging
import re
import unicodedata

from app.explorer.datasets import DatasetService
from app.explorer.schemas import LocationOut

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
    def __init__(self, datasets: DatasetService, geo=None):
        self.datasets = datasets
        self.geo = geo

    def examples(self) -> list[str]:
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

    def search(self, query: str, *, online: bool = True, limit: int = 6) -> list[LocationOut]:
        q = fold(query)
        if not q:
            return []
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
        out: list[LocationOut] = []
        for c in cands:
            bb = None
            if c.bbox is not None and not c.bbox.crosses_antimeridian:
                bb = [c.bbox.west, c.bbox.south, c.bbox.east, c.bbox.north]
            alt = 12_000.0
            if bb:
                span = max(bb[2] - bb[0], bb[3] - bb[1])
                alt = float(min(6_000_000.0, max(8_000.0, span * 111_000 * 2.2)))
            out.append(LocationOut(id=c.id, name=c.name, display_name=c.display_name, lat=c.latitude, lon=c.longitude, kind=c.class_label.lower(), source=c.provider_name, bbox=bb, zoom_altitude_m=alt))
        return out

    def get(self, location_id: str) -> LocationOut | None:
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

    @staticmethod
    def from_point(lat: float, lon: float) -> LocationOut:
        return LocationOut(id=f"coord:{lat:.5f},{lon:.5f}", name=f"{lat:.4f}, {lon:.4f}", display_name=f"{lat:.4f}°, {lon:.4f}°", lat=lat, lon=lon, kind="point", source="coordinates", zoom_altitude_m=20_000.0)
