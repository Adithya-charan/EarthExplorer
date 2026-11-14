"""Visualization preview and confirmation.

``preview`` re-resolves every location from its id (the client never supplies coordinates), validates the
preferences, derives the camera and warnings, and returns a summary plus a confirmation token.
``confirm`` recomputes the same preview and only returns the visualization if the user's token still matches,
so what is generated is exactly what was confirmed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.errors import AppError
from app.geo import geometry as G
from app.geo.coords import format_coordinates
from app.geo.resolver import Resolver, check_location_id
from app.geo.schemas import (
    AttributionItem,
    BBox,
    Camera,
    ConfirmRequest,
    GeneratedVisualization,
    Leg,
    Message,
    PreviewRequest,
    PreviewResponse,
    PreviewSummary,
    QualityItem,
    ResolvedLocation,
    SummaryLocation,
    VisualizationPreferences,
)

QUESTION = "Are these locations and visualization settings correct?"
POLAR_LIMIT = G.MERCATOR_MAX_LAT

# Camera windows for the viewpoint presets. These frame the view; they are not geographic boundaries.
PRESET_WINDOWS: dict[str, tuple[str, BBox]] = {
    "earth": ("Entire Earth", BBox(west=-180, south=-60, east=180, north=80)),
    "asia": ("Asia", BBox(west=25, south=-11, east=150, north=60)),
    "europe": ("Europe", BBox(west=-25, south=34, east=45, north=72)),
    "africa": ("Africa", BBox(west=-20, south=-36, east=55, north=38)),
    "north_america": ("North America", BBox(west=-170, south=7, east=-50, north=75)),
    "south_america": ("South America", BBox(west=-83, south=-57, east=-33, north=14)),
    "australia": ("Australia", BBox(west=112, south=-45, east=155, north=-9)),
    "antarctica": ("Antarctica", BBox(west=-180, south=-90, east=180, north=-60)),
}
SINGLE_POINT_ZOOM = {"city": 9.5, "landmark": 14.0, "mountain_peak": 11.0, "coordinate": 8.0, "other": 8.0, "island": 8.0, "region": 6.0}

ATTRIBUTION_CATALOG: dict[str, AttributionItem] = {
    "natural_earth": AttributionItem(
        id="natural_earth",
        text="Made with Natural Earth (public domain).",
        url="https://www.naturalearthdata.com",
        kind="generalized_data",
        note="Cartographic outlines and label positions at 1:10 to 1:50 million; not survey-grade or legal borders.",
    ),
    "osm": AttributionItem(
        id="osm",
        text="© OpenStreetMap contributors (ODbL 1.0).",
        url="https://www.openstreetmap.org/copyright",
        kind="verified_data",
        note="Geocoding results and base-map data are contributed by volunteers; positions are not independently verified.",
    ),
    "openfreemap": AttributionItem(
        id="openfreemap",
        text="Vector tiles by OpenFreeMap © OpenMapTiles, data from OpenStreetMap.",
        url="https://openfreemap.org",
        kind="verified_data",
    ),
    "gibs": AttributionItem(
        id="gibs",
        text="Imagery: NASA Global Imagery Browse Services (GIBS), part of NASA EOSDIS — Blue Marble Shaded Relief & Bathymetry.",
        url="https://earthdata.nasa.gov/gibs",
        kind="imagery",
        note="A static composite, not live and not current. Zoomed-in detail is limited to roughly 500 m per pixel.",
    ),
    "terrain": AttributionItem(
        id="terrain",
        text="Terrain: Terrain Tiles on AWS (Mapzen) — SRTM, GMTED2010, NED, ETOPO1 and other sources.",
        url="https://registry.opendata.aws/terrain-tiles/",
        kind="imagery",
        note="Elevation mosaic of mixed resolution; used for shading, not for measurement.",
    ),
    "computed": AttributionItem(
        id="computed",
        text="Day/night shading is computed from the Sun's position for the time shown; it is not satellite imagery.",
        kind="computed",
    ),
    "maplibre": AttributionItem(
        id="maplibre",
        text="Map rendering: MapLibre GL JS (BSD-3-Clause).",
        url="https://maplibre.org",
        kind="software",
    ),
}


def _geo_label(loc: ResolvedLocation) -> str:
    return f"{loc.name} ({loc.class_label.lower()})"


class VizService:
    def __init__(self, resolver: Resolver):
        self.resolver = resolver

    # ------------------------------------------------------------------------------ build
    def _resolve_all(self, req: PreviewRequest) -> list[ResolvedLocation]:
        ids = [check_location_id(r.location_id) for r in req.locations]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise AppError(422, "duplicate_locations", "The same location was selected more than once: " + ", ".join(dupes) + ". Remove the duplicate to continue.", {"ids": dupes})
        return [self.resolver.resolve_id(i, req.language) for i in ids]

    def _camera(self, locs: list[ResolvedLocation], prefs: VisualizationPreferences, language: str) -> Camera:
        vp = prefs.viewpoint
        if vp.mode == "preset":
            label, box = PRESET_WINDOWS[vp.preset or "earth"]
            lat, lon = G.bbox_center(box)
            return Camera(
                mode="preset",
                description=f"{label} (preset camera window)",
                bbox=box,
                center={"lat": lat, "lon": lon},
                framing_note="Preset windows frame the view; they are not geographic boundaries. Selected locations outside the window are still drawn.",
            )
        if vp.mode == "region":
            region = self.resolver.resolve_id(check_location_id(vp.region_location_id or ""), language)
            b = region.bbox
            if b is None or (b.east - b.west) < 1e-4 or (b.north - b.south) < 1e-4:
                raise AppError(422, "viewpoint_needs_area", f"'{region.name}' is a single point, so it cannot define a viewing region. Choose a country, region, ocean or other area.")
            lat, lon = G.bbox_center(b)
            return Camera(
                mode="region",
                description=f"Region: {region.name}",
                bbox=b,
                center={"lat": lat, "lon": lon},
                framing_note=f"Framed on the bounding box of '{region.name}' ({region.source.provider_name}).",
            )
        boxes = [loc.bbox or BBox(west=loc.point.longitude, south=loc.point.latitude, east=loc.point.longitude, north=loc.point.latitude) for loc in locs]
        box = G.union_bbox(boxes)
        lat, lon = G.bbox_center(box)
        single_point = len(locs) == 1 and (box.east - box.west) < 1e-4 and (box.north - box.south) < 1e-4
        zoom = SINGLE_POINT_ZOOM.get(locs[0].feature_class, 8.0) if single_point else None
        note = "Framed automatically on all selected locations (longitude extent chosen across the 180° meridian when shorter)."
        if box.crosses_antimeridian:
            note += " This view crosses the antimeridian."
        return Camera(mode="auto", description="Automatically frame all selected locations", bbox=box, center={"lat": lat, "lon": lon}, zoom_hint=zoom, framing_note=note)

    @staticmethod
    def _projection_2d(locs: list[ResolvedLocation], camera: Camera, prefs: VisualizationPreferences) -> tuple[str, list[Message]]:
        msgs: list[Message] = []
        lats = [loc.point.latitude for loc in locs] + [x for loc in locs if loc.bbox for x in (loc.bbox.south, loc.bbox.north)]
        beyond = any(abs(v) > POLAR_LIMIT for v in lats)
        if camera.mode == "preset" and prefs.viewpoint.preset == "antarctica":
            beyond = True
        if beyond:
            south = min(lats) < -POLAR_LIMIT or (camera.mode == "preset" and prefs.viewpoint.preset == "antarctica")
            msgs.append(
                Message(
                    code="polar_projection",
                    severity="info",
                    text=f"Some of this view lies beyond ±{POLAR_LIMIT:.2f}° latitude, which Web Mercator cannot show. The 2D view uses a polar stereographic projection of the vector atlas instead; the 3D globe shows the poles directly.",
                )
            )
            return ("polar_south" if south else "polar_north"), msgs
        if prefs.projection_2d == "mercator":
            return "mercator", msgs
        if prefs.projection_2d == "equal_earth":
            return "equal_earth", msgs
        b = camera.bbox
        wide = b is not None and ((b.east - b.west) > 100 or (b.north - b.south) > 70)
        if wide:
            msgs.append(
                Message(
                    code="projection_equal_earth",
                    severity="info",
                    text="This view spans a large part of the world, so the 2D map defaults to the Equal Earth projection, which keeps areas comparable. Web Mercator (tiles with satellite imagery) is available from the 2D projection setting but exaggerates areas toward the poles.",
                )
            )
            return "equal_earth", msgs
        return "mercator", msgs

    def _warnings(self, locs: list[ResolvedLocation], prefs: VisualizationPreferences, camera: Camera) -> list[Message]:
        w: list[Message] = []
        # near-duplicates (different ids, practically the same spot)
        for i in range(len(locs)):
            for j in range(i + 1, len(locs)):
                a, b = locs[i].point, locs[j].point
                d_km, _ = G.geodesic_leg(a.latitude, a.longitude, b.latitude, b.longitude)
                if d_km < 1.0:
                    w.append(Message(code="near_duplicate", severity="warning", text=f"'{locs[i].name}' and '{locs[j].name}' are less than 1 km apart; their markers will overlap."))
        crossing = [loc.name for loc in locs if loc.bbox and loc.bbox.crosses_antimeridian]
        if crossing or (camera.bbox and camera.bbox.crosses_antimeridian):
            names = ", ".join(crossing) if crossing else "the selected locations"
            w.append(Message(code="antimeridian", severity="info", text=f"{names} cross(es) the 180° meridian (the International Date Line region). The map shows them across the line rather than the long way round."))
        missing = [loc.name for loc in locs if loc.feature_class in ("country", "state_province", "continent", "ocean_sea", "lake", "river", "mountain_range", "desert", "forest", "island", "region") and not loc.geometry]
        if missing:
            w.append(Message(code="geometry_unavailable", severity="warning", text="No outline is available for " + ", ".join(missing) + "; each is shown as a single point, not as its real extent."))
        pts = [(loc.point.latitude, loc.point.longitude) for loc in locs]
        if prefs.format in ("3d", "both") and len(pts) > 1 and G.max_pairwise_angle(pts) > 150:
            w.append(Message(code="antipodal_span", severity="warning", text="Some selected locations are more than 150° apart, so they cannot all be on the visible side of the globe at once. Rotate the globe, or use the 2D map to see them together."))
        if prefs.style in ("satellite", "cinematic"):
            w.append(Message(code="imagery_static", severity="info", text="Satellite imagery is a static NASA Blue Marble composite: it is not live and does not show current conditions."))
        if prefs.effects.day_night:
            w.append(Message(code="day_night_computed", severity="info", text="Day/night shading is computed from the Sun's position at the time shown in the viewer. It is an illustration, not an observation."))
        if prefs.detail == "advanced" or prefs.effects.terrain_shading:
            w.append(Message(code="terrain_limits", severity="info", text="Terrain shading uses elevation tiles of mixed source and resolution; fine detail varies by region and is not suitable for measurement."))
        if any(loc.source.provider == "user" for loc in locs):
            w.append(Message(code="user_coordinates", severity="info", text="Locations entered as coordinates are plotted exactly where you typed them; EarthTrend does not check that they are the place you meant."))
        return w

    def _attributions(self, locs: list[ResolvedLocation], prefs: VisualizationPreferences) -> list[AttributionItem]:
        keys: list[str] = []
        providers = {loc.source.provider for loc in locs}
        if "natural_earth" in providers:
            keys.append("natural_earth")
        if "openstreetmap" in providers:
            keys.append("osm")
        if prefs.style != "satellite" or prefs.detail != "basic" or prefs.labels.region_names or prefs.effects.borders:
            keys += ["openfreemap", "osm"]
        if prefs.style in ("satellite", "cinematic"):
            keys.append("gibs")
        if prefs.detail == "advanced" or prefs.effects.terrain_shading:
            keys.append("terrain")
        if prefs.effects.day_night:
            keys.append("computed")
        keys.append("maplibre")
        seen: list[str] = []
        for k in keys:
            if k not in seen:
                seen.append(k)
        return [ATTRIBUTION_CATALOG[k] for k in seen]

    def _quality(self, locs: list[ResolvedLocation], prefs: VisualizationPreferences) -> list[QualityItem]:
        q: list[QualityItem] = []
        entered = [loc for loc in locs if loc.source.provider == "user"]
        pts = [loc for loc in locs if loc.geometry_info.quality != "generalized" and loc.source.provider != "user"]
        if pts:
            q.append(QualityItem(category="source_data", text="Positions reported by a named source (not independently verified): " + "; ".join(f"{loc.name} — {loc.source.provider_name}" for loc in pts) + "."))
        if entered:
            q.append(QualityItem(category="source_data", text="Positions plotted exactly as you entered them (not checked against any place): " + "; ".join(loc.name for loc in entered) + "."))
        shaped = [loc for loc in locs if loc.geometry_info.quality == "generalized"]
        if shaped:
            q.append(QualityItem(category="generalized", text="Generalized outlines (display only, not for measurement): " + "; ".join(f"{loc.name} — {loc.geometry_info.generalization}" for loc in shaped) + "."))
        miss = [loc for loc in locs if loc.geometry_info.quality == "unavailable"]
        if miss:
            q.append(QualityItem(category="unavailable", text="Outline unavailable (shown as a point): " + ", ".join(loc.name for loc in miss) + "."))
        illus = ["numbered markers and labels"]
        if prefs.effects.atmosphere:
            illus.append("atmosphere glow")
        if prefs.effects.day_night:
            illus.append("day/night shading")
        if prefs.effects.connect_lines:
            illus.append("connecting lines (geodesics between consecutive locations)")
        q.append(QualityItem(category="illustrative", text="Visual elements that are decorative or computed, not observations: " + ", ".join(illus) + "."))
        return q

    @staticmethod
    def _legs(locs: list[ResolvedLocation]) -> tuple[list[Leg], dict[str, Any]]:
        legs: list[Leg] = []
        features: list[dict[str, Any]] = []
        for i in range(len(locs) - 1):
            a, b = locs[i].point, locs[i + 1].point
            dist, brg = G.geodesic_leg(a.latitude, a.longitude, b.latitude, b.longitude)
            path = G.geodesic_path(a.latitude, a.longitude, b.latitude, b.longitude)
            crosses = any(abs(lon) > 180 for lon, _ in path)
            legs.append(Leg(from_index=i + 1, to_index=i + 2, distance_km=round(dist, 1), initial_bearing_deg=round(brg, 1), crosses_antimeridian=crosses))
            features.append(
                {
                    "type": "Feature",
                    "properties": {"from": i + 1, "to": i + 2, "distance_km": round(dist, 1)},
                    "geometry": {"type": "LineString", "coordinates": [[round(lon, 5), round(lat, 5)] for lon, lat in path]},
                }
            )
        return legs, {"type": "FeatureCollection", "features": features}

    def _build(self, req: PreviewRequest) -> dict[str, Any]:
        prefs = req.preferences
        locs = self._resolve_all(req)
        camera = self._camera(locs, prefs, req.language)
        projection, proj_msgs = self._projection_2d(locs, camera, prefs)
        warnings = self._warnings(locs, prefs, camera) + proj_msgs
        legs, connections = self._legs(locs)
        return {"prefs": prefs, "locs": locs, "camera": camera, "projection": projection, "warnings": warnings, "legs": legs, "connections": connections}

    @staticmethod
    def _token(built: dict[str, Any]) -> str:
        payload = {
            "v": 1,
            "locations": [
                {"id": loc.id, "lat": loc.point.latitude, "lon": loc.point.longitude, "geom": hashlib.sha256(json.dumps(loc.geometry, sort_keys=True, separators=(",", ":")).encode()).hexdigest() if loc.geometry else None}
                for loc in built["locs"]
            ],
            "prefs": built["prefs"].model_dump(mode="json"),
            "camera": built["camera"].model_dump(mode="json"),
            "projection": built["projection"],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    # ------------------------------------------------------------------------------ public
    def preview(self, req: PreviewRequest) -> PreviewResponse:
        b = self._build(req)
        prefs: VisualizationPreferences = b["prefs"]
        locs: list[ResolvedLocation] = b["locs"]
        summary_locs = [
            SummaryLocation(
                index=i + 1,
                id=loc.id,
                name=prefs.labels.custom.get(loc.id) or loc.name,
                display_name=loc.display_name,
                context_label=loc.context.label,
                country=loc.context.country,
                class_label=loc.class_label,
                feature_class=loc.feature_class,
                latitude=loc.point.latitude,
                longitude=loc.point.longitude,
                coordinates_text=format_coordinates(loc.point.latitude, loc.point.longitude),
                geometry_type=loc.geometry_type,
                geometry_quality=(loc.geometry_info.generalization or loc.geometry_info.note or "point") if loc.geometry_info.available else (loc.geometry_info.note or "point"),
                point_kind=loc.point.kind,
                source=loc.source.provider_name,
                data_status=loc.validation.status,
            )
            for i, loc in enumerate(locs)
        ]
        summary = PreviewSummary(
            locations=summary_locs,
            format=prefs.format,
            viewpoint=b["camera"].description,
            detail=prefs.detail,
            style=prefs.style,
            labels=prefs.labels.model_dump(),
            effects=prefs.effects.model_dump(),
            projection_2d=b["projection"],
            legs=b["legs"],
        )
        return PreviewResponse(
            question=QUESTION,
            summary=summary,
            camera=b["camera"],
            warnings=b["warnings"],
            attributions=self._attributions(locs, prefs),
            data_quality=self._quality(locs, prefs),
            confirmation_token=self._token(b),
            can_confirm=True,
        )

    def confirm(self, req: ConfirmRequest) -> GeneratedVisualization:
        if not req.confirmed:
            raise AppError(400, "not_confirmed", "The visualization is only generated after you confirm the summary. Send confirmed=true to proceed.")
        b = self._build(req)
        if self._token(b) != req.confirmation_token:
            raise AppError(409, "stale_confirmation", "The locations or settings changed since you reviewed them (or the geocoder returned different data). Review the summary again.")
        prefs: VisualizationPreferences = b["prefs"]
        locs: list[ResolvedLocation] = b["locs"]
        return GeneratedVisualization(
            id=uuid.uuid4().hex,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            confirmed_token=req.confirmation_token,
            preferences=prefs,
            locations=locs,
            connections=b["connections"],  # always computed; the client decides whether to draw them
            legs=b["legs"],
            camera=b["camera"],
            warnings=b["warnings"],
            attributions=self._attributions(locs, prefs),
            notes=[f"2D projection: {b['projection']}", "Generated after explicit user confirmation."],
        )
