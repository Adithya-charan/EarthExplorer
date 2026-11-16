"""Build the Deep-Time datasets from the original scientific sources (pygplates + EarthByte/PALEOMAP/PBDB/Macrostrat/ICS).

Input : DEEPTIME_ROOT/originals (see fetch_deeptime_sources.py)
Output: DEEPTIME_ROOT/out/*.json|csv (staging) and datasets/deep_time/ (runtime data read by the backend)

Everything numeric is computed from the source files. Nothing is interpolated between time slices: each frame is a direct
evaluation of the rotation model (which itself interpolates between its finite-rotation poles, flagged per frame).
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pygplates
import shapely
from PIL import Image
from shapely.geometry import MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
from app.explorer.deeptime_knowledge import BIBLIOGRAPHY, EVENTS, EXTRA_POINTS, EURASIA_POINT, HIMALAYA_STAGES, REFERENCE_PLACES  # noqa: E402

ROOT = Path(os.environ.get("DEEPTIME_ROOT", "F:/NASAX_DEEPTIME"))
ORIG = ROOT / "originals"
OUT = ROOT / "out"
RUNTIME = REPO / "datasets" / "deep_time"
ATLAS = REPO / "datasets" / "india_historical_atlas"
GEO = ORIG / "GPLATES/extracted/GeoData/FeatureCollections"
SCO = ORIG / "EARTHBYTE/extracted/Scotese PaleoAtlas_v3"

REQUESTED = [0, 0.001, 0.01, 0.1, 1, 5, 10, 20, 30, 40, 50, 55, 66, 75, 90, 100, 120, 140, 150, 180, 200, 230, 250]
EXTRA = [60, 70, 80, 110, 130, 160, 170, 190, 210, 220, 240]
AGES = sorted(set(REQUESTED + EXTRA))
EB, PM = "earthbyte", "paleomap"
EB_NAME = "EarthByte / Zahirovic et al. (2022) rotation model, anchor plate 0 (optimised mantle frame)"
PM_NAME = "PALEOMAP Global Plate Model (Scotese 2016), anchor plate 0"
WRAP = pygplates.DateLineWrapper()


def akey(a: float) -> str:
    return f"{a:g}".replace(".", "p")


# ------------------------------------------------------------------------------------------------ time scale
def load_timescale() -> dict:
    ts = {}
    for k in ("eras", "periods", "epochs", "ages"):
        d = json.loads((ORIG / "MACROSTRAT" / f"macrostrat_intervals_{k}.json").read_text(encoding="utf-8"))["success"]["data"]
        ts[k] = [{"name": x["name"], "t_age": x["t_age"], "b_age": x["b_age"], "color": x.get("color")} for x in d if x["b_age"] <= 700]
    return ts


def interval(ts: list[dict], age: float) -> str:
    for x in ts:
        if x["t_age"] <= age < x["b_age"]:
            return x["name"]
    return ts[-1]["name"] if age >= ts[-1]["b_age"] else ts[0]["name"]


def boundary(ts: dict, age: float) -> str:
    """Name a formal ICS boundary when the age sits on one (within 0.05 Ma or 1 percent of the age)."""
    for lvl in ("periods", "epochs", "eras"):
        for x in ts[lvl]:
            b = x["b_age"]
            if 0 < b <= 700 and abs(age - b) <= max(0.05, 0.01 * b) and age != 0:
                above = next((y["name"] for y in ts[lvl] if abs(y["t_age"] - b) < 1e-9), "")
                return f"{above}-{x['name']} boundary ({b:g} Ma)" if above else f"base of the {x['name']} ({b:g} Ma)"
    return ""


def classify(ts: dict, age: float) -> dict:
    era = interval(ts["eras"], age)
    period = interval(ts["periods"], age)
    epoch = interval(ts["epochs"], age)
    return {"era": era, "period": period, "epoch": epoch, "age_stage": interval(ts["ages"], age), "boundary": boundary(ts, age)}


# ------------------------------------------------------------------------------------------------ geometry helpers
def poly_from_wrapped(wp) -> Polygon | None:
    ext = [(p.get_longitude(), p.get_latitude()) for p in wp.get_exterior_points()]
    holes = [[(p.get_longitude(), p.get_latitude()) for p in wp.get_interior_points(i)] for i in range(wp.get_number_of_interior_rings())]
    if len(ext) < 3:
        return None
    g = Polygon(ext, [h for h in holes if len(h) >= 3])
    if not g.is_valid:
        g = g.buffer(0)
    return g if not g.is_empty else None


def reconstruct_polys(features, rm, age: float) -> list[tuple]:
    out: list = []
    pygplates.reconstruct(features, rm, out, age, anchor_plate_id=0)
    res = []
    for rg in out:
        geom = rg.get_reconstructed_geometry()
        if not isinstance(geom, pygplates.PolygonOnSphere):
            continue
        f = rg.get_feature()
        for wp in WRAP.wrap(geom):
            g = poly_from_wrapped(wp)
            if g is not None:
                res.append((f, g))
    return res


def clean(g, tol: float):
    g = g.simplify(tol, preserve_topology=True)
    g = shapely.set_precision(g, 0.01)
    return g if not g.is_empty else None


def fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def feat(g, **props) -> dict:
    return {"type": "Feature", "properties": props, "geometry": mapping(g)}


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def gc_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(d))


def move(rm, plate: int, age: float, lat: float, lon: float):
    """Reconstructed (lat, lon) of a present-day point carried on `plate`; None when the model has no rotation for it."""
    if age == 0:
        return round(lat, 4), round(lon, 4)
    try:
        q = rm.get_rotation(age, plate, 0, anchor_plate_id=0)
    except Exception:  # noqa: BLE001
        return None
    la, lo = (q * pygplates.PointOnSphere(lat, lon)).to_lat_lon()
    return round(la, 4), round(lo, 4)


def plate_of(part, pt):
    """(plate id, name) of the static polygon containing a point, or (None, None)."""
    hit = part.partition_point(pt)
    if hit is None:
        return None, None
    f = hit.get_feature()
    return f.get_reconstruction_plate_id(), f.get_name()


def rot_ages(path: Path) -> dict[int, set]:
    ages: dict[int, set] = defaultdict(set)
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        p = ln.split()
        if len(p) >= 7:
            try:
                ages[int(p[0])].add(float(p[1]))
            except ValueError:
                pass
    return ages


# ------------------------------------------------------------------------------------------------ places
def load_places() -> list[dict]:
    out = []
    want = set(REFERENCE_PLACES)
    for f in ("cities/cities.geojson", "geographical_features/features.geojson", "localities/localities.geojson", "states/india_states.geojson", "districts/india_districts.geojson", "countries/india.geojson"):
        for x in json.loads((ATLAS / "geographical_boundaries" / f).read_text(encoding="utf-8"))["features"]:
            p = x["properties"]
            if p.get("lat") is None or p.get("lon") is None:
                continue
            out.append({"id": p["id"], "name": p["name"], "lat": p["lat"], "lon": p["lon"], "level": p["level"], "reference": p["id"] in want})
    for e in EXTRA_POINTS:
        out.append({"id": e["id"], "name": e["name"], "lat": e["lat"], "lon": e["lon"], "level": "region", "reference": True, "note": e["note"]})
    return out


HIMALAYAN = ("mountain:himalayas", "river:dhauliganga-catchment", "glacier:gangotri-glacier")


# ------------------------------------------------------------------------------------------------ main
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ts = load_timescale()
    dump(RUNTIME / "timescale.json", ts)

    eb_rot_file = GEO / "Rotations/Zahirovic_etal_2022_OptimisedMantleRef_and_NNRMantleRef.rot"
    pm_rot_file = SCO / "PALEOMAP Global Plate Model/PALEOMAP_PlateModel.rot"
    rm = {EB: pygplates.RotationModel(str(eb_rot_file)), PM: pygplates.RotationModel(str(pm_rot_file))}
    poles = {EB: rot_ages(eb_rot_file), PM: rot_ages(pm_rot_file)}

    static = pygplates.FeatureCollection(str(GEO / "StaticPolygons/Shapefile/Global_EarthByte_GPlates_PresentDay_StaticPlatePolygons.shp"))
    coast = pygplates.FeatureCollection(str(GEO / "Coastlines/Shapefile/Global_EarthByte_GPlates_PresentDay_Coastlines.shp"))
    contin = pygplates.FeatureCollection(str(GEO / "ContinentalPolygons/Shapefile/Global_EarthByte_GPlates_PresentDay_ContinentalPolygons.shp"))
    cao = {k: pygplates.FeatureCollection(str(GEO / f"Paleogeography/Global_Cao_etal/{k}_402_2.shp")) for k in ("lm", "sm", "m", "i")}
    pm_poly = pygplates.FeatureCollection(str(SCO / "PALEOMAP Global Plate Model/PALEOMAP_PlatePolygons.gpml"))
    part_eb = pygplates.PlatePartitioner(static, rm[EB])
    part_pm = pygplates.PlatePartitioner(pm_poly, rm[PM])

    # --- modern India outline carried on the Indian Plate (501)
    india = shape(json.loads((ATLAS / "geographical_boundaries/countries/india.geojson").read_text(encoding="utf-8"))["features"][0]["geometry"]).simplify(0.03)
    india_feats = []
    for part in (india.geoms if isinstance(india, MultiPolygon) else [india]):
        f = pygplates.Feature()
        f.set_geometry(pygplates.PolygonOnSphere([(y, x) for x, y in list(part.exterior.coords)[:-1]]))
        f.set_reconstruction_plate_id(501)
        india_feats.append(f)

    # --- places (reference points): plate assignment per model
    places = load_places()
    for p in places:
        pt = pygplates.PointOnSphere(p["lat"], p["lon"])
        for m, part in ((EB, part_eb), (PM, part_pm)):
            pid, pname = plate_of(part, pt)
            method = "static plate polygon containing the point"
            if p["id"] in HIMALAYAN:
                pid, method = 501, "assigned to the Indian Plate (the Himalayan fold-thrust belt is built from Indian-margin crust); the rigid static polygon may place this point on the Eurasian side"
            p[f"plate_{m}"] = {"plate_id": pid, "plate_name": pname, "method": method if pid is not None else "no polygon contains the point"}
    # a Eurasian reference point and the Indian-margin reference point for the convergence gap
    eur_pid = {m: plate_of(part, pygplates.PointOnSphere(EURASIA_POINT["lat"], EURASIA_POINT["lon"]))[0] for m, part in ((EB, part_eb), (PM, part_pm))}
    ind_ref = {"lat": 28.5, "lon": 80.0}

    frames_meta = []
    cao_cache: dict[float, dict] = {}
    for age in AGES:
        d = RUNTIME / "frames" / akey(age)
        cls = classify(ts, age)
        info = {"age_ma": age, "key": akey(age), **cls, "models": {}}
        done = d / "frame.json"
        if done.exists() and not os.environ.get("DEEPTIME_REBUILD"):
            info = json.loads(done.read_text(encoding="utf-8"))
            cao_cache[age] = {lab: [shape(x["geometry"]) for x in json.loads((d / f"cao_{lab}.geojson").read_text(encoding="utf-8"))["features"]] for lab in ("landmass", "shallow_marine", "mountains", "ice_sheet")}
            frames_meta.append(info)
            print("frame", age, "(reused)")
            continue

        # EarthByte model ----------------------------------------------------------------------
        plates = defaultdict(list)
        names = {}
        for f, g in reconstruct_polys(static, rm[EB], age):
            pid = f.get_reconstruction_plate_id()
            plates[pid].append(g)
            names.setdefault(pid, f.get_name() or "")
        plate_feats = []
        for pid, gs in plates.items():
            g = clean(unary_union(gs), 0.15)
            if g is not None:
                plate_feats.append(feat(g, plate_id=pid, name=names[pid], is_indian_plate=(pid == 501)))
        dump(d / "plates.geojson", fc(plate_feats))
        cfe = [feat(g2, name=f.get_name(), plate_id=f.get_reconstruction_plate_id()) for f, g in reconstruct_polys(contin, rm[EB], age) if (g2 := clean(g, 0.1)) is not None]
        dump(d / "continents.geojson", fc(cfe))
        cof = [feat(g2, plate_id=f.get_reconstruction_plate_id()) for f, g in reconstruct_polys(coast, rm[EB], age) if (g2 := clean(g, 0.08)) is not None]
        dump(d / "coastlines.geojson", fc(cof))
        caoc: dict[str, list] = {}
        cao_interval = None
        for k, label in (("lm", "landmass"), ("sm", "shallow_marine"), ("m", "mountains"), ("i", "ice_sheet")):
            polys = reconstruct_polys(cao[k], rm[EB], age)
            fl = []
            for f, g in polys:
                a = f.get_shapefile_attributes() or {}
                if cao_interval is None and a.get("FROMAGE") is not None:
                    cao_interval = [a.get("FROMAGE"), a.get("TOAGE")]
                g2 = clean(g, 0.1)
                if g2 is not None:
                    fl.append(feat(g2, cls=label, from_age=a.get("FROMAGE"), to_age=a.get("TOAGE"), plate_id=f.get_reconstruction_plate_id()))
            caoc[label] = fl
            dump(d / f"cao_{label}.geojson", fc(fl))
        cao_cache[age] = {k: [shape(x["geometry"]) for x in v] for k, v in caoc.items()}
        ind = []
        for f, g in reconstruct_polys(india_feats, rm[EB], age):
            g2 = clean(g, 0.03)
            if g2 is not None:
                ind.append(feat(g2, name="Modern India outline (reference only)"))
        dump(d / "india_outline_earthbyte.geojson", fc(ind))
        info["models"][EB] = {"label": EB_NAME, "polygon_counts": {"plates": len(plate_feats), "continents": len(cfe), "coastlines": len(cof), **{k: len(v) for k, v in caoc.items()}}, "cao_interval_ma": cao_interval if any(caoc.values()) else None}

        # PALEOMAP model -----------------------------------------------------------------------
        ind2 = []
        for f, g in reconstruct_polys(india_feats, rm[PM], age):
            g2 = clean(g, 0.03)
            if g2 is not None:
                ind2.append(feat(g2, name="Modern India outline (reference only)"))
        dump(d / "india_outline_paleomap.geojson", fc(ind2))
        info["models"][PM] = {"label": PM_NAME}
        dump(done, info)
        frames_meta.append(info)
        print("frame", age, cls["period"], info["models"][EB]["polygon_counts"])

    # --- Scotese maps -------------------------------------------------------------------------
    maps = {}
    for p in sorted((SCO / "PALEOMAP PaleoAtlas Rasters v3").glob("*.jpg")):
        m = re.search(r"_(\d{3})\.jpg$", p.name)
        if m:
            maps[int(m.group(1))] = p
    for fm in frames_meta:
        age = fm["age_ma"]
        best = min(maps, key=lambda a: abs(a - age))
        src = maps[best]
        dst = RUNTIME / "paleomap" / f"{best:03d}.jpg"
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(src) as im:
                w, h = im.size
                im = im.convert("RGB")
                if w > 2400:
                    im = im.resize((2400, round(h * 2400 / w)), Image.LANCZOS)
                im.save(dst, quality=84, optimize=True)
        with Image.open(src) as im:
            fm["models"][PM].update({"map_file": f"paleomap/{best:03d}.jpg", "map_age_ma": best, "map_name": src.stem, "map_exact": best == age, "map_offset_ma": round(best - age, 4), "source_pixels": list(im.size)})

    # --- places: reconstructed positions + Cao context ---------------------------------------
    trees = {age: {lab: (STRtree(gs), gs) for lab, gs in c.items() if gs} for age, c in cao_cache.items()}
    for p in places:
        p["recon"] = {EB: {}, PM: {}}
        for fm in frames_meta:
            age = fm["age_ma"]
            for m in (EB, PM):
                pid = p[f"plate_{m}"]["plate_id"]
                p["recon"][m][akey(age)] = move(rm[m], pid, age, p["lat"], p["lon"]) if pid is not None else None
            pos = p["recon"][EB][akey(age)]
            ctx = None
            if pos and 2 <= age <= 402:
                pt = Point(pos[1], pos[0])
                ctx = "no mapped land or shallow sea at this position (deep ocean or not mapped)"
                for label, name in (("ice_sheet", "ice sheet"), ("mountains", "mountains"), ("landmass", "landmass"), ("shallow_marine", "shallow marine")):
                    tr = trees[age].get(label)
                    if tr and any(tr[1][i].contains(pt) for i in tr[0].query(pt)):
                        ctx = name
                        break
            p.setdefault("cao_context", {})[akey(age)] = ctx
    dump(RUNTIME / "places.json", {"models": {EB: EB_NAME, PM: PM_NAME}, "places": places})

    # --- India gap to Eurasia and plate motion ----------------------------------------------
    gap = {}
    for fm in frames_meta:
        age = fm["age_ma"]
        row = {}
        for m in (EB, PM):
            a = move(rm[m], 501, age, ind_ref["lat"], ind_ref["lon"])
            e = move(rm[m], eur_pid[m], age, EURASIA_POINT["lat"], EURASIA_POINT["lon"]) if eur_pid[m] is not None else None
            row[m] = {"india": a, "eurasia": e, "gap_km": round(gc_km(*a, *e)) if a and e else None, "eurasia_plate_id": eur_pid[m]}
        gap[akey(age)] = row
    speed = {}
    prev = None
    for fm in frames_meta:
        age = fm["age_ma"]
        if prev is not None and age - prev > 0.5:
            for m in (EB, PM):
                a0 = move(rm[m], 501, prev, 20.0, 78.0)
                a1 = move(rm[m], 501, age, 20.0, 78.0)
                speed.setdefault(m, []).append({"from_ma": age, "to_ma": prev, "cm_per_year": round(gc_km(*a0, *a1) * 1e5 / ((age - prev) * 1e6), 2)})
        prev = age
    dump(RUNTIME / "india_gap_and_motion.json", {"reference": {"india_point": ind_ref, "eurasia_point": EURASIA_POINT, "note": "Great-circle distance between a point on the Indian Plate and a point on the Eurasian Plate, both reconstructed with the same model. Rigid plates only: shortening inside Eurasia and India is not represented, so the gap does not equal the amount of ocean."}, "gap": gap, "speed": speed})

    # --- fossils --------------------------------------------------------------------------------
    fossils = build_fossils(ts, rm, part_eb, part_pm)
    dump(RUNTIME / "fossils.json", fossils)
    forms = build_formations(ts, rm, part_eb, part_pm)
    dump(RUNTIME / "formations.json", forms)
    # --- manifest -------------------------------------------------------------------------------
    for fm in frames_meta:
        age = fm["age_ma"]
        eb_poles = poles[EB].get(501, set())
        pm_poles = poles[PM].get(501, set())
        fm["interpolation"] = {EB: "pole age present in the rotation file (no interpolation)" if any(abs(age - x) < 1e-6 for x in eb_poles) else "rotation interpolated by the model between its finite-rotation poles", PM: "pole age present in the rotation file (no interpolation)" if any(abs(age - x) < 1e-6 for x in pm_poles) else "rotation interpolated by the model between its finite-rotation poles"}
        fm["has_cao"] = 2 <= age <= 402
    manifest = {"ages": [f["age_ma"] for f in frames_meta], "frames": frames_meta, "models": {EB: EB_NAME, PM: PM_NAME}, "requested_ages": REQUESTED, "added_ages": EXTRA}
    dump(RUNTIME / "manifest.json", manifest)
    print("frames:", len(frames_meta), "fossils:", len(fossils["records"]))


# ------------------------------------------------------------------------------------------------ fossils
def read_pbdb(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    i = next(k for k, ln in enumerate(lines) if ln.startswith('"occurrence_no"') or ln.startswith('"collection_no"') or ln.startswith('"reference_no"'))
    rd = list(csv.reader(io.StringIO("\n".join(lines[i:]))))
    h = rd[0]
    seen = Counter()
    keys = []
    for c in h:
        keys.append(c if seen[c] == 0 else f"{c}__{seen[c]}")
        seen[c] += 1
    return [dict(zip(keys, r)) for r in rd[1:] if len(r) == len(keys)]


def build_fossils(ts, rm, part_eb, part_pm) -> dict:
    rows = read_pbdb(ORIG / "PALEOBIOLOGY_DATABASE/pbdb_occs_Dinosauria_IN.csv")
    refs = {r["reference_no"]: r for r in read_pbdb(ORIG / "PALEOBIOLOGY_DATABASE/pbdb_refs_Dinosauria_IN.csv")}
    out = []
    for r in rows:
        try:
            lat, lon = float(r["lat"]), float(r["lng"])
            mx, mn = float(r["max_ma"]), float(r["min_ma"])
        except ValueError:
            continue
        pt = pygplates.PointOnSphere(lat, lon)
        recon = {}
        pids = {}
        for m, part in ((EB, part_eb), (PM, part_pm)):
            pid, _ = plate_of(part, pt)
            pids[m] = pid
            recon[m] = {}
            if pid is None:
                continue
            for a in AGES:
                if mn - 5 <= a <= mx + 5:
                    pos = move(rm[m], pid, a, lat, lon)
                    if pos:
                        recon[m][akey(a)] = pos
        flags = r.get("flags", "")
        ftype = "trace fossil (ichnotaxon)" if "I" in flags else ("form taxon (isolated remains, e.g. eggs or teeth)" if "F" in flags else "body fossil (taxonomic occurrence)")
        fm = r.get("formation") or r.get("formation__1") or ""
        ref = refs.get(r["reference_no"], {})
        out.append({
            "occurrence_id": f"PBDB:occ:{r['occurrence_no']}", "taxon_name": r["accepted_name"], "identified_name": r["identified_name"], "higher_taxonomy": " > ".join(x for x in (r.get("phylum"), r.get("class"), r.get("order"), r.get("family"), r.get("genus")) if x and not x.startswith("NO_")),
            "fossil_type": ftype, "geological_period": span(ts, mx, mn), "interval": " to ".join(x for x in (r["early_interval"], r["late_interval"]) if x), "minimum_age_ma": mn, "maximum_age_ma": mx,
            "locality": r.get("geogcomments", "")[:300], "county": r.get("county", ""), "state": r["state"], "latitude": lat, "longitude": lon, "formation": fm, "member": r.get("member", ""), "environment": r.get("environment", ""), "lithology": r.get("lithology1", ""),
            "reference_id": f"PBDB:ref:{r['reference_no']}", "reference_text": r.get("primary_reference", ""), "reference_doi": ref.get("doi", ""), "collection_id": f"PBDB:col:{r['collection_no']}",
            "source_database": "The Paleobiology Database (CC0)", "data_quality": f"coordinates {r.get('latlng_basis') or 'basis not stated'} ({r.get('latlng_precision') or 'precision not stated'}); age range {mx - mn:.1f} Myr", "plate_id": pids, "recon": recon,
        })
    return {"source": "The Paleobiology Database, data service 1.2, query base_name=Dinosauria cc=IN", "records": out, "models": {EB: EB_NAME, PM: PM_NAME}}


def macrostrat_get(path: str, cache: dict) -> dict:
    """Macrostrat API call, cached in the originals folder so the exact responses are kept."""
    if path in cache:
        return cache[path]
    import urllib.request
    req = urllib.request.Request("https://macrostrat.org/api/v2/" + path, headers={"User-Agent": "NASAX-research-client"})
    try:
        cache[path] = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        cache[path] = {"error": f"{type(exc).__name__}: {exc}"}
    return cache[path]


def build_formations(ts, rm, part_eb, part_pm) -> dict:
    """Formations named in Mesozoic PBDB collections in India, enriched with Macrostrat where it holds a matching name."""
    from urllib.parse import quote
    rows = read_pbdb(ORIG / "PALEOBIOLOGY_DATABASE/pbdb_occs_Mesozoic_IN.csv")
    g: dict = {}
    for r in rows:
        f = r.get("formation") or r.get("formation__1") or ""
        if not f:
            continue
        try:
            lat, lon, mx, mn = float(r["lat"]), float(r["lng"]), float(r["max_ma"]), float(r["min_ma"])
        except ValueError:
            continue
        k = (f, r.get("state", ""))
        d = g.setdefault(k, {"cols": set(), "occ": 0, "lat": [], "lon": [], "max": [], "min": [], "lith": Counter(), "env": Counter(), "ref": set(), "group": Counter(), "member": Counter()})
        d["occ"] += 1
        if r["collection_no"] not in d["cols"]:
            d["cols"].add(r["collection_no"])
            d["lat"].append(lat)
            d["lon"].append(lon)
        d["max"].append(mx)
        d["min"].append(mn)
        for key_, col in (("lith", "lithology1"), ("env", "environment"), ("group", "geological_group"), ("member", "member")):
            if r.get(col):
                d[key_][r[col]] += 1
        d["ref"].add(r["reference_no"])
    cache_path = ORIG / "MACROSTRAT" / "macrostrat_strat_names_lookup.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    recs = []
    for n, ((f, st), d) in enumerate(sorted(g.items(), key=lambda kv: -kv[1]["occ"]), 1):
        lat, lon = sum(d["lat"]) / len(d["lat"]), sum(d["lon"]) / len(d["lon"])
        mx, mn = max(d["max"]), min(d["min"])
        name = re.sub(r"\s+(Formation|Fm\.?|beds|Beds|Shale|Group)$", "", f).strip() or f
        ms = macrostrat_get(f"defs/strat_names?strat_name={quote(name)}&response=long&format=json", cache)
        hits = (ms.get("success") or {}).get("data") or []
        match = None
        if hits:
            h0 = hits[0]
            match = {"strat_name_id": h0.get("strat_name_id"), "name": h0.get("strat_name_long") or h0.get("strat_name"), "rank": h0.get("rank"), "t_age": h0.get("t_age"), "b_age": h0.get("b_age"), "ref_id": h0.get("ref_id"), "n_hits": len(hits)}
        recon = {EB: {}, PM: {}}
        pt = pygplates.PointOnSphere(lat, lon)
        for m, part in ((EB, part_eb), (PM, part_pm)):
            pid, _ = plate_of(part, pt)
            if pid is None:
                continue
            for a in AGES:
                if mn - 5 <= a <= mx + 5:
                    pos = move(rm[m], pid, a, lat, lon)
                    if pos:
                        recon[m][akey(a)] = pos
        recs.append({"formation_id": f"PBDB-FM-{n:03d}", "formation_name": f, "state": st or "not stated in PBDB", "locality": f"mean position of {len(d['cols'])} PBDB collection(s)", "lithology": ", ".join(k for k, _ in d["lith"].most_common(3)), "depositional_environment": ", ".join(k for k, _ in d["env"].most_common(3)), "group": ", ".join(k for k, _ in d["group"].most_common(2)),
                     "minimum_age_ma": mn, "maximum_age_ma": mx, "geological_period": span(ts, mx, mn), "latitude": round(lat, 4), "longitude": round(lon, 4), "n_collections": len(d["cols"]), "n_occurrences": d["occ"], "reference_ids": sorted(f"PBDB:ref:{x}" for x in d["ref"])[:12], "n_references": len(d["ref"]),
                     "source_database": "The Paleobiology Database (CC0) collections" + ("; Macrostrat strat-name match" if match else "; no Macrostrat strat-name match"), "macrostrat_match": match, "recon": recon})
    cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return {"source": "PBDB occurrences in India, 66-252 Ma, grouped by formation and state; ages are the union of the collection age ranges and are not formal formation ages", "records": recs}


def span(ts, mx, mn) -> str:
    a, b = interval(load_ts_cache()["periods"], mx - 1e-6), interval(load_ts_cache()["periods"], max(mn, 0) + 1e-6)
    return a if a == b else f"{a} to {b}"


_TS = {}


def load_ts_cache():
    if not _TS:
        _TS.update(load_timescale())
    return _TS


if __name__ == "__main__":
    main()
