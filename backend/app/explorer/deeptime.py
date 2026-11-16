"""Deep-Time Geological Explorer: serves reconstruction frames, fossils and place histories built from original scientific data.

Data is produced offline by scripts/build_deeptime_data.py (pygplates + EarthByte/PALEOMAP/PBDB/ICS). This module only reads it.
Every response labels what is a dataset record, what is a model reconstruction, what is a published interpretation and
what is uncertain. Frames are direct evaluations of the rotation models; no frame is a measurement of the past.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from app.explorer.deeptime_knowledge import BIBLIOGRAPHY, EVENTS, EURASIA_POINT, HIMALAYA_STAGES

EB, PM = "earthbyte", "paleomap"
MODEL_LABEL = {EB: "EarthByte (Zahirovic et al. 2022 rotations; Cao et al. 2017 paleogeography)", PM: "PALEOMAP (Scotese 2016 maps and plate model)"}
DINO_SLICES = [250, 230, 200, 180, 150, 130, 120, 100, 90, 75, 66]
LAYER_FILES = {
    "plates": ("plates.geojson", "Plate geometry (static polygons moved rigidly with the rotation model)", "model reconstruction"),
    "continents": ("continents.geojson", "Continental polygons", "model reconstruction"),
    "coastlines": ("coastlines.geojson", "Present-day coastlines carried on their plates (not ancient shorelines)", "model reconstruction"),
    "landmass": ("cao_landmass.geojson", "Paleo landmass (Cao et al. 2017)", "published paleogeography"),
    "shallow_marine": ("cao_shallow_marine.geojson", "Paleo shallow sea (Cao et al. 2017)", "published paleogeography"),
    "mountains": ("cao_mountains.geojson", "Paleo mountains (Cao et al. 2017)", "published paleogeography"),
    "ice_sheet": ("cao_ice_sheet.geojson", "Paleo ice sheets (Cao et al. 2017)", "published paleogeography"),
}
CAVEAT = ("Geological Reconstruction: a model-based visualisation, not a satellite observation and not a photograph of the past. "
          "Positions carry model uncertainty; the two plate models shown here can disagree by hundreds to thousands of kilometres.")


def km(a: tuple, b: tuple) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    d = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(d))


def key(age: float) -> str:
    return f"{age:g}".replace(".", "p")


def ma_text(age: float) -> str:
    if age == 0:
        return "present day"
    if age < 0.0105:
        return f"{round(age * 1e6):,} years ago"
    if age < 1:
        return f"{round(age * 1e6):,} years ago"
    return f"{age:g} million years ago"


class DeepTimeService:
    def __init__(self, root: Path):
        self.root = root
        self.available = (root / "manifest.json").exists()
        self._m: dict | None = None
        self._places: dict | None = None
        self._fossils: dict | None = None
        self._gap: dict | None = None
        self._forms: list[dict] | None = None

    # ----------------------------------------------------------------------------------- loading
    def _j(self, name: str) -> Any:
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    @property
    def manifest(self) -> dict:
        if self._m is None:
            self._m = self._j("manifest.json")
        return self._m

    @property
    def places(self) -> dict[str, dict]:
        if self._places is None:
            self._places = {p["id"]: p for p in self._j("places.json")["places"]}
        return self._places

    @property
    def fossils(self) -> list[dict]:
        if self._fossils is None:
            self._fossils = self._j("fossils.json")["records"]
        return self._fossils

    @property
    def formations(self) -> list[dict]:
        if self._forms is None:
            self._forms = self._j("formations.json")["records"]
        return self._forms

    @property
    def motion(self) -> dict:
        if self._gap is None:
            self._gap = self._j("india_gap_and_motion.json")
        return self._gap

    @property
    def ages(self) -> list[float]:
        return self.manifest["ages"]

    def nearest(self, age: float) -> float:
        return min(self.ages, key=lambda a: abs(a - age))

    def frame_meta(self, age: float) -> dict:
        a = self.nearest(age)
        return next(f for f in self.manifest["frames"] if f["age_ma"] == a)

    def layer_path(self, age: float, name: str) -> Path | None:
        a = self.nearest(age)
        d = self.root / "frames" / key(a)
        if name == "india_outline_earthbyte" or name == "india_outline_paleomap":
            p = d / f"{name}.geojson"
        elif name in LAYER_FILES:
            p = d / LAYER_FILES[name][0]
        else:
            return None
        return p if p.exists() else None

    def paleomap_path(self, age: float) -> Path | None:
        fm = self.frame_meta(age)
        f = fm["models"][PM].get("map_file")
        return (self.root / f) if f else None

    # ---------------------------------------------------------------------------------- events
    def events(self, age: float | None = None, span: float = 0.0) -> list[dict]:
        ts = self._j("timescale.json")
        ics = {x["name"]: x["b_age"] for lvl in ("periods", "epochs", "eras") for x in ts[lvl]}
        out = []
        for e in EVENTS:
            start, end = e["start"], e["end"]
            if e.get("ics") and e["ics"] in ics:
                start = end = ics[e["ics"]]
            row = {"event_id": e["id"], "event_name": e["name"], "start_age_ma": start, "end_age_ma": end, "affected_region": e["region"], "geological_process": e["process"], "description": e["description"], "evidence_source": e["sources"], "confidence": e["confidence"], "uncertainty_notes": e["uncertainty"], "kind": "published interpretation" if "boundary" not in e["name"].lower() else "formal time-scale boundary (ICS)"}
            if age is None or (end - span - 1e-9 <= age <= start + span + 1e-9):
                out.append(row)
        return sorted(out, key=lambda r: -r["start_age_ma"])

    def references(self, ids: str | list[str] | None = None) -> list[dict]:
        want = set(ids.split(";") if isinstance(ids, str) else (ids or []))
        return [b for b in BIBLIOGRAPHY if not want or b["id"] in want]

    # ----------------------------------------------------------------------------------- frame
    def frame(self, age: float, model: str = EB) -> dict:
        if not self.available:
            raise FileNotFoundError("deep-time data not built")
        fm = self.frame_meta(age)
        a = fm["age_ma"]
        k = fm["key"]
        layers = []
        if model == EB:
            for name, (_, label, kind) in LAYER_FILES.items():
                if self.layer_path(a, name):
                    n = (fm["models"][EB]["polygon_counts"] or {}).get(name, 0)
                    if n:
                        layers.append({"name": name, "label": label, "kind": kind, "url": f"/api/explorer/deeptime/frames/{k}/layers/{name}", "features": n})
            layers.append({"name": "india_outline_earthbyte", "label": "Modern India outline carried on the Indian Plate (reference only; India as a country did not exist)", "kind": "model reconstruction", "url": f"/api/explorer/deeptime/frames/{k}/layers/india_outline_earthbyte"})
        else:
            layers.append({"name": "india_outline_paleomap", "label": "Modern India outline carried on the Indian Plate (reference only)", "kind": "model reconstruction", "url": f"/api/explorer/deeptime/frames/{k}/layers/india_outline_paleomap"})
        raster = None
        if model == PM:
            pmx = fm["models"][PM]
            raster = {"url": f"/api/explorer/deeptime/frames/{k}/paleomap", "map_age_ma": pmx["map_age_ma"], "map_name": pmx["map_name"], "exact": pmx["map_exact"], "offset_ma": pmx["map_offset_ma"], "note": "Global paleogeographic map in the coordinates of its own time (not the present-day coordinates). It is not interpolated: the nearest published map age is used." if not pmx["map_exact"] else "Global paleogeographic map in the coordinates of its own time."}
        ind = self.motion["gap"][k]
        india = {m: ind[m] for m in (EB, PM)}
        dis = None
        if india[EB]["india"] and india[PM]["india"]:
            dis = round(km(tuple(india[EB]["india"]), tuple(india[PM]["india"])))
        env = self.india_environment(a)
        return {
            "age_ma": a, "requested_age_ma": age, "label": ma_text(a), "key": k, "model": model, "model_label": MODEL_LABEL[model], "mode_label": "Geological Reconstruction",
            "era": fm["era"], "period": fm["period"], "epoch": fm["epoch"], "age_stage": fm["age_stage"], "boundary": fm["boundary"],
            "layers": layers, "raster": raster, "india": india, "models_disagree_km": dis, "interpolation": fm["interpolation"][model], "has_paleogeography": bool(fm.get("has_cao")) if model == EB else bool(raster),
            "events": self.events(a, span=max(0.05, 0.02 * a)), "environment": env, "fossil_count": len(self.fossil_records(a, 0.0, model)), "caveat": CAVEAT,
            "resolution": "Plate polygons simplified to about 10 km for display; the underlying rotation models are global and carry no city-level information." if model == EB else "Map image of about 0.1 degree per pixel (about 11 km); global model, no city-level information.",
            "sources": self.frame_sources(model, fm),
            "confidence": "Low to medium. Reconstructions further back than about 100 Ma rest on indirect evidence (seafloor spreading is mostly subducted) and differ between models." if a > 100 else "Medium for the last 100 Ma: constrained by seafloor spreading records, hotspot tracks and palaeomagnetism.",
        }

    def frame_sources(self, model: str, fm: dict) -> list[dict]:
        if model == EB:
            return [{"id": "B01", "role": "rotation model"}, {"id": "B02", "role": "plate model"}, {"id": "B03", "role": "paleogeography polygons (2 to 402 Ma)"}, {"id": "B06", "role": "time scale"}]
        return [{"id": "B05", "role": "maps and plate model"}, {"id": "B06", "role": "time scale"}]

    def india_environment(self, age: float) -> dict:
        """What the data say about the Indian Plate at this age (reference points only; never city-level)."""
        k = key(age)
        out = []
        for pid in ("city:hyderabad", "city:bengaluru", "city:mumbai", "city:delhi", "city:kolkata", "city:chennai", "mountain:himalayas"):
            p = self.places.get(pid)
            if p:
                out.append({"id": pid, "name": p["name"], "context": p["cao_context"].get(k)})
        return {"kind": "dataset record (Cao et al. 2017 classification of the reconstructed position)", "points": out}

    # ----------------------------------------------------------------------------------- fossils
    def fossil_records(self, age: float, window: float = 0.0, model: str = EB) -> list[dict]:
        k = key(self.nearest(age))
        a = self.nearest(age)
        out = []
        for r in self.fossils:
            if r["minimum_age_ma"] - window <= a <= r["maximum_age_ma"] + window:
                pos = r["recon"].get(model, {}).get(k)
                out.append({**{x: r[x] for x in ("occurrence_id", "taxon_name", "higher_taxonomy", "fossil_type", "geological_period", "minimum_age_ma", "maximum_age_ma", "locality", "state", "latitude", "longitude", "formation", "reference_id", "reference_text", "source_database", "data_quality", "environment")}, "reconstructed": pos, "age_label": f"{r['minimum_age_ma']:g} to {r['maximum_age_ma']:g} Ma", "is_bird": " > Aves" in r["higher_taxonomy"]})
        return out

    def fossil_geojson(self, age: float, window: float = 0.0, model: str = EB) -> dict:
        feats = []
        for r in self.fossil_records(age, window, model):
            pos = r["reconstructed"]
            if pos is None:
                continue
            feats.append({"type": "Feature", "properties": {**{k: v for k, v in r.items() if k not in ("reconstructed",)}, "modern_latitude": r["latitude"], "modern_longitude": r["longitude"]}, "geometry": {"type": "Point", "coordinates": [pos[1], pos[0]]}})
        return {"type": "FeatureCollection", "features": feats, "properties": {"note": "Points are the modern find-spots carried to their reconstructed position at this age. A fossil at a modern coordinate does not show that the whole modern region had the same environment."}}

    def formation_geojson(self, age: float, window: float = 0.0, model: str = EB) -> dict:
        a = self.nearest(age)
        k = key(a)
        feats = []
        for r in self.formations:
            if r["minimum_age_ma"] - window <= a <= r["maximum_age_ma"] + window:
                pos = r["recon"].get(model, {}).get(k)
                if pos is None:
                    continue
                props = {x: r[x] for x in ("formation_id", "formation_name", "state", "locality", "lithology", "depositional_environment", "minimum_age_ma", "maximum_age_ma", "geological_period", "n_collections", "n_occurrences", "source_database", "reference_ids")}
                props.update(modern_latitude=r["latitude"], modern_longitude=r["longitude"], macrostrat=r["macrostrat_match"])
                feats.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [pos[1], pos[0]]}})
        return {"type": "FeatureCollection", "features": feats, "properties": {"note": "Formation positions are the mean of PBDB collection coordinates, carried to their reconstructed position. Ages are the union of the collection age ranges, not formal formation ages."}}

    # ----------------------------------------------------------------------------------- places
    def place(self, pid: str, age: float) -> dict | None:
        p = self.places.get(pid)
        if not p:
            return None
        a = self.nearest(age)
        k = key(a)
        pos = {m: p["recon"][m].get(k) for m in (EB, PM)}
        dis = round(km(tuple(pos[EB]), tuple(pos[PM]))) if pos[EB] and pos[PM] else None
        return {
            "id": pid, "name": p["name"], "modern_position": {"latitude": p["lat"], "longitude": p["lon"]}, "age_ma": a, "age_label": ma_text(a),
            "plate": {m: p[f"plate_{m}"] for m in (EB, PM)}, "reconstructed_position": pos, "models_disagree_km": dis, "paleogeography_context": p["cao_context"].get(k),
            "explanation": self.explain_place(p, a, pos, dis), "limitations": ["Only the plate carrying the modern location is reconstructed. The city, lake or river itself did not exist at this age.", "The source models are global and cannot resolve city-level paleogeography; no ancient city-scale topography is drawn.", CAVEAT],
        }

    def explain_place(self, p: dict, age: float, pos: dict, dis: int | None) -> str:
        k = key(age)
        pl = p["plate_earthbyte"]
        bits = [f"{p['name']} ({p['lat']:.2f}N, {p['lon']:.2f}E today) sits on the {pl.get('plate_name') or 'plate with id ' + str(pl.get('plate_id'))} in the EarthByte model" + (f" (plate {pl['plate_id']})." if pl.get("plate_id") else ".")]
        if age == 0:
            bits.append("This is the present day: no reconstruction is applied.")
            return " ".join(bits)
        if pos[EB]:
            bits.append(f"Model reconstruction at {ma_text(age)}: the underlying plate position was near {abs(pos[EB][0]):.1f}{'N' if pos[EB][0] >= 0 else 'S'}, {abs(pos[EB][1]):.1f}{'E' if pos[EB][1] >= 0 else 'W'} (EarthByte)" + (f" and {abs(pos[PM][0]):.1f}{'N' if pos[PM][0] >= 0 else 'S'}, {abs(pos[PM][1]):.1f}{'E' if pos[PM][1] >= 0 else 'W'} (PALEOMAP); the two models differ by about {dis:,} km." if pos[PM] and dis is not None else "."))
        ctx = p["cao_context"].get(k)
        if ctx:
            bits.append(f"Dataset record: Cao et al. (2017) classify the reconstructed position as: {ctx}.")
        elif 0 < age < 2:
            bits.append("The Cao et al. paleogeography covers 2 to 402 Ma, so no paleogeographic class is available at this age.")
        return " ".join(bits)

    # ----------------------------------------------------------------------------------- analytics
    def analytics(self) -> dict:
        """Series for the Deep-Time Analytics page, all computed from the built data (nothing typed in)."""
        from collections import Counter

        ages = sorted(self.ages)
        track = []
        for a in ages:
            g = self.motion["gap"][key(a)]
            eb, pm = g[EB], g[PM]
            dis = round(km(tuple(eb["india"]), tuple(pm["india"]))) if eb["india"] and pm["india"] else None
            fm = self.frame_meta(a)
            track.append({"age_ma": a, "period": fm["period"], "eb_lat": eb["india"][0] if eb["india"] else None, "eb_lon": eb["india"][1] if eb["india"] else None, "pm_lat": pm["india"][0] if pm["india"] else None, "pm_lon": pm["india"][1] if pm["india"] else None, "eb_gap_km": eb["gap_km"], "pm_gap_km": pm["gap_km"], "models_disagree_km": dis})
        path_km = {}
        for m, la, lo in ((EB, "eb_lat", "eb_lon"), (PM, "pm_lat", "pm_lon")):
            path_km[m] = round(sum(km((a[la], a[lo]), (b[la], b[lo])) for a, b in zip(track, track[1:]) if a[la] is not None and b[la] is not None))
        speed = self.motion["speed"]
        peak = {}
        for m, rows in speed.items():
            top = max(rows, key=lambda r: r["cm_per_year"])
            peak[m] = {"cm_per_year": top["cm_per_year"], "from_ma": top["from_ma"], "to_ma": top["to_ma"]}
        fos = self.fossils
        per = Counter(r["geological_period"] for r in fos)
        bins = []
        for lo in range(0, 260, 10):
            hi = lo + 10
            bins.append({"from_ma": lo, "to_ma": hi, "records": sum(1 for r in fos if r["minimum_age_ma"] < hi and r["maximum_age_ma"] >= lo)})
        grp = Counter((r["higher_taxonomy"].split(" > ") + ["unclassified"])[1] for r in fos)
        form_per = Counter(r["geological_period"] for r in self.formations)
        cities = ["city:hyderabad", "city:bengaluru", "city:mumbai", "city:delhi", "city:kolkata", "city:chennai"]
        strips = []
        for pid in cities:
            p = self.places.get(pid)
            if p:
                strips.append({"id": pid, "name": p["name"], "series": [{"age_ma": a, "class": p["cao_context"].get(key(a))} for a in ages]})
        return {
            "track": track, "speed": speed,
            "kpis": {"path_km": path_km, "peak_speed": peak, "ages": len(ages), "fossil_records": len(fos), "birds": sum(1 for r in fos if " > Aves" in r["higher_taxonomy"]), "formations": len(self.formations), "events": len(self.events()), "max_models_disagree_km": max((t["models_disagree_km"] or 0) for t in track)},
            "fossils": {"by_period": [{"period": k, "records": v} for k, v in per.most_common()], "by_age": bins, "by_group": [{"group": k, "records": v} for k, v in grp.most_common()], "by_state": [{"state": k or "not stated", "records": v} for k, v in Counter(r["state"] for r in fos).most_common(10)], "top_taxa": [{"taxon": k, "records": v} for k, v in Counter(r["taxon_name"] for r in fos).most_common(10)]},
            "formations": {"by_period": [{"period": k, "formations": v} for k, v in form_per.most_common()]},
            "places": strips, "events": self.events(),
            "note": "Rigid-plate model values; the India-Eurasia distance is not the width of an ocean. Fossil counts are PBDB record counts, not abundance.",
        }

    def sources(self) -> list[dict]:
        import csv

        p = self.root / "csv" / "geological_reconstruction_metadata.csv"
        if not p.exists():
            return []
        with p.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    # ----------------------------------------------------------------------------------- himalaya / dinosaurs
    def himalaya(self) -> dict:
        rows = []
        h = self.places.get("mountain:himalayas")
        for st in HIMALAYA_STAGES:
            a = self.nearest(st["age"])
            k = key(a)
            gap = self.motion["gap"][k]
            rows.append({**st, "age_ma": a, "label": ma_text(a), "india_position": {m: gap[m]["india"] for m in (EB, PM)}, "india_eurasia_gap_km": {m: gap[m]["gap_km"] for m in (EB, PM)}, "himalaya_point": {m: (h["recon"][m].get(k) if h else None) for m in (EB, PM)}, "references": self.references(st["sources"])})
        return {"title": "Himalayan formation", "note": "Collision timing is debated; ranges and competing models are kept rather than a single date.", "stages": rows, "gap_note": self.motion["reference"]["note"]}

    def dinosaur_era(self) -> dict:
        slices = []
        for a in DINO_SLICES:
            f = self.frame(a, EB)
            recs = self.fossil_records(a, 0.0, EB)
            slices.append({"age_ma": f["age_ma"], "label": f["label"], "period": f["period"], "epoch": f["epoch"], "boundary": f["boundary"], "india": f["india"], "fossil_count": len(recs), "fossil_count_within_5_ma": len(self.fossil_records(a, 5.0, EB)), "events": f["events"], "has_paleogeography": f["has_paleogeography"], "paleomap": self.frame_meta(a)["models"][PM].get("map_name")})
        return {"title": "India during the age of dinosaurs", "slices": slices, "note": "Fossil counts are PBDB occurrence records whose age range includes the time slice. Absence of records is not evidence of absence of dinosaurs."}
