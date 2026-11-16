"""Render the visual-proof PNGs for the Deep-Time evidence package from the built data (no hand-drawn geography).

    python -X utf8 scripts/build_deeptime_previews.py          (needs matplotlib, numpy, Pillow)

Every map is drawn from datasets/deep_time (the reconstructed GeoJSON frames, PALEOMAP maps and PBDB-derived fossil records).
Each image carries its own label: "Geological Reconstruction, not a satellite observation".
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import PatchCollection  # noqa: E402
from matplotlib.patches import PathPatch  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "deep_time"
EVID = Path(os.environ.get("DEEPTIME_EVIDENCE", "F:/NASAX_DEEP_TIME_EVIDENCE"))
VP = EVID / "05_VISUAL_PROOF"
LABEL = "Geological Reconstruction (model-based), not a satellite observation"
OCEAN = "#0d3b66"
BG = "#050b1c"
FILL = {"cao_shallow_marine": ("#3fb2d6", 0.75), "cao_landmass": ("#5aa469", 1.0), "cao_mountains": ("#9a7b55", 1.0), "cao_ice_sheet": ("#f1f8ff", 1.0)}


def key(a: float) -> str:
    return f"{a:g}".replace(".", "p")


def load(p: Path) -> dict | None:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def patches(fc: dict | None, pred=None) -> list[PathPatch]:
    out = []
    if not fc:
        return out
    for f in fc["features"]:
        if pred and not pred(f["properties"]):
            continue
        g = f["geometry"]
        if not g:
            continue
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"] if g["type"] == "MultiPolygon" else []
        for poly in polys:
            verts, codes = [], []
            for ring in poly:
                if len(ring) < 3:
                    continue
                verts += [tuple(p) for p in ring]
                codes += [MPath.MOVETO] + [MPath.LINETO] * (len(ring) - 2) + [MPath.CLOSEPOLY]
            if verts:
                out.append(PathPatch(MPath(verts, codes)))
    return out


def add(ax, fc, fc_color, alpha=1.0, edge="none", lw=0.0, pred=None, z=1):
    ps = patches(fc, pred)
    if ps:
        ax.add_collection(PatchCollection(ps, facecolor=fc_color, edgecolor=edge, linewidth=lw, alpha=alpha, zorder=z))


def style(ax, extent, title, small=False):
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_facecolor(OCEAN)
    ax.set_aspect("equal")
    ax.set_xticks(range(int(extent[0] // 30 * 30), int(extent[1]) + 1, 30))
    ax.set_yticks(range(int(extent[2] // 30 * 30), int(extent[3]) + 1, 30))
    ax.tick_params(labelsize=6 if small else 8, colors="#9fb3c8")
    ax.grid(color="#ffffff", alpha=0.08, lw=0.4)
    ax.set_title(title, color="white", fontsize=8 if small else 11, loc="left")
    for s in ax.spines.values():
        s.set_color("#3b4a63")


def fig_new(w, h):
    fig = plt.figure(figsize=(w, h), dpi=110, facecolor=BG)
    return fig


def foot(fig, text):
    fig.text(0.01, 0.01, text, color="#9fb3c8", fontsize=6.5)


def draw_eb(ax, k, india_only_outline=True):
    d = DATA / "frames" / k
    has = any((d / f"{n}.geojson").exists() and load(d / f"{n}.geojson")["features"] for n in ("cao_landmass",))
    for n in ("cao_shallow_marine", "cao_landmass", "cao_mountains", "cao_ice_sheet"):
        add(ax, load(d / f"{n}.geojson"), FILL[n][0], FILL[n][1], z=2)
    if not has:
        add(ax, load(d / "continents.geojson"), "#3f7f5f", 0.85, z=2)
        add(ax, load(d / "coastlines.geojson"), "none", 1.0, edge="#e5e7eb", lw=0.3, z=3)
    pl = load(d / "plates.geojson")
    add(ax, pl, "none", 1.0, edge="#94a3b8", lw=0.3, pred=lambda p: not p.get("is_indian_plate"), z=4)
    add(ax, pl, "#f59e0b", 0.25, edge="#f59e0b", lw=1.2, pred=lambda p: bool(p.get("is_indian_plate")), z=5)
    add(ax, load(d / "india_outline_earthbyte.geojson"), "none", 1.0, edge="#fbbf24", lw=1.6, z=6)
    return has


def frame_previews():
    out = VP / "GLOBAL_RECONSTRUCTIONS"
    out.mkdir(parents=True, exist_ok=True)
    man = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    n = 0
    for fm in man["frames"]:
        a, k = fm["age_ma"], fm["key"]
        head = f"{a:g} Ma - {fm['period']} / {fm['epoch']}" if a else "Present day (0 Ma)"
        # EarthByte
        fig = fig_new(9, 4.9)
        ax = fig.add_axes([0.05, 0.1, 0.93, 0.8])
        has = draw_eb(ax, k)
        style(ax, (-180, 180, -90, 90), f"{head}   EarthByte (Zahirovic 2022)" + (" + Cao 2017" if has else ", no paleogeography at this age"))
        foot(fig, LABEL + ". Amber = Indian Plate. Rotation interpolated between the model's poles." if a else LABEL + ". Present day: no reconstruction applied.")
        fig.savefig(out / f"recon_{k}_eb.png")
        plt.close(fig)
        # PALEOMAP
        mf = fm["models"]["paleomap"].get("map_file")
        fig = fig_new(9, 4.9)
        ax = fig.add_axes([0.05, 0.1, 0.93, 0.8])
        style(ax, (-180, 180, -90, 90), f"{head}   PALEOMAP / Scotese map '{fm['models']['paleomap'].get('map_name', 'n/a')}'")
        if mf:
            ax.imshow(np.asarray(Image.open(DATA / mf).convert("RGB")), extent=(-180, 180, -90, 90), zorder=1, interpolation="bilinear")
        add(ax, load(DATA / "frames" / k / "india_outline_paleomap.geojson"), "none", 1.0, edge="#fbbf24", lw=1.6, z=6)
        exact = fm["models"]["paleomap"].get("map_exact")
        foot(fig, LABEL + ". " + ("Published map used as is" if exact else f"Nearest map ({fm['models']['paleomap'].get('map_age_ma')} Ma) used, not interpolated") + ". Amber = modern India outline (reference).")
        fig.savefig(out / f"recon_{k}_pm.png")
        plt.close(fig)
        n += 2
    return n


def india_movement():
    out = VP / "INDIA_PLATE_MOVEMENT"
    out.mkdir(parents=True, exist_ok=True)
    mot = json.loads((DATA / "india_gap_and_motion.json").read_text(encoding="utf-8"))
    ages = [250, 200, 150, 140, 120, 100, 90, 75, 66, 55, 40, 20, 0]
    cm = plt.get_cmap("plasma_r")
    fig = fig_new(11, 5.6)
    ax = fig.add_axes([0.04, 0.1, 0.55, 0.8])
    style(ax, (10, 130, -80, 50), "Indian Plate through time (EarthByte)")
    add(ax, load(DATA / "frames" / "0" / "continents.geojson"), "#2d4a3e", 0.5, z=1)
    for a in ages:
        fc = load(DATA / "frames" / key(a) / "india_outline_earthbyte.geojson")
        c = cm(a / 260)
        add(ax, fc, c, 0.35 if a else 0.7, edge=c, lw=1.0, z=3)
        if fc:
            xs, ys = [], []
            for f in fc["features"]:
                polys = [f["geometry"]["coordinates"]] if f["geometry"]["type"] == "Polygon" else f["geometry"]["coordinates"]
                for poly in polys:
                    for x, y in poly[0]:
                        xs.append(x)
                        ys.append(y)
            if xs:
                ax.text(sum(xs) / len(xs), sum(ys) / len(ys), f"{a}", color="white", fontsize=6.5, ha="center", va="center", zorder=7, weight="bold")
    tr = sorted([(float(k.replace("p", ".")), v["earthbyte"]["india"]) for k, v in mot["gap"].items() if v["earthbyte"]["india"]], key=lambda x: x[0])
    ax.plot([p[1] for _, p in tr], [p[0] for _, p in tr], color="white", lw=0.8, ls=":", zorder=6)
    ax2 = fig.add_axes([0.66, 0.56, 0.32, 0.34], facecolor="#0b1530")
    for m, c in (("earthbyte", "#fbbf24"), ("paleomap", "#38bdf8")):
        xs = sorted([(float(k.replace("p", ".")), v[m]["gap_km"]) for k, v in mot["gap"].items() if v[m]["gap_km"] is not None])
        ax2.plot([x for x, _ in xs], [y for _, y in xs], color=c, label=m)
    ax2.invert_xaxis()
    ax2.set_title("Distance India - Eurasia reference point (km)", color="white", fontsize=8, loc="left")
    ax2.tick_params(colors="#9fb3c8", labelsize=7)
    ax2.legend(fontsize=7, facecolor="#0b1530", labelcolor="white")
    ax3 = fig.add_axes([0.66, 0.1, 0.32, 0.34], facecolor="#0b1530")
    for m, c in (("earthbyte", "#fbbf24"), ("paleomap", "#38bdf8")):
        sp = mot["speed"][m]
        ax3.step([s["from_ma"] for s in sp], [s["cm_per_year"] for s in sp], color=c, where="mid", label=m)
    ax3.invert_xaxis()
    ax3.set_title("Indian Plate speed (cm/yr, model)", color="white", fontsize=8, loc="left")
    ax3.set_xlabel("Ma", color="#9fb3c8", fontsize=7)
    ax3.tick_params(colors="#9fb3c8", labelsize=7)
    foot(fig, LABEL + ". Rigid plates: shortening inside Eurasia/India not represented.")
    fig.savefig(out / "india_plate_journey.png")
    plt.close(fig)
    return 1


def himalaya():
    out = VP / "HIMALAYAN_EVOLUTION"
    out.mkdir(parents=True, exist_ok=True)
    mot = json.loads((DATA / "india_gap_and_motion.json").read_text(encoding="utf-8"))
    stages = [(130, "Break-up of Gondwana"), (100, "Northward motion, no Himalaya"), (66, "Approach to Eurasia"), (50, "Collision debated: 55-40 Ma"), (30, "Continued convergence"), (0, "Present day")]
    fig = fig_new(12, 6.2)
    for i, (a, t) in enumerate(stages):
        ax = fig.add_subplot(2, 3, i + 1)
        k = key(a)
        draw_eb(ax, k)
        g = mot["gap"][k]["earthbyte"]
        if g["eurasia"]:
            ax.plot(g["eurasia"][1], g["eurasia"][0], marker="*", color="#f87171", ms=9, zorder=9)
        style(ax, (20, 130, -70, 60), f"{a} Ma - {t}\nEurasia ref. star; gap {g['gap_km']:,} km (EarthByte)", small=True)
    fig.subplots_adjust(left=0.04, right=0.98, top=0.9, bottom=0.07, wspace=0.12, hspace=0.35)
    foot(fig, LABEL + ". Collision timing is debated; plate positions only, not mountains.")
    fig.savefig(out / "himalayan_formation_stages.png")
    plt.close(fig)
    return 1


def dinosaurs():
    out = VP / "DINOSAUR_ERA"
    out.mkdir(parents=True, exist_ok=True)
    fos = json.loads((DATA / "fossils.json").read_text(encoding="utf-8"))["records"]
    sl = [250, 230, 200, 180, 150, 130, 120, 100, 90, 75, 66]
    fig = fig_new(14, 9)
    for i, a in enumerate(sl):
        ax = fig.add_subplot(3, 4, i + 1)
        k = key(a)
        draw_eb(ax, k)
        pts = [r["recon"]["earthbyte"][k] for r in fos if r["minimum_age_ma"] <= a <= r["maximum_age_ma"] and k in r["recon"]["earthbyte"]]
        if pts:
            ax.scatter([p[1] for p in pts], [p[0] for p in pts], s=14, c="#fb923c", edgecolors="white", linewidths=0.5, zorder=10)
        style(ax, (10, 120, -80, 40), f"{a} Ma - PBDB records spanning this age: {len(pts)}", small=True)
    ax = fig.add_subplot(3, 4, 12)
    ax.axis("off")
    ax.text(0, 0.9, "India during the age of dinosaurs", color="white", fontsize=11, weight="bold", va="top")
    ax.text(0, 0.72, "Orange points: real Paleobiology Database\noccurrences of Dinosauria in India whose recorded\nage range includes the slice, carried to their\nreconstructed position. Absence of points is\nabsence of records, not of animals.\nAmber: Indian Plate.", color="#cbd5e1", fontsize=8, va="top")
    fig.subplots_adjust(left=0.03, right=0.99, top=0.95, bottom=0.05, wspace=0.12, hspace=0.3)
    foot(fig, LABEL + ". Fossils: PBDB (CC0), query base_name=Dinosauria cc=IN. Reconstruction: EarthByte / Zahirovic et al. 2022.")
    fig.savefig(out / "india_age_of_dinosaurs.png")
    plt.close(fig)
    return 1


def fossil_sites():
    out = VP / "FOSSIL_OCCURRENCES"
    out.mkdir(parents=True, exist_ok=True)
    fos = json.loads((DATA / "fossils.json").read_text(encoding="utf-8"))["records"]
    fig = fig_new(11, 5.8)
    ax = fig.add_axes([0.04, 0.08, 0.5, 0.82])
    style(ax, (66, 98, 6, 38), f"Modern find-spots of Indian dinosaur records in PBDB (n={len(fos)})")
    add(ax, load(DATA / "frames" / "0" / "continents.geojson"), "#2d4a3e", 0.9, z=1)
    cols = {"Triassic": "#a855f7", "Jurassic": "#22d3ee", "Cretaceous": "#fb923c"}
    for per, c in cols.items():
        pts = [(r["longitude"], r["latitude"]) for r in fos if r["geological_period"].startswith(per)]
        if pts:
            ax.scatter(*zip(*pts), s=18, c=c, edgecolors="white", linewidths=0.4, label=f"{per} ({len(pts)})", zorder=5)
    other = [(r["longitude"], r["latitude"]) for r in fos if not any(r["geological_period"].startswith(p) for p in cols)]
    if other:
        ax.scatter(*zip(*other), s=18, c="#94a3b8", edgecolors="white", linewidths=0.4, label=f"Other / mixed ({len(other)})", zorder=5)
    ax.legend(fontsize=7, facecolor="#0b1530", labelcolor="white", loc="lower left")
    ax2 = fig.add_axes([0.62, 0.08, 0.36, 0.82], facecolor="#0b1530")
    from collections import Counter

    c = Counter(r["state"] or "not stated" for r in fos).most_common(10)
    ax2.barh([k for k, _ in c][::-1], [v for _, v in c][::-1], color="#fb923c")
    ax2.set_title("Records by state (top 10)", color="white", fontsize=9, loc="left")
    ax2.tick_params(colors="#9fb3c8", labelsize=7)
    foot(fig, "Data: The Paleobiology Database (CC0). Modern coordinates exactly as recorded; coordinate precision is given per record in data_quality. Not a satellite observation.")
    fig.savefig(out / "pbdb_india_dinosaur_occurrences.png")
    plt.close(fig)
    return 1


if __name__ == "__main__":
    n = frame_previews() + india_movement() + himalaya() + dinosaurs() + fossil_sites()
    print("previews written:", n, "->", VP)
