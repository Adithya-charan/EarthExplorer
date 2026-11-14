"""Geometry helpers: antimeridian-safe extents, label points, simplification and geodesic measures.

All coordinates are WGS84 longitude/latitude in degrees. Measurements use the WGS84 ellipsoid via pyproj.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import shapely
from pyproj import Geod
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge

from app.geo.schemas import BBox

GEOD = Geod(ellps="WGS84")
MERCATOR_MAX_LAT = 85.0511287798  # latitude limit of Web Mercator tiles


# ------------------------------------------------------------------------- longitude extents
def wrap_lon(lon: float) -> float:
    """Wrap a longitude into [-180, 180]. 180 stays 180, -180 stays -180."""
    if -180.0 <= lon <= 180.0:
        return lon
    return ((lon + 180.0) % 360.0) - 180.0


def circular_extent(intervals: Iterable[tuple[float, float]]) -> tuple[float, float, bool]:
    """Smallest longitude arc covering all ``(min_lon, max_lon)`` intervals (each within -180..180).

    Returns ``(west, east, crosses)``. When ``crosses`` is true ``east`` is unwrapped (> 180), so a feature
    on both sides of the antimeridian (Fiji, Russia's Chukotka, the Aleutians) gets a narrow box instead
    of one spanning the whole world. If nothing is uncovered the whole circle is returned.
    """
    ivs = sorted((min(a, b), max(a, b)) for a, b in intervals)
    if not ivs:
        raise ValueError("no intervals")
    merged: list[list[float]] = []
    for lo, hi in ivs:
        if merged and lo <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    if len(merged) == 1:
        return merged[0][0], merged[0][1], False

    # Gaps between consecutive merged intervals, plus the gap that wraps around the antimeridian.
    best_gap = -1.0
    best_idx = -1  # the arc starts right after merged[best_idx]
    for i in range(len(merged)):
        nxt = merged[(i + 1) % len(merged)]
        gap = nxt[0] - merged[i][1] if i + 1 < len(merged) else (nxt[0] + 360.0) - merged[i][1]
        if gap > best_gap:
            best_gap, best_idx = gap, i
    if best_idx == len(merged) - 1:  # the largest gap is the one around the antimeridian: no crossing
        return merged[0][0], merged[-1][1], False
    west = merged[best_idx + 1][0]
    east = merged[best_idx][1] + 360.0
    return west, east, True


def _part_intervals(geom: BaseGeometry) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for part in shapely.get_parts(geom):
        if part.is_empty:
            continue
        minx, _, maxx, _ = part.bounds
        out.append((minx, maxx))
    return out


def geometry_bbox(geom: BaseGeometry) -> BBox:
    """Antimeridian-aware bounding box of a (multi-)geometry."""
    if geom.is_empty:
        raise ValueError("empty geometry")
    west, east, crosses = circular_extent(_part_intervals(geom))
    _, miny, _, maxy = geom.bounds
    return BBox(west=west, south=miny, east=east, north=maxy, crosses_antimeridian=crosses)


def bbox_from_extent(west: float, south: float, east: float, north: float) -> BBox:
    """Build a BBox from provider values where ``west > east`` means the box crosses the antimeridian."""
    west, east = wrap_lon(west), wrap_lon(east)
    crosses = east < west
    return BBox(west=west, south=south, east=east + 360.0 if crosses else east, north=north, crosses_antimeridian=crosses)


def union_bbox(boxes: list[BBox]) -> BBox:
    """Combine boxes, choosing the narrowest longitude arc (so Tonga + Fiji do not span the globe)."""
    intervals: list[tuple[float, float]] = []
    for b in boxes:
        if b.east > 180.0:
            intervals.append((b.west, 180.0))
            intervals.append((-180.0, wrap_lon(b.east)))
        else:
            intervals.append((b.west, b.east))
    west, east, crosses = circular_extent(intervals)
    return BBox(
        west=west,
        south=min(b.south for b in boxes),
        east=east,
        north=max(b.north for b in boxes),
        crosses_antimeridian=crosses,
    )


def bbox_center(b: BBox) -> tuple[float, float]:
    """(lat, lon) of the box centre, with longitude wrapped back into -180..180."""
    return (b.south + b.north) / 2.0, wrap_lon((b.west + b.east) / 2.0)


# ---------------------------------------------------------------------------- label points
def representative_point(geom: BaseGeometry) -> tuple[float, float, str]:
    """(lat, lon, kind) of a point that lies on the feature (polygons: inside the largest part)."""
    if isinstance(geom, Point):
        return geom.y, geom.x, "provider_point"
    if isinstance(geom, (LineString, MultiLineString)):
        return (*_line_midpoint(geom), "line_midpoint")
    parts = [p for p in shapely.get_parts(geom) if isinstance(p, Polygon) and not p.is_empty]
    if not parts:
        p = geom.representative_point()
        return p.y, p.x, "representative_point"
    biggest = max(parts, key=lambda p: p.area)
    p = biggest.representative_point()
    return p.y, p.x, "representative_point"


def _line_midpoint(geom: BaseGeometry) -> tuple[float, float]:
    merged = linemerge(geom) if isinstance(geom, MultiLineString) else geom
    parts = [p for p in shapely.get_parts(merged) if isinstance(p, LineString) and not p.is_empty]
    longest = max(parts, key=lambda p: p.length)
    mid = longest.interpolate(0.5, normalized=True)
    return mid.y, mid.x


# --------------------------------------------------------------------------- measuring
def vertex_count(geom: BaseGeometry) -> int:
    return int(shapely.get_num_coordinates(geom))


def geodesic_area_km2(geom: BaseGeometry) -> float | None:
    """WGS84 geodesic area of polygons in km², or None for non-polygons and polygons that enclose a pole."""
    polys = [p for p in shapely.get_parts(geom) if isinstance(p, Polygon) and not p.is_empty]
    if not polys:
        return None
    _, miny, _, maxy = geom.bounds
    if miny <= -89.5 or maxy >= 89.5:
        return None  # a polygon wrapping a pole needs special handling; do not report a wrong number
    total = 0.0
    for p in polys:
        area, _ = GEOD.geometry_area_perimeter(p)
        total += abs(area)
    return total / 1e6


def geodesic_length_km(geom: BaseGeometry) -> float | None:
    lines = [p for p in shapely.get_parts(geom) if isinstance(p, LineString) and not p.is_empty]
    if not lines:
        return None
    return sum(GEOD.geometry_length(line) for line in lines) / 1000.0


def ensure_valid(geom: BaseGeometry) -> BaseGeometry:
    if geom.is_valid:
        return geom
    fixed = shapely.make_valid(geom)
    if fixed.geom_type == "GeometryCollection":
        keep = [g for g in shapely.get_parts(fixed) if g.geom_type in ("Polygon", "MultiPolygon", "LineString", "MultiLineString")]
        if keep:
            fixed = shapely.union_all(keep)
    return fixed


SIMPLIFY_STEPS_DEG = (0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5)


def simplify_to_budget(geom: BaseGeometry, max_vertices: int) -> tuple[BaseGeometry, float | None]:
    """Reduce vertices only as far as needed to fit ``max_vertices``. Returns (geometry, tolerance used)."""
    if vertex_count(geom) <= max_vertices:
        return geom, None
    for tol in SIMPLIFY_STEPS_DEG:
        simplified = geom.simplify(tol, preserve_topology=True)
        if not simplified.is_empty and vertex_count(simplified) <= max_vertices:
            return simplified, tol
    last = geom.simplify(SIMPLIFY_STEPS_DEG[-1], preserve_topology=True)
    return last, SIMPLIFY_STEPS_DEG[-1]


def round_coords(obj: Any, ndigits: int = 5) -> Any:
    """Round every coordinate in a GeoJSON geometry mapping (5 decimals ≈ 1 m)."""
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(v), ndigits) for v in obj]
        return [round_coords(o, ndigits) for o in obj]
    if isinstance(obj, dict):
        return {k: (round_coords(v, ndigits) if k == "coordinates" else v) for k, v in obj.items()}
    return obj


def to_geojson(geom: BaseGeometry, ndigits: int = 5) -> dict[str, Any]:
    return round_coords(mapping(geom), ndigits)


def crosses_antimeridian(geom: BaseGeometry) -> bool:
    return geometry_bbox(geom).crosses_antimeridian


# ------------------------------------------------------------------------------ geodesics
def geodesic_leg(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    """(distance in km, initial bearing in degrees 0-360) along the WGS84 geodesic."""
    az12, _, dist = GEOD.inv(lon1, lat1, lon2, lat2)
    return dist / 1000.0, az12 % 360.0


def geodesic_path(lat1: float, lon1: float, lat2: float, lon2: float, n: int = 48) -> list[tuple[float, float]]:
    """Points (lon, lat) along the geodesic, with longitudes *unwrapped* so a line crossing the antimeridian
    continues (170, 175, 181, 186 ...) instead of jumping across the map."""
    pts = [(lon1, lat1)] + GEOD.npts(lon1, lat1, lon2, lat2, n) + [(lon2, lat2)]
    out: list[tuple[float, float]] = []
    prev: float | None = None
    for lon, lat in pts:
        if prev is not None:
            while lon - prev > 180.0:
                lon -= 360.0
            while lon - prev < -180.0:
                lon += 360.0
        out.append((lon, lat))
        prev = lon
    return out


def angular_distance_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle angular distance on a sphere, in degrees."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def max_pairwise_angle(points: list[tuple[float, float]]) -> float:
    """Largest great-circle angle (degrees) between any two (lat, lon) points."""
    best = 0.0
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            best = max(best, angular_distance_deg(*points[i], *points[j]))
    return best


def tile_xy(lat: float, lon: float, zoom: int) -> tuple[int, int, float, float]:
    """Slippy-map tile (x, y) containing the point plus the fractional position (0..1) inside it."""
    lat = max(-MERCATOR_MAX_LAT, min(MERCATOR_MAX_LAT, lat))
    n = 2**zoom
    xf = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    yf = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    x, y = min(n - 1, max(0, int(xf))), min(n - 1, max(0, int(yf)))
    return x, y, xf - x, yf - y
