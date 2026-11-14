"""Natural Earth gazetteer: name search, feature geometry and point-in-polygon context.

Natural Earth (public domain) supplies the *reference geometry* for countries, states / provinces, continents,
oceans and seas, physical regions (ranges, deserts, ...), lakes, rivers and a list of cities and named peaks.
The files are fetched by ``scripts/fetch_natural_earth.py``; nothing here talks to the network.

Accuracy notes that are carried into the API responses:

* Polygons are cartographic generalizations (1:10m to 1:50m). They are not survey-grade or legal borders.
* Point positions for places and peaks are placed for map labelling and can be kilometres from the true
  centre / summit. The resolver prefers OpenStreetMap points for cities and peaks for that reason.
"""

from __future__ import annotations

import bisect
import json
import logging
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.errors import AppError
from app.geo import geometry as G
from app.geo.schemas import (
    CLASS_LABELS,
    SHAPE_BY_CLASS,
    BBox,
    Candidate,
    Context,
    Fact,
    GeometryInfo,
    PointInfo,
    ResolvedLocation,
    SourceInfo,
    Validation,
)
from app.geo.text import fold, title_case_if_shouting

log = logging.getLogger("earthtrend.geo")

SOURCE_URL = "https://www.naturalearthdata.com"
LAYER_DIRS = {
    "countries": "ne_50m_admin_0_countries",
    "admin1": "ne_10m_admin_1_states_provinces",
    "places": "ne_10m_populated_places_simple",
    "marine": "ne_10m_geography_marine_polys",
    "regions": "ne_10m_geography_regions_polys",
    "regionpts": "ne_10m_geography_regions_points",
    "peaks": "ne_10m_geography_regions_elevation_points",
    "rivers": "ne_10m_rivers_lake_centerlines",
    "lakes": "ne_10m_lakes",
}
SCALE_LABEL = {"50m": "1:50 million", "10m": "1:10 million"}
MAX_AREA_VERTICES = 12_000
MAX_LINE_VERTICES = 20_000
CONTEXT_SIMPLIFY_DEG = 0.05

_SPLIT = re.compile(r"[|;]")

POINT_NOTES = {
    "label_point": "Cartographic label position supplied by Natural Earth. It marks the feature on a map; it is not a precise location.",
    "representative_point": "A point guaranteed to lie on the feature, computed from its geometry. It is not the feature's centre or a surveyed location.",
    "line_midpoint": "Midpoint along the longest connected stretch of the line geometry. It is not the river's source or mouth.",
    "place": "Position of the place as stored in Natural Earth, which is placed for 1:10 million cartography. Expect offsets of kilometres from a city centre.",
    "peak": "Natural Earth positions mountains for map labelling at 1:10 million; the position can be several kilometres from the summit.",
    "builtin": "The geographic poles are defined as 90° N and 90° S latitude. Longitude is undefined at a pole; 0° is used for display.",
}

REGION_CLASS = {
    "Range/mtn": "mountain_range",
    "Desert": "desert",
    "Continent": "continent",
    "Island": "island",
    "Island group": "island",
    "Lake": "lake",
}


@dataclass(slots=True)
class Entry:
    id: str
    layer: str
    name: str
    feature_class: str
    class_label: str
    lat: float
    lon: float
    point_kind: str
    context: Context
    importance: float
    names: set[str] = field(default_factory=set)
    fids: list[int] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    bbox: BBox | None = None
    note: str | None = None
    point_note_key: str | None = None
    dataset_scale: str = "10m"
    # Country context for regions / lakes / rivers is computed on first use (it needs geometry work).
    context_pending: str | None = None
    fallback_label: str | None = None


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _display_name(e: Entry, ctx: Context) -> str:
    """A name that tells same-named places apart: 'Springfield, Illinois, United States of America',
    'Georgia (state), United States of America', 'Georgia' (the country)."""
    if e.feature_class == "state_province":
        kind = (e.class_label or "region").lower()
        return f"{e.name} ({kind})" + (f", {ctx.country}" if ctx.country else "")
    if e.feature_class == "city" and ctx.label:
        return f"{e.name}, {ctx.label}"
    return e.name


def _nz(v: Any) -> str | None:
    """Non-empty string from a possibly-missing cell."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip()
    return s or None


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _names_from(row: dict[str, Any], cols: list[str]) -> set[str]:
    out: set[str] = set()
    for c in cols:
        v = _nz(row.get(c))
        if not v:
            continue
        for part in _SPLIT.split(v):
            f = fold(part)
            if f:
                out.add(f)
                if re.fullmatch(r"(?:[a-z] ?){2,5}", f):  # 'u s a' -> 'usa'
                    out.add(f.replace(" ", ""))
    return out


def _records(df: pd.DataFrame) -> tuple[list[dict[str, Any]], list[BaseGeometry]]:
    """Plain dict rows (fast to read) plus a parallel list of geometries."""
    if isinstance(df, gpd.GeoDataFrame):
        geoms = list(df.geometry)
        plain = pd.DataFrame(df.drop(columns=df.geometry.name))
    else:
        geoms, plain = [], df
    return plain.to_dict("records"), geoms


def _lang_cols(df: pd.DataFrame) -> list[str]:
    skip = {"name_len", "name_sort", "name_local", "name_alt", "name_abb", "name_ciawf"}
    return [c for c in df.columns if c.startswith("name_") and c not in skip]


class Gazetteer:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self._lock = threading.RLock()
        self._ready = False
        self._failed: str | None = None
        self.entries: dict[str, Entry] = {}
        self._exact: dict[str, list[str]] = {}
        self._primary: list[tuple[str, str]] = []  # (folded primary name, entry id) for substring search
        self._prefix: list[tuple[str, str]] = []  # sorted (folded name, entry id) for prefix search
        self._gdf: dict[str, gpd.GeoDataFrame] = {}
        self._coarse_countries: gpd.GeoDataFrame | None = None
        self._admin1_full: gpd.GeoDataFrame | None = None
        self.manifest: dict[str, Any] = {}

    # ----------------------------------------------------------------------------- loading
    @property
    def available(self) -> bool:
        return all(self._layer_path(k) is not None for k in LAYER_DIRS)

    def _layer_path(self, layer: str) -> Path | None:
        d = self.dir / LAYER_DIRS[layer]
        return next(iter(d.glob("*.shp")), None) if d.is_dir() else None

    def _read(self, layer: str, *, geometry: bool = True, **kwargs: Any) -> gpd.GeoDataFrame | pd.DataFrame:
        path = self._layer_path(layer)
        if path is None:
            raise AppError(503, "geo_data_missing", f"Natural Earth layer '{LAYER_DIRS[layer]}' is not installed. Run scripts/fetch_natural_earth.py.")
        df = pyogrio.read_dataframe(path, read_geometry=geometry, encoding="utf-8", **kwargs)
        df.columns = [c if c == "geometry" else c.lower() for c in df.columns]
        return df

    def warm(self) -> None:
        """Build the index now (otherwise it is built on first use)."""
        self._ensure()

    def _ensure(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            if not self.available:
                self._failed = "Natural Earth data files are not installed. Run: python scripts/fetch_natural_earth.py"
                raise AppError(503, "geo_data_missing", self._failed)
            manifest = self.dir / "manifest.json"
            if manifest.is_file():
                try:
                    self.manifest = json.loads(manifest.read_text(encoding="utf-8"))
                except ValueError:
                    self.manifest = {}
            self._build_index()
            self._ready = True
            log.info("Natural Earth gazetteer ready: %d features", len(self.entries))

    # -------------------------------------------------------------------------- index build
    def _add(self, e: Entry, extra_names: set[str], primary: list[str]) -> None:
        if e.id in self.entries:  # defensive: ids must be unique
            return
        folded_primary = [f for f in (fold(p) for p in primary) if f]
        e.names |= extra_names | set(folded_primary)
        self.entries[e.id] = e
        for n in e.names:
            self._exact.setdefault(n, []).append(e.id)
            self._prefix.append((n, e.id))
        for f in folded_primary:
            self._primary.append((f, e.id))

    def _build_index(self) -> None:
        self._entries_countries()
        self._entries_admin1()
        self._entries_places()
        self._entries_marine()
        self._entries_regions()
        self._entries_regionpts()
        self._entries_peaks()
        self._entries_lakes()
        self._entries_rivers()
        self._entries_builtin()
        self._prefix.sort()
        self._primary = sorted(set(self._primary))

    def _countries(self) -> gpd.GeoDataFrame:
        if "countries" not in self._gdf:
            self._gdf["countries"] = self._read("countries")
        return self._gdf["countries"]

    def _entries_countries(self) -> None:
        df = self._countries()
        lang = _lang_cols(df)
        rows, geoms = _records(df)
        seen: set[str] = set()
        for pos, row in enumerate(rows):
            if _nz(row.get("continent")) == "Antarctica":
                continue  # represented by the continent polygon instead
            geom = geoms[pos]
            code = _nz(row.get("adm0_a3")) or f"r{pos}"
            if code in seen:
                code = f"{code}-{pos}"
            seen.add(code)
            name = _nz(row.get("name_en")) or _nz(row.get("name")) or code
            sovereign = _nz(row.get("sovereignt"))
            kind = _nz(row.get("type")) or "Country"
            continent = _nz(row.get("continent"))
            iso2 = _nz(row.get("iso_a2"))
            iso2 = iso2 if iso2 and iso2 != "-99" else None
            if sovereign and fold(sovereign) != fold(name) and kind in ("Dependency", "Disputed", "Country", "Indeterminate"):
                class_label = f"Dependency or territory of {sovereign}" if kind == "Dependency" else CLASS_LABELS["country"]
                label = f"{class_label} · {continent}" if continent else class_label
            else:
                label = continent or None
                class_label = CLASS_LABELS["country"]
            facts: list[Fact] = []
            pop = _num(row.get("pop_est"))
            if pop and pop > 0:
                year = _nz(row.get("pop_year"))
                facts.append(Fact(key="population", label="Population estimate" + (f" ({year})" if year and year != "0" else ""), value=int(pop), source="Natural Earth"))
            for key, label_txt, col in (("continent", "Continent (Natural Earth classification)", "continent"), ("subregion", "Subregion", "subregion"), ("sovereign", "Sovereign state", "sovereignt"), ("status", "Status in Natural Earth", "type")):
                v = _nz(row.get(col))
                if v:
                    facts.append(Fact(key=key, label=label_txt, value=v, source="Natural Earth"))
            wd = _nz(row.get("wikidataid"))
            if wd:
                facts.append(Fact(key="wikidata", label="Wikidata ID", value=wd, source="Natural Earth"))
            lat, lon = _num(row.get("label_y")), _num(row.get("label_x"))
            kind_pt = "label_point"
            if lat is None or lon is None or not geom.buffer(0).contains(Point(lon, lat)):
                lat, lon, kind_pt = G.representative_point(geom)
            pop_rank = _num(row.get("pop_rank")) or 8
            e = Entry(
                id=f"ne:admin0:{code}",
                layer="countries",
                name=name,
                feature_class="country",
                class_label=class_label,
                lat=lat,
                lon=lon,
                point_kind=kind_pt,
                context=Context(country=name, country_code=iso2, label=label, source_note="Natural Earth admin-0"),
                importance=_clamp(0.6 + 0.4 * pop_rank / 18.0),
                fids=[pos],
                facts=facts,
                bbox=G.geometry_bbox(geom),
                dataset_scale="50m",
            )
            self._add(e, _names_from(row, lang + ["name", "name_long", "admin", "formal_en", "abbrev", "name_alt", "brk_name"]), [name, _nz(row.get("name_long")) or "", _nz(row.get("formal_en")) or ""])

    def _entries_admin1(self) -> None:
        df = self._read("admin1", geometry=False)
        lang = _lang_cols(df)
        rows, _ = _records(df)
        for pos, row in enumerate(rows):
            raw_id = _nz(row.get("ne_id"))
            code = raw_id or re.sub(r"[^A-Za-z0-9_.-]+", "_", _nz(row.get("adm1_code")) or f"r{pos}")
            name = _nz(row.get("name_en")) or _nz(row.get("name"))
            lat, lon = _num(row.get("latitude")), _num(row.get("longitude"))
            if not name or lat is None or lon is None:
                continue
            admin = _nz(row.get("admin"))
            kind = _nz(row.get("type_en")) or "Region"
            iso2 = _nz(row.get("iso_a2"))
            facts = [Fact(key="admin_type", label="Administrative type", value=kind, source="Natural Earth")]
            for key, lbl, col in (("iso_3166_2", "ISO 3166-2 code", "iso_3166_2"), ("wikidata", "Wikidata ID", "wikidataid")):
                v = _nz(row.get(col))
                if v:
                    facts.append(Fact(key=key, label=lbl, value=v, source="Natural Earth"))
            area = _num(row.get("area_sqkm"))
            if area and area > 0:
                facts.append(Fact(key="area_sqkm", label="Area (Natural Earth attribute)", value=round(area, 1), unit="km²", source="Natural Earth"))
            e = Entry(
                id=f"ne:admin1:{code}",
                layer="admin1",
                name=name,
                feature_class="state_province",
                class_label=kind,
                lat=lat,
                lon=lon,
                point_kind="label_point",
                context=Context(country=admin, country_code=iso2, label=admin or kind, source_note="Natural Earth admin-1"),
                importance=_clamp(0.55 - 0.03 * (_num(row.get("labelrank")) or 3)),
                fids=[pos],
                facts=facts,
            )
            self._add(e, _names_from(row, lang + ["name", "name_alt", "name_local"]), [name, _nz(row.get("name")) or ""])

    def _entries_places(self) -> None:
        df = self._read("places", geometry=False)
        rows, _ = _records(df)
        for pos, row in enumerate(rows):
            nid = _nz(row.get("ne_id")) or f"r{pos}"
            name = _nz(row.get("name"))
            lat, lon = _num(row.get("latitude")), _num(row.get("longitude"))
            if not name or lat is None or lon is None:
                continue
            fc = _nz(row.get("featurecla")) or "Populated place"
            if fc in ("Scientific station", "Meteorological Station", "Historic place"):
                fclass, label = "landmark", fc
            else:
                fclass, label = "city", ("Capital city" if "Admin-0 capital" in fc else CLASS_LABELS["city"])
            country, adm1, iso2 = _nz(row.get("adm0name")), _nz(row.get("adm1name")), _nz(row.get("iso_a2"))
            pop = _num(row.get("pop_max")) or 0
            if pop <= 0:  # Natural Earth uses -99 (and 0) for "unknown"; never present that as a population
                pop = 0
            facts: list[Fact] = []
            if pop > 0:
                facts.append(Fact(key="population", label="Population (largest Natural Earth estimate)", value=int(pop), source="Natural Earth"))
            if "capital" in fc.lower():
                facts.append(Fact(key="capital", label="Role", value=fc, source="Natural Earth"))
            e = Entry(
                id=f"ne:place:{nid}",
                layer="places",
                name=name,
                feature_class=fclass,
                class_label=label,
                lat=lat,
                lon=lon,
                point_kind="provider_point",
                context=Context(country=country, country_code=iso2, admin1=adm1, label=", ".join(x for x in (adm1, country) if x) or None, source_note="Natural Earth populated places"),
                importance=_clamp(math.log10(pop + 10) / 7.5) if pop else 0.15,
                fids=[pos],
                facts=facts,
                point_note_key="place",
            )
            self._add(e, _names_from(row, ["name", "nameascii", "namealt", "namepar"]), [name, _nz(row.get("nameascii")) or ""])

    def _entries_marine(self) -> None:
        df = self._read("marine")
        self._gdf["marine"] = df
        lang = _lang_cols(df)
        rows, geoms = _records(df)
        info: dict[int, dict[str, Any]] = {}
        for pos, row in enumerate(rows):
            name = _nz(row.get("name"))
            if not name:
                continue
            info[pos] = {"name": title_case_if_shouting(name) or name, "fc": (_nz(row.get("featurecla")) or "sea").lower(), "name_en": _nz(row.get("name_en"))}
        # Oceans that Natural Earth splits for labelling (North/South Pacific, North/South Atlantic) are also
        # offered as one feature, built by taking the union of the Natural Earth polygons.
        by_en: dict[str, list[int]] = {}
        for pos, r in info.items():
            if r["fc"] == "ocean" and r["name_en"]:
                by_en.setdefault(r["name_en"], []).append(pos)
        composite_of: dict[int, str] = {}
        for en, poss in by_en.items():
            if len(poss) < 2:
                continue
            geom = unary_union([geoms[p] for p in poss])
            lat, lon, kind = G.representative_point(geom)
            parts = " + ".join(info[p]["name"] for p in poss)
            e = Entry(
                id=f"ne:marine:{fold(en).replace(' ', '-')}",
                layer="marine",
                name=en,
                feature_class="ocean_sea",
                class_label="Ocean",
                lat=lat,
                lon=lon,
                point_kind=kind,
                context=Context(label="Ocean", source_note="Natural Earth marine areas"),
                importance=1.0,
                fids=poss,
                bbox=G.geometry_bbox(geom),
                note=f"Union of Natural Earth polygons: {parts}.",
            )
            self._add(e, set(), [en])
            for p in poss:
                composite_of[p] = en
        for pos, r in info.items():
            row, geom = rows[pos], geoms[pos]
            lat, lon, kind = G.representative_point(geom)
            fc = r["fc"]
            if fc == "river":  # an estuary / river-mouth polygon, not the river itself
                fclass, cls_label = "region", "River mouth or estuary (marine area)"
            else:
                fclass, cls_label = "ocean_sea", {"ocean": "Ocean", "sea": "Sea"}.get(fc, fc.capitalize())
            comp = composite_of.get(pos)
            e = Entry(
                id=f"ne:marine:{_nz(row.get('ne_id')) or pos}",
                layer="marine",
                name=r["name"],
                feature_class=fclass,
                class_label=cls_label,
                lat=lat,
                lon=lon,
                point_kind=kind,
                context=Context(label=f"Part of the {comp}" if comp else cls_label, source_note="Natural Earth marine areas"),
                importance=_clamp(0.9 - 0.12 * (_num(row.get("scalerank")) or 3)),
                fids=[pos],
                bbox=G.geometry_bbox(geom),
            )
            names = _names_from(row, lang + ["name", "namealt", "label"])
            if comp:  # the composite owns the generic English name
                names.discard(fold(comp))
            self._add(e, names, [r["name"]])

    def _coarse(self) -> gpd.GeoDataFrame:
        with self._lock:
            if self._coarse_countries is None:
                c = self._countries().copy()
                c["geometry"] = c.geometry.simplify(CONTEXT_SIMPLIFY_DEG, preserve_topology=True)
                self._coarse_countries = c
            return self._coarse_countries

    def _countries_touched(self, geom: BaseGeometry, limit: int = 4) -> list[str]:
        """Names of the countries a feature overlaps, largest overlap first (computed on simplified shapes)."""
        coarse = self._coarse()
        g = geom.simplify(CONTEXT_SIMPLIFY_DEG, preserve_topology=True)
        idx = coarse.sindex.query(g, predicate="intersects")
        if not len(idx):
            return []
        sub = coarse.iloc[idx]
        try:
            inter = sub.geometry.intersection(g)
        except Exception:  # noqa: BLE001 - topology problem in the source; give no country context
            return []
        is_poly = g.geom_type in ("Polygon", "MultiPolygon")
        # Sizes only rank the overlaps (degrees are fine for that), so measure the shapes directly.
        sizes = [(part.area if is_poly else part.length) for part in inter]
        ranked = sorted(((float(s), i) for i, s in enumerate(sizes) if s > 0), reverse=True)
        names = []
        for _, i in ranked[:limit]:
            r = sub.iloc[i]
            nm = _nz(r.get("name_en")) or _nz(r.get("name"))
            if nm:
                names.append(nm)
        return names

    def _context(self, e: Entry) -> Context:
        if e.context_pending:
            with self._lock:
                kind = e.context_pending
                if kind:
                    geom = self._geometry_for(e)
                    touched = self._countries_touched(geom, 4) if geom is not None else []
                    if kind == "river":
                        label = ("Flows through " + ", ".join(touched)) if touched else None
                    else:
                        label = ", ".join(touched) or e.fallback_label
                    e.context = Context(
                        country=touched[0] if (kind == "lake" and len(touched) == 1) else None,
                        label=label,
                        source_note="Countries overlapped by the Natural Earth geometry (computed on simplified shapes).",
                    )
                    e.context_pending = None
        return e.context

    def _entries_regions(self) -> None:
        df = self._read("regions")
        self._gdf["regions"] = df
        lang = _lang_cols(df)
        rows, geoms = _records(df)
        for pos, row in enumerate(rows):
            fc = _nz(row.get("featurecla")) or "Geoarea"
            if fc == "Dragons-be-here":
                continue
            raw = _nz(row.get("name_en")) or _nz(row.get("name"))
            if not raw:
                continue
            name = title_case_if_shouting(raw) or raw
            geom = geoms[pos]
            cls = REGION_CLASS.get(fc, "region")
            lat, lon, kind = G.representative_point(geom)
            pending: str | None = None
            note = None
            if cls == "continent":
                eid = f"ne:continent:{fold(name).replace(' ', '-')}"
                ctx = Context(label="Continent (Natural Earth label polygon)", source_note="Natural Earth geography regions")
                note = "Continent outlines follow convention (for example the Europe-Asia boundary), and Natural Earth's label polygon may omit remote islands."
                class_label = CLASS_LABELS["continent"]
            else:
                eid = f"ne:region:{_nz(row.get('ne_id')) or pos}"
                ctx = Context(label=_nz(row.get("region")))
                pending = "region"
                class_label = fc if cls == "region" else CLASS_LABELS[cls]
            e = Entry(
                id=eid,
                layer="regions",
                name=name,
                feature_class=cls,
                class_label=class_label,
                lat=lat,
                lon=lon,
                point_kind=kind,
                context=ctx,
                importance=_clamp(0.85 - 0.1 * (_num(row.get("scalerank")) or 4)),
                fids=[pos],
                bbox=G.geometry_bbox(geom),
                note=note,
                context_pending=pending,
                fallback_label=_nz(row.get("region")),
            )
            self._add(e, _names_from(row, lang + ["name", "namealt"]), [name, _nz(row.get("name")) or ""])

    def _entries_regionpts(self) -> None:
        df = self._read("regionpts", geometry=False)
        lang = _lang_cols(df)
        rows, _ = _records(df)
        for pos, row in enumerate(rows):
            raw = _nz(row.get("name_en")) or _nz(row.get("name"))
            lat, lon = _num(row.get("lat_y")), _num(row.get("long_x"))
            if not raw or lat is None or lon is None:
                continue
            fc = (_nz(row.get("featurecla")) or "feature").lower()
            if fc == "pole":  # Natural Earth stores magnetic poles here; the geographic poles are built in
                continue
            cls = {"island": "island", "island group": "island", "waterfall": "landmark"}.get(fc, "region")
            label = {"waterfall": "Waterfall"}.get(fc, fc.capitalize())
            name = title_case_if_shouting(raw) or raw
            e = Entry(
                id=f"ne:regionpt:{_nz(row.get('ne_id')) or pos}",
                layer="regionpts",
                name=name,
                feature_class=cls,
                class_label=label,
                lat=lat,
                lon=lon,
                point_kind="provider_point",
                context=Context(label=_nz(row.get("region")), source_note="Natural Earth named physical features"),
                importance=_clamp(0.6 - 0.08 * (_num(row.get("scalerank")) or 4)),
                fids=[pos],
                point_note_key="peak",
            )
            self._add(e, _names_from(row, ["name", "name_en", "name_alt"] + lang), [name])

    def _entries_peaks(self) -> None:
        df = self._read("peaks", geometry=False)
        lang = _lang_cols(df)
        rows, _ = _records(df)
        for pos, row in enumerate(rows):
            if (_nz(row.get("featurecla")) or "") != "mountain":
                continue
            raw = _nz(row.get("name_en")) or _nz(row.get("name"))
            lat, lon = _num(row.get("lat_y")), _num(row.get("long_x"))
            if not raw or lat is None or lon is None:
                continue
            elev = _num(row.get("elevation"))
            facts: list[Fact] = []
            if elev is not None:
                facts.append(Fact(key="elevation", label="Elevation (Natural Earth attribute)", value=round(elev), unit="m", source="Natural Earth"))
            nations = [n for n in (_nz(row.get("nation1")), _nz(row.get("nation2"))) if n]
            e = Entry(
                id=f"ne:peak:{_nz(row.get('ne_id')) or pos}",
                layer="peaks",
                name=raw,
                feature_class="mountain_peak",
                class_label=CLASS_LABELS["mountain_peak"],
                lat=lat,
                lon=lon,
                point_kind="provider_point",
                context=Context(country=nations[0] if nations else None, label=", ".join(nations) or _nz(row.get("region")), source_note="Natural Earth named peaks"),
                importance=_clamp(0.7 - 0.1 * (_num(row.get("scalerank")) or 4)),
                fids=[pos],
                facts=facts,
                point_note_key="peak",
            )
            self._add(e, _names_from(row, ["name", "name_en", "name_alt"] + lang), [raw])

    def _entries_lakes(self) -> None:
        df = self._read("lakes")
        self._gdf["lakes"] = df
        lang = _lang_cols(df)
        rows, geoms = _records(df)
        for pos, row in enumerate(rows):
            raw = _nz(row.get("name"))
            if not raw:
                continue
            geom = geoms[pos]
            lat, lon, kind = G.representative_point(geom)
            e = Entry(
                id=f"ne:lake:{_nz(row.get('ne_id')) or pos}",
                layer="lakes",
                name=raw,
                feature_class="lake",
                class_label=CLASS_LABELS["lake"] + (" (reservoir)" if (_nz(row.get("featurecla")) or "").lower() == "reservoir" else ""),
                lat=lat,
                lon=lon,
                point_kind=kind,
                context=Context(label=_nz(row.get("admin"))),
                importance=_clamp(0.75 - 0.1 * (_num(row.get("scalerank")) or 4)),
                fids=[pos],
                bbox=G.geometry_bbox(geom),
                context_pending="lake",
                fallback_label=_nz(row.get("admin")),
            )
            self._add(e, _names_from(row, lang + ["name", "name_en", "name_alt", "name_abb"]), [raw, _nz(row.get("name_en")) or ""])

    def _entries_rivers(self) -> None:
        df = self._read("rivers")
        self._gdf["rivers"] = df
        lang = _lang_cols(df)
        rows, geoms = _records(df)
        groups: dict[tuple[str, str], list[int]] = {}
        for pos, row in enumerate(rows):
            nm = _nz(row.get("name_en")) or _nz(row.get("name"))
            if not nm:
                continue
            groups.setdefault((fold(nm), str(row.get("rivernum"))), []).append(pos)
        # Merge same-named groups whose lines are close together (one river system split over several numbers).
        by_name: dict[str, list[list[int]]] = {}
        for (n, _), poss in groups.items():
            by_name.setdefault(n, []).append(poss)
        for n, glist in by_name.items():
            merged: list[tuple[list[int], BaseGeometry]] = []
            for poss in glist:
                geom = unary_union([geoms[p] for p in poss])
                for k, (ids_k, geom_k) in enumerate(merged):
                    if geom_k.distance(geom) < 0.5:
                        merged[k] = (ids_k + list(poss), unary_union([geom_k, geom]))
                        break
                else:
                    merged.append((list(poss), geom))
            for poss, geom in merged:
                first = rows[poss[0]]
                disp = _nz(first.get("name_en")) or _nz(first.get("name")) or n
                lat, lon, kind = G.representative_point(geom)
                fcs = {(_nz(rows[p].get("featurecla")) or "River") for p in poss}
                label = "Canal" if fcs == {"Canal"} else CLASS_LABELS["river"]
                names: set[str] = set()
                for p in poss:
                    names |= _names_from(rows[p], lang + ["name", "name_en", "name_alt"])
                ne_ids = [_num(rows[p].get("ne_id")) for p in poss]
                key = int(min(x for x in ne_ids if x)) if any(ne_ids) else min(poss)
                e = Entry(
                    id=f"ne:river:{key}",
                    layer="rivers",
                    name=disp,
                    feature_class="river",
                    class_label=label,
                    lat=lat,
                    lon=lon,
                    point_kind=kind,
                    context=Context(),
                    importance=_clamp(0.8 - 0.1 * (_num(first.get("scalerank")) or 5)),
                    fids=sorted(poss),
                    bbox=G.geometry_bbox(geom),
                    context_pending="river",
                )
                self._add(e, names, [disp, _nz(first.get("name")) or ""])

    def _entries_builtin(self) -> None:
        for key, label, lat in (("north", "North Pole", 90.0), ("south", "South Pole", -90.0)):
            e = Entry(
                id=f"builtin:geographic-{key}-pole",
                layer="builtin",
                name=f"Geographic {label}",
                feature_class="other",
                class_label="Geographic pole",
                lat=lat,
                lon=0.0,
                point_kind="provider_point",
                context=Context(label=f"Defined as {abs(lat):.0f}° {'N' if lat > 0 else 'S'} latitude"),
                importance=0.8,
                point_note_key="builtin",
            )
            self._add(e, {fold(label), fold(f"geographic {label}"), fold(f"the {label}")}, [f"Geographic {label}", label])

    # ----------------------------------------------------------------------------- search
    def search(self, query: str, limit: int = 8, classes: set[str] | None = None, exact_if_any: bool = False) -> list[Candidate]:
        """Find features by name. ``'Paris, France'`` treats the part after the comma as context.

        ``exact_if_any`` keeps only exact-name matches when there are any (used when resolving, so that
        "Georgia" offers the country and the state, not every place with "Georgia" in its name).
        """
        self._ensure()
        parts = [p.strip() for p in query.split(",") if p.strip()]
        if not parts:
            return []
        q = fold(parts[0])
        quals = [fold(p) for p in parts[1:] if fold(p)]
        if not q:
            return []
        scores: dict[str, float] = {}

        def bump(eid: str, s: float) -> None:
            if s > scores.get(eid, 0.0):
                scores[eid] = s

        for eid in self._exact.get(q, ()):
            bump(eid, 1.0)
        has_exact = bool(scores)
        if not (exact_if_any and has_exact):
            if len(q) >= 2:
                lo = bisect.bisect_left(self._prefix, (q, ""))
                n = 0
                while lo < len(self._prefix) and self._prefix[lo][0].startswith(q) and n < 400:
                    bump(self._prefix[lo][1], 0.7)
                    lo += 1
                    n += 1
            if len(q) >= 3:
                word = " " + q
                for nm, eid in self._primary:
                    if word in " " + nm:
                        bump(eid, 0.5)
                    elif q in nm and len(q) >= 4:
                        bump(eid, 0.3)

        out: list[tuple[float, float, Entry]] = []
        for eid, s in scores.items():
            e = self.entries[eid]
            if classes and e.feature_class not in classes:
                continue
            if quals and not self._matches_context(e, quals):
                continue
            out.append((s, e.importance, e))
        out.sort(key=lambda t: (-t[0], -t[1], t[2].name))
        return [self.to_candidate(e) for _, _, e in out[:limit]]

    def _matches_context(self, e: Entry, quals: list[str]) -> bool:
        c = self._context(e)
        hay = " ".join(fold(x) for x in (c.country, c.admin1, c.admin2, c.label, c.country_code) if x)
        hay_words = set(hay.split())
        return all(q in hay or q in hay_words for q in quals)

    def to_candidate(self, e: Entry) -> Candidate:
        ctx = self._context(e)
        display = _display_name(e, ctx)
        note = e.note
        if e.point_note_key == "peak" and not note:
            note = POINT_NOTES["peak"]
        return Candidate(
            id=e.id,
            name=e.name,
            display_name=display,
            feature_class=e.feature_class,  # type: ignore[arg-type]
            class_label=e.class_label,
            shape_hint=SHAPE_BY_CLASS.get(e.feature_class, "point"),
            context=ctx,
            latitude=e.lat,
            longitude=e.lon,
            position_kind=e.point_kind,  # type: ignore[arg-type]
            provider="builtin" if e.layer == "builtin" else "natural_earth",
            provider_name="Definition (geodesy)" if e.layer == "builtin" else "Natural Earth",
            provider_importance=round(e.importance, 3),
            bbox=e.bbox,
            note=note,
        )

    # ---------------------------------------------------------------------------- geometry
    def _geometry_for(self, e: Entry) -> BaseGeometry | None:
        if e.layer == "countries":
            return self._countries().geometry.iloc[e.fids[0]]
        if e.layer == "admin1":
            df = self._read("admin1", fids=[e.fids[0]])
            return df.geometry.iloc[0] if len(df) else None
        if e.layer in ("marine", "regions", "lakes", "rivers"):
            gdf = self._gdf[e.layer]
            geoms = [gdf.geometry.iloc[p] for p in e.fids]
            return geoms[0] if len(geoms) == 1 else unary_union(geoms)
        return None  # point layers

    def get(self, location_id: str) -> ResolvedLocation:
        self._ensure()
        e = self.entries.get(location_id)
        if e is None:
            raise AppError(404, "location_not_found", f"No reference-atlas feature has the id '{location_id}'.")
        return self.to_resolved(e)

    def to_resolved(self, e: Entry) -> ResolvedLocation:
        geom = self._geometry_for(e)
        ctx = self._context(e)
        scale = SCALE_LABEL.get(e.dataset_scale, e.dataset_scale)
        bbox = e.bbox
        out_geom: dict[str, Any] | None = None
        checks = ["latitude and longitude are within WGS84 limits"]
        limitations: list[str] = []
        if e.layer == "builtin":
            gi = GeometryInfo(available=False, type=None, quality="not_applicable", note="A pole is a single defined point.")
            gtype = "Point"
            bbox = BBox(west=e.lon, south=e.lat, east=e.lon, north=e.lat)
            limitations.append(POINT_NOTES["builtin"])
            src = SourceInfo(
                provider="builtin",
                provider_name="Definition (geodesy)",
                dataset=None,
                source_id=e.id,
                license="Not applicable",
                attribution="The geographic poles are the points at 90° N and 90° S latitude by definition.",
                url=None,
            )
            return ResolvedLocation(
                id=e.id,
                name=e.name,
                display_name=e.name,
                feature_class="other",
                class_label=e.class_label,
                geometry_type="Point",
                context=ctx,
                point=PointInfo(latitude=e.lat, longitude=e.lon, kind="provider_point", note=POINT_NOTES["builtin"]),
                bbox=bbox,
                geometry=None,
                geometry_info=gi,
                source=src,
                validation=Validation(status="validated", checks=checks + ["latitude is the defined value for the pole"], limitations=limitations),
                facts=[],
            )
        limitations.append("Natural Earth is a cartographic dataset: positions and outlines are generalized and are not survey-grade or legal boundaries.")
        if geom is None:
            gtype = "Point"
            gi = GeometryInfo(available=False, type=None, quality="not_applicable", note="This feature is a point in the source; there is no area or line geometry.")
        else:
            geom = G.ensure_valid(geom)
            checks.append("geometry is valid (OGC simple features)")
            budget = MAX_LINE_VERTICES if geom.geom_type in ("LineString", "MultiLineString") else MAX_AREA_VERTICES
            simplified, tol = G.simplify_to_budget(geom, budget)
            gtype = simplified.geom_type
            out_geom = G.to_geojson(simplified)
            bbox = G.geometry_bbox(geom)
            area = G.geodesic_area_km2(geom)
            length = G.geodesic_length_km(geom)
            gen = f"Natural Earth {scale} cartographic generalization" + (f", further simplified to about {tol:g}° tolerance to limit size" if tol else "")
            note = "Area is not reported because the polygon touches a pole." if area is None and gtype in ("Polygon", "MultiPolygon") else None
            gi = GeometryInfo(
                available=True,
                type=gtype,  # type: ignore[arg-type]
                quality="generalized",
                generalization=gen,
                simplify_tolerance_deg=tol,
                vertex_count=G.vertex_count(simplified),
                crosses_antimeridian=bbox.crosses_antimeridian,
                area_km2=round(area, 1) if area is not None else None,
                length_km=round(length, 1) if length is not None else None,
                note=note,
            )
            limitations.append("Outlines of disputed areas follow Natural Earth's own convention.")
        if bbox is None:
            bbox = BBox(west=e.lon, south=e.lat, east=e.lon, north=e.lat)
        note_key = e.point_note_key or (e.point_kind if e.point_kind in POINT_NOTES else None)
        if e.layer == "regionpts" and e.feature_class not in ("island", "region"):
            point_note = "Position stored in Natural Earth for this named feature (cartographic accuracy)."
        else:
            point_note = POINT_NOTES.get(note_key or "", POINT_NOTES["label_point"])
        if e.note:
            limitations.append(e.note)
        src = SourceInfo(
            provider="natural_earth",
            provider_name="Natural Earth",
            dataset=LAYER_DIRS[e.layer],
            source_id=e.id.split(":", 2)[-1],
            scale=scale,
            license="Public domain",
            attribution="Made with Natural Earth.",
            url=SOURCE_URL,
        )
        return ResolvedLocation(
            id=e.id,
            name=e.name,
            display_name=_display_name(e, ctx),
            feature_class=e.feature_class,  # type: ignore[arg-type]
            class_label=e.class_label,
            geometry_type=gtype if out_geom else "Point",  # type: ignore[arg-type]
            context=ctx,
            point=PointInfo(latitude=e.lat, longitude=e.lon, kind=e.point_kind, note=point_note),  # type: ignore[arg-type]
            bbox=bbox,
            geometry=out_geom,
            geometry_info=gi,
            source=src,
            validation=Validation(status="validated_with_limits", checks=checks, limitations=limitations),
            facts=list(e.facts),
            also_matched=[],
        )

    # --------------------------------------------------------------------------- context
    def _admin1_geoms(self) -> gpd.GeoDataFrame:
        with self._lock:
            if self._admin1_full is None:
                self._admin1_full = self._read("admin1")
            return self._admin1_full

    def locate(self, lat: float, lon: float) -> Context:
        """Country / state / sea containing a point, by point-in-polygon against Natural Earth (offline)."""
        self._ensure()
        pt = Point(lon, lat)
        countries = self._countries()
        idx = countries.sindex.query(pt, predicate="within")
        ctx = Context(source_note="Derived from Natural Earth polygons by containment; near coasts and borders the result can be wrong.")
        if len(idx):
            row = countries.iloc[int(idx[0])]
            ctx.country = _nz(row.get("name_en")) or _nz(row.get("name"))
            iso2 = _nz(row.get("iso_a2"))
            ctx.country_code = iso2 if iso2 and iso2 != "-99" else None
            a1 = self._admin1_geoms()
            j = a1.sindex.query(pt, predicate="within")
            if len(j):
                ctx.admin1 = _nz(a1.iloc[int(j[0])].get("name_en")) or _nz(a1.iloc[int(j[0])].get("name"))
            ctx.label = ", ".join(x for x in (ctx.admin1, ctx.country) if x) or None
            return ctx
        marine = self._gdf.get("marine")
        if marine is not None:
            j = marine.sindex.query(pt, predicate="within")
            if len(j):
                best = min((marine.iloc[int(i)] for i in j), key=lambda r: r.geometry.area)
                ctx.label = title_case_if_shouting(_nz(best.get("name"))) or ctx.label
        return ctx

    # ---------------------------------------------------------------------- boundary layers
    def feature_collection(self, layer: str, ids: list[str] | None, simplify: float = 0.0) -> dict[str, Any]:
        """GeoJSON FeatureCollection of Natural Earth geometry (all countries, or selected ids)."""
        self._ensure()
        features: list[dict[str, Any]] = []
        if ids is None:
            if layer != "countries":
                raise AppError(400, "ids_required", f"Layer '{layer}' is large; request specific features with ids=.")
            df = self._countries()
            rows, geoms = _records(df)
            for pos, row in enumerate(rows):
                geom = geoms[pos]
                if simplify > 0:
                    geom = geom.simplify(simplify, preserve_topology=True)
                if geom.is_empty:
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "id": f"ne:admin0:{_nz(row.get('adm0_a3')) or pos}",
                        "properties": {"name": _nz(row.get("name_en")) or _nz(row.get("name")), "iso_a3": _nz(row.get("adm0_a3")), "continent": _nz(row.get("continent"))},
                        "geometry": G.to_geojson(geom, 3 if simplify >= 0.05 else 4),
                    }
                )
        else:
            for loc_id in ids:
                loc = self.get(loc_id)
                if loc.geometry is None:
                    continue
                features.append({"type": "Feature", "id": loc.id, "properties": {"name": loc.name, "class": loc.feature_class}, "geometry": loc.geometry})
        return {"type": "FeatureCollection", "features": features}

    def status(self) -> dict[str, Any]:
        layers = {k: self._layer_path(k) is not None for k in LAYER_DIRS}
        if not self.manifest and (self.dir / "manifest.json").is_file():
            try:
                self.manifest = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))
            except ValueError:
                self.manifest = {}
        retrieved = {k: v.get("retrieved_at") for k, v in (self.manifest.get("layers") or {}).items()}
        return {
            "available": self.available,
            "indexed": self._ready,
            "features": len(self.entries) if self._ready else None,
            "layers_installed": layers,
            "retrieved_at": retrieved,
            "error": self._failed,
        }
