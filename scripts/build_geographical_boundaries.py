"""Build the GeoJSON gazetteer used for place recognition and boundary display.

Real boundaries come only from data that was actually downloaded:
  * states and districts   geoBoundaries gbOpen India ADM1 / ADM2 (simplified), ODbL
  * water-body outlines    derived from the downloaded JRC Global Surface Water occurrence tiles (>= 50 % occurrence)
  * Indian Sundarbans      mangrove class of the downloaded ESA WorldCover 2021 tile, clipped to West Bengal
Everything else (cities, localities, landmarks, some features) is a reference point or a rough box that is marked
``approximate_point`` or ``approximate_bbox``. Those are NOT boundaries and the app says so.

Run:  python scripts/build_geographical_boundaries.py
"""

from __future__ import annotations

import json
import math
import sys
import unicodedata
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.windows import from_bounds
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atlas_common import ATLAS, now_iso  # noqa: E402


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


GB = ATLAS / "geographical_boundaries"
ORIG = GB / "originals"
ROOT = ATLAS.parent.parent
LICENSE_GB = "ODbL 1.0 (geoBoundaries gbOpen); attribution to geoBoundaries required"


def ascii_name(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def rnd(geom, nd: int = 4):
    def r(c):
        return [round(v, nd) for v in c] if isinstance(c[0], (int, float)) else [r(x) for x in c]
    m = mapping(geom)
    out = {"type": m["type"], "coordinates": r(m["coordinates"])}
    # Rounding coordinates can make a thin polygon touch itself; repair it so every stored outline is valid.
    if out["type"] in ("Polygon", "MultiPolygon") and not shape(out).is_valid:
        fixed = shape(out).buffer(0)
        mm = mapping(fixed)
        out = {"type": mm["type"], "coordinates": mm["coordinates"]}
    return out


def fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def feat(geom: dict | None, props: dict) -> dict:
    return {"type": "Feature", "geometry": geom, "properties": props}


STATE_ALIASES = {"Odisha": ["orissa"], "Uttarakhand": ["uttaranchal"], "Delhi": ["nct of delhi", "new delhi state"], "Tamil Nadu": ["tamilnadu"], "Telangana": [], "Karnataka": ["mysore state"], "West Bengal": ["paschimbanga", "bengal"]}


def build_admin() -> tuple[dict, dict, list, list]:
    a1 = json.loads((ORIG / "geoBoundaries-IND-ADM1_simplified.geojson").read_text(encoding="utf-8"))
    a2 = json.loads((ORIG / "geoBoundaries-IND-ADM2_simplified.geojson").read_text(encoding="utf-8"))
    states, sgeoms = [], []
    for f in a1["features"]:
        g = shape(f["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        name = ascii_name(f["properties"]["shapeName"])
        sid = "state:" + name.lower().replace(" ", "-")
        sgeoms.append((name, sid, g))
        states.append(feat(rnd(g), {
            "id": sid, "name": name, "level": "state", "hierarchy": ["India"], "aliases": STATE_ALIASES.get(name, []), "iso": f["properties"].get("shapeISO"), "boundary_status": "authoritative_simplified",
            "boundary_note": "geoBoundaries simplified administrative boundary; not an official survey line.", "source": "geoBoundaries gbOpen IND ADM1", "source_id": "geoboundaries_IND_ADM1", "license": LICENSE_GB,
            "bbox": [round(v, 5) for v in g.bounds], "lat": round(g.representative_point().y, 5), "lon": round(g.representative_point().x, 5),
        }))
    tree = STRtree([g for _, _, g in sgeoms])
    districts, dgeoms = [], []
    for f in a2["features"]:
        g = shape(f["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        rp = g.representative_point()
        parent = None
        for i in tree.query(rp):
            if sgeoms[i][2].contains(rp):
                parent = sgeoms[i][0]
                break
        name = ascii_name(f["properties"]["shapeName"])
        did = f"district:{(parent or 'india').lower().replace(' ', '-')}:{name.lower().replace(' ', '-')}:{f['properties']['shapeID'][-6:]}"
        dgeoms.append((name, did, parent, g))
        districts.append(feat(rnd(g), {
            "id": did, "name": name, "level": "district", "hierarchy": ["India"] + ([parent] if parent else []), "aliases": [], "boundary_status": "authoritative_simplified",
            "boundary_note": "geoBoundaries simplified administrative boundary; not an official survey line.", "source": "geoBoundaries gbOpen IND ADM2", "source_id": "geoboundaries_IND_ADM2", "license": LICENSE_GB,
            "bbox": [round(v, 5) for v in g.bounds], "lat": round(rp.y, 5), "lon": round(rp.x, 5),
        }))
    return fc(states), fc(districts), sgeoms, dgeoms


def find_district(dgeoms, lon: float, lat: float):
    p = Point(lon, lat)
    for name, did, parent, g in dgeoms:
        if g.contains(p):
            return name, did, parent
    return None, None, None


def find_state(sgeoms, lon: float, lat: float) -> str | None:
    p = Point(lon, lat)
    for name, sid, g in sgeoms:
        if g.contains(p):
            return name
    return None


# (name, lat, lon, aliases, radius_km) approximate reference points
CITIES = [
    ("Hyderabad", 17.3850, 78.4867, ["hyderabad india", "greater hyderabad"], 14), ("Secunderabad", 17.4399, 78.4983, [], 6), ("Bengaluru", 12.9716, 77.5946, ["bangalore", "bengaluru india", "bangalore india"], 16),
    ("Mumbai", 19.0760, 72.8777, ["bombay"], 14), ("Delhi", 28.6139, 77.2090, ["new delhi", "delhi india"], 16), ("Kolkata", 22.5726, 88.3639, ["calcutta"], 12), ("Chennai", 13.0827, 80.2707, ["madras"], 12),
    ("Pune", 18.5204, 73.8567, [], 10), ("Ahmedabad", 23.0225, 72.5714, [], 10), ("Jaipur", 26.9124, 75.7873, [], 9), ("Lucknow", 26.8467, 80.9462, [], 9), ("Kochi", 9.9312, 76.2673, ["cochin"], 8),
    ("Visakhapatnam", 17.6868, 83.2185, ["vizag", "visakhapatnam india"], 9), ("Dehradun", 30.3165, 78.0322, [], 7), ("Joshimath", 30.5553, 79.5644, [], 3), ("Haridwar", 29.9457, 78.1642, [], 5),
    ("Rishikesh", 30.0869, 78.2676, [], 4), ("Guwahati", 26.1445, 91.7362, [], 8), ("Bhubaneswar", 20.2961, 85.8245, [], 8), ("Patna", 25.5941, 85.1376, [], 8), ("Gosaba", 22.1630, 88.8000, [], 4), ("Canning", 22.3164, 88.6667, [], 3),
]
LOCALITIES = [  # (name, parent city, lat, lon, aliases)
    ("Gachibowli", "Hyderabad", 17.4401, 78.3489, []), ("HITEC City", "Hyderabad", 17.4435, 78.3772, ["hitech city"]), ("Madhapur", "Hyderabad", 17.4483, 78.3915, []), ("Kukatpally", "Hyderabad", 17.4849, 78.4138, ["kphb"]),
    ("Banjara Hills", "Hyderabad", 17.4126, 78.4482, []), ("Uppal", "Hyderabad", 17.4018, 78.5594, []), ("Begumpet", "Hyderabad", 17.4440, 78.4680, []), ("Bellandur", "Bengaluru", 12.9260, 77.6762, ["bellandur bangalore", "bellandur bengaluru"]),
    ("Whitefield", "Bengaluru", 12.9698, 77.7500, []), ("Koramangala", "Bengaluru", 12.9352, 77.6245, []), ("HSR Layout", "Bengaluru", 12.9116, 77.6389, []), ("Indiranagar", "Bengaluru", 12.9784, 77.6408, []),
    ("Andheri", "Mumbai", 19.1136, 72.8697, []), ("Bandra", "Mumbai", 19.0596, 72.8295, []),
]
LANDMARKS = [  # (name, parent, lat, lon, aliases)
    ("Charminar", "Hyderabad", 17.3616, 78.4747, ["char minar"]), ("Golconda Fort", "Hyderabad", 17.3833, 78.4011, ["golkonda"]), ("Lalbagh Botanical Garden", "Bengaluru", 12.9507, 77.5848, ["lalbagh"]),
    ("Gateway of India", "Mumbai", 18.9220, 72.8347, []), ("India Gate", "Delhi", 28.6129, 77.2295, []), ("Taj Mahal", "Agra", 27.1751, 78.0421, []), ("Hawa Mahal", "Jaipur", 26.9239, 75.8267, []),
]
# name, level, lat, lon, aliases, state, bbox or None, radius_km
FEATURES_POINTS = [
    ("Chilika Lake", "lake", 19.72, 85.32, ["chilika", "chilka lake"], "Odisha", [85.05, 19.45, 85.65, 19.95]), ("Sagar Island", "island", 21.65, 88.08, ["ganga sagar", "sagar island west bengal"], "West Bengal", [88.0, 21.55, 88.15, 21.82]),
    ("Gangotri Glacier", "glacier", 30.9333, 79.0833, ["gangotri"], "Uttarakhand", [79.0, 30.85, 79.2, 31.0]), ("Himalayas", "mountain", 30.75, 79.825, ["the himalayas", "himalaya", "himalayan range"], "Uttarakhand", [72.5, 26.5, 97.5, 37.0]),
    ("Dhauliganga catchment", "river", 30.75, 79.825, ["dhauliganga", "dhauliganga valley", "dhauli ganga"], "Uttarakhand", [79.60, 30.55, 80.05, 30.95]),
    ("Bay of Bengal coast, Sundarbans", "coast", 21.75, 88.90, ["sundarbans coast"], "West Bengal", [88.6, 21.55, 89.1, 22.05]),
]


def derive_water(occ_path: Path, lon: float, lat: float, search: float = 0.05):
    with rasterio.open(occ_path) as s:
        win = from_bounds(lon - search, lat - search, lon + search, lat + search, s.transform).round_offsets().round_lengths()
        arr = s.read(1, window=win)
        tr = s.window_transform(win)
    from scipy import ndimage as ndi
    best = None
    for thr in (10,):
        m = (arr >= thr) & (arr <= 100)
        m = ndi.binary_closing(m, iterations=2)
        lab, n = ndi.label(m)
        if n == 0:
            continue
        r, c = int((tr.f - lat) / abs(tr.e)), int((lon - tr.c) / tr.a)
        r, c = min(max(r, 0), arr.shape[0] - 1), min(max(c, 0), arr.shape[1] - 1)
        k = lab[r, c]
        if k == 0:
            dist = ndi.distance_transform_edt(lab == 0, return_indices=True)
            ii = dist[1][:, r, c]
            k = lab[ii[0], ii[1]]
        comp = lab == k
        if comp.sum() < 120:
            continue
        polys = [shape(g) for g, v in shapes(comp.astype(np.uint8), mask=comp, transform=tr) if v == 1]
        geom = unary_union(polys).simplify(0.0002)
        best = (geom, thr, int(comp.sum()))
        break
    return best


def derive_mangrove(sgeoms) -> tuple | None:
    wc = ATLAS / "official/sundarbans/originals/ESA_WorldCover_10m_2021_v200_N21E087_Map.tif"
    if not wc.exists():
        return None
    bbox = (88.0, 21.45, 89.3, 22.35)
    with rasterio.open(wc) as s:
        win = from_bounds(*bbox, transform=s.transform).round_offsets().round_lengths()
        f = 3
        win = rasterio.windows.Window(win.col_off, win.row_off, (win.width // f) * f, (win.height // f) * f)
        arr = s.read(1, window=win, out_shape=(int(win.height // f), int(win.width // f)), resampling=rasterio.enums.Resampling.mode)
        tr = s.window_transform(win) * s.window_transform(win).scale(f, f) if False else s.window_transform(win)
        tr = tr * tr.scale(f, f)
    from scipy import ndimage as ndi
    m = ndi.binary_closing(arr == 95, iterations=3)
    m = ndi.binary_opening(m, iterations=1)
    lab, n = ndi.label(m)
    sizes = ndi.sum(m, lab, range(1, n + 1))
    keep = np.isin(lab, [i + 1 for i, v in enumerate(sizes) if v >= 400])
    polys = [shape(g) for g, v in shapes(keep.astype(np.uint8), mask=keep, transform=tr) if v == 1]
    geom = unary_union(polys).simplify(0.0008)
    wb = next(g for nme, sid, g in sgeoms if nme == "West Bengal")
    clipped = geom.intersection(wb)
    return clipped, float(keep.sum())


def circle(lon: float, lat: float, km: float):
    return Point(lon, lat).buffer(km / (111.32 * math.cos(math.radians(lat))) * 1.0, 24).simplify(0.001) if False else _ellipse(lon, lat, km)


def _ellipse(lon: float, lat: float, km: float):
    pts = [(lon + (km / (111.32 * math.cos(math.radians(lat)))) * math.cos(t), lat + (km / 110.57) * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 49)]
    from shapely.geometry import Polygon
    return Polygon(pts)


def main() -> None:
    states, districts, sgeoms, dgeoms = build_admin()
    (GB / "states").mkdir(parents=True, exist_ok=True)
    (GB / "districts").mkdir(parents=True, exist_ok=True)
    write_json(GB / "states" / "india_states.geojson", states)
    write_json(GB / "districts" / "india_districts.geojson", districts)
    india = unary_union([g for _, _, g in sgeoms]).simplify(0.01)
    write_json(GB / "countries" / "india.geojson", fc([feat(rnd(india, 3), {
        "id": "country:india", "name": "India", "level": "country", "hierarchy": [], "aliases": ["republic of india", "bharat"], "boundary_status": "derived_from_official_data",
        "boundary_note": "Dissolved from the geoBoundaries ADM1 units (simplified); not an official boundary.", "source": "geoBoundaries gbOpen IND ADM1", "license": LICENSE_GB, "bbox": [round(v, 4) for v in india.bounds], "lat": 22.5, "lon": 79.0})]))

    cities = []
    for name, lat, lon, aliases, rad in CITIES:
        st = find_state(sgeoms, lon, lat)
        dname, did, _ = find_district(dgeoms, lon, lat)
        cities.append(feat({"type": "Point", "coordinates": [lon, lat]}, {
            "id": f"city:{name.lower().replace(' ', '-')}", "name": name, "level": "city", "hierarchy": ["India"] + ([st] if st else []), "aliases": aliases, "lat": lat, "lon": lon,
            "boundary_status": "administrative_proxy" if did else "approximate_point", "boundary_ref": did, "approx_radius_km": rad,
            "boundary_note": ("No city-limit polygon was downloaded. The outline shown is the containing district (an administrative proxy)." if did else "Reference point only; the circle is an approximate area."),
            "source": "reference point (approximate), district from geoBoundaries ADM2", "license": "reference coordinates; district boundary ODbL (geoBoundaries)", "bbox": [round(lon - rad / 100, 4), round(lat - rad / 110, 4), round(lon + rad / 100, 4), round(lat + rad / 110, 4)]}))
    write_json(GB / "cities" / "cities.geojson", fc(cities))
    st_of = {c["properties"]["name"]: c["properties"]["hierarchy"] for c in cities}
    locs = []
    for name, parent, lat, lon, aliases in LOCALITIES:
        locs.append(feat({"type": "Point", "coordinates": [lon, lat]}, {
            "id": f"locality:{name.lower().replace(' ', '-')}", "name": name, "level": "locality", "hierarchy": st_of.get(parent, ["India"]) + ([parent] if parent not in st_of.get(parent, []) else []), "aliases": aliases, "lat": lat, "lon": lon,
            "boundary_status": "approximate_point", "approx_radius_km": 2.0, "boundary_note": "Reference point only. The circle is an approximate area, not an authoritative boundary.", "source": "reference point (approximate)", "license": "reference coordinates",
            "bbox": [round(lon - 0.02, 4), round(lat - 0.018, 4), round(lon + 0.02, 4), round(lat + 0.018, 4)]}))
    for name, parent, lat, lon, aliases in LANDMARKS:
        locs.append(feat({"type": "Point", "coordinates": [lon, lat]}, {
            "id": f"landmark:{name.lower().replace(' ', '-')}", "name": name, "level": "landmark", "hierarchy": st_of.get(parent, ["India"]) + ([parent] if parent not in st_of.get(parent, []) else []), "aliases": aliases, "lat": lat, "lon": lon,
            "boundary_status": "approximate_point", "approx_radius_km": 0.4, "boundary_note": "Reference point only. The circle is an approximate area, not an authoritative boundary.", "source": "reference point (approximate)", "license": "reference coordinates",
            "bbox": [round(lon - 0.006, 5), round(lat - 0.005, 5), round(lon + 0.006, 5), round(lat + 0.005, 5)]}))
    (GB / "localities").mkdir(parents=True, exist_ok=True)
    write_json(GB / "localities" / "localities.geojson", fc(locs))

    feats = []
    occ70 = ATLAS / "official/bengaluru/originals/occurrence_70E_20Nv1_4_2021.tif"
    for name, lon, lat, aliases, state, parent in (
        ("Bellandur Lake", 77.6720, 12.9352, ["bellandur", "bellandur tank", "bellandur lake bengaluru", "bellandur lake bangalore"], "Karnataka", "Bengaluru"),
        ("Hussain Sagar", 78.4738, 17.4239, ["hussain sagar lake", "hussainsagar", "tank bund lake"], "Telangana", "Hyderabad"),
        ("Osman Sagar", 78.3004, 17.3858, ["gandipet", "osman sagar lake"], "Telangana", "Hyderabad"),
        ("Himayat Sagar", 78.3900, 17.3200, ["himayatsagar", "himayat sagar lake"], "Telangana", "Hyderabad"),
    ):
        res = derive_water(occ70, lon, lat) if occ70.exists() else None
        base = {"id": f"lake:{name.lower().replace(' ', '-')}", "name": name, "level": "lake", "hierarchy": ["India", state, parent], "aliases": aliases, "lat": lat, "lon": lon, "license": "Free and open (JRC); reference point approximate"}
        if res:
            geom, thr, npx = res
            b = geom.bounds
            feats.append(feat(rnd(geom), {**base, "boundary_status": "derived_from_official_data", "boundary_note": f"Outline derived from the downloaded JRC Global Surface Water occurrence tile (pixels where water was detected in at least {thr}% of valid observations, 1984-2021). It is not a surveyed boundary and can understate lakes whose surface is often covered by vegetation or froth.",
                                         "source": "JRC Global Surface Water v1.4 (occurrence), downloaded", "source_id": "jrc_gsw_occurrence_70E_20N", "bbox": [round(v, 5) for v in b], "derived_pixels": npx}))
        else:
            feats.append(feat({"type": "Point", "coordinates": [lon, lat]}, {**base, "boundary_status": "approximate_point", "approx_radius_km": 1.5, "boundary_note": "Reference point only.", "source": "reference point (approximate)", "bbox": [lon - 0.03, lat - 0.025, lon + 0.03, lat + 0.025]}))
    mg = derive_mangrove(sgeoms)
    if mg:
        geom, npx = mg
        feats.append(feat(rnd(geom), {"id": "forest:sundarbans", "name": "Sundarbans", "level": "forest", "hierarchy": ["India", "West Bengal"], "aliases": ["the sundarbans", "sunderbans", "sundarban", "indian sundarbans", "sundarbans national park", "sundarbans biosphere reserve"],
                                      "lat": 21.80, "lon": 88.85, "boundary_status": "derived_from_official_data",
                                      "boundary_note": "Mangrove extent in West Bengal from the downloaded ESA WorldCover 2021 map (class 95), clipped to the West Bengal boundary. It is not the legal reserve boundary.", "source": "ESA WorldCover 10 m 2021 v200 (downloaded) and geoBoundaries ADM1",
                                      "source_id": "esa_worldcover_2021_N21E087", "license": "CC BY 4.0 (ESA WorldCover); ODbL (geoBoundaries)", "bbox": [round(v, 5) for v in geom.bounds]}))
    for name, level, lat, lon, aliases, state, bb in FEATURES_POINTS:
        status = "analysis_window" if name.startswith(("Dhauliganga", "Bay of Bengal")) else "approximate_bbox"
        geom = box(*bb)
        feats.append(feat(rnd(geom, 5), {"id": f"{level}:{name.lower().replace(' ', '-').replace(',', '')}", "name": name, "level": level, "hierarchy": ["India", state], "aliases": aliases, "lat": lat, "lon": lon, "boundary_status": status,
                                          "boundary_note": ("The rectangle is the analysis window used for the atlas data, not a catchment or coastline boundary." if status == "analysis_window" else "A rough bounding box for orientation. It is not an authoritative boundary."),
                                          "source": "reference extent (approximate)", "license": "reference coordinates", "bbox": list(bb)}))
    (GB / "geographical_features").mkdir(parents=True, exist_ok=True)
    write_json(GB / "geographical_features" / "features.geojson", fc(feats))
    index = {"generated_at": now_iso(), "files": {"countries": 1, "states": len(states["features"]), "districts": len(districts["features"]), "cities": len(cities), "localities": len(locs), "geographical_features": len(feats)},
             "status_counts": {}, "notes": "boundary_status: authoritative_simplified (geoBoundaries), derived_from_official_data, administrative_proxy, analysis_window, approximate_bbox, approximate_point."}
    for f in cities + locs + feats + states["features"] + districts["features"]:
        s = f["properties"]["boundary_status"]
        index["status_counts"][s] = index["status_counts"].get(s, 0) + 1
    write_json(GB / "index.json", index)
    print(json.dumps(index, indent=1))
    for f in feats:
        p = f["properties"]
        print(p["name"], p["boundary_status"], p.get("derived_pixels", ""))


if __name__ == "__main__":
    main()
