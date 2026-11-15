"""PNG previews rendered from the real rasters: one per observation, before/after, change maps and an India overview.

Output: datasets/india_historical_atlas/previews/<dataset_id>/{observation_<date>.png, before_after_<variable>.png,
change_<variable>.png} and previews/india_overview.png. Every image carries its data label; nothing is drawn that is not in a raster
or boundary file. Run:  python scripts/generate_previews.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from atlas_common import ATLAS, now_iso, read_json, write_json  # noqa: E402
from app.explorer.rendering import DIFF_COLORS, HATCH, OBS_COLORS  # noqa: E402

OUT = ATLAS / "previews"
MAXPX = 900
BG = (11, 20, 38)
FONT = ImageFont.load_default(size=15)
SMALL = ImageFont.load_default(size=12)
LEGEND_DIFF = [((56, 139, 253), "unchanged"), ((230, 57, 70), "lost"), ((46, 204, 113), "gained"), ((122, 128, 140), "other")]


def colorize(arr: np.ndarray, uncertain: int) -> Image.Image:
    rgb = np.zeros((*arr.shape, 3), np.uint8)
    rgb[:] = BG
    for code, c in OBS_COLORS.items():
        rgb[arr == code] = c[:3]
    r, c = np.indices(arr.shape)
    rgb[(arr == uncertain) & (((r + c) % 6) < 2)] = HATCH[:3]
    return fit(Image.fromarray(rgb))


def fit(img: Image.Image) -> Image.Image:
    s = MAXPX / max(img.size)
    return img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.NEAREST)


def framed(img: Image.Image, title: str, subtitle: str, legend: list[tuple[tuple[int, int, int], str]]) -> Image.Image:
    h = 52
    leg = 24 + 20 * ((len(legend) + 2) // 3) if legend else 8
    canvas = Image.new("RGB", (max(img.width, 520), img.height + h + leg), BG)
    canvas.paste(img, (0, h))
    d = ImageDraw.Draw(canvas)
    d.text((8, 6), title, fill=(230, 238, 250), font=FONT)
    d.text((8, 28), subtitle, fill=(150, 170, 200), font=SMALL)
    for i, (c, name) in enumerate(legend):
        x, y = 8 + (i % 3) * 250, h + img.height + 10 + (i // 3) * 20
        d.rectangle([x, y, x + 12, y + 12], fill=c)
        d.text((x + 18, y - 1), name, fill=(200, 212, 230), font=SMALL)
    return canvas


def read(path: Path) -> np.ndarray:
    with rasterio.open(path) as s:
        return s.read(1)


def class_legend(d: dict, present: set[int]) -> list[tuple[tuple[int, int, int], str]]:
    out = []
    for k, name in d["classes"].items():
        k = int(k)
        if k in present and k in OBS_COLORS:
            out.append((OBS_COLORS[k][:3], name))
    return out


def side_by_side(a: Image.Image, b: Image.Image, la: str, lb: str) -> Image.Image:
    gap = 12
    w = Image.new("RGB", (a.width + b.width + gap, max(a.height, b.height) + 24), BG)
    w.paste(a, (0, 24))
    w.paste(b, (a.width + gap, 24))
    d = ImageDraw.Draw(w)
    d.text((6, 4), la, fill=(230, 238, 250), font=FONT)
    d.text((a.width + gap + 6, 4), lb, fill=(230, 238, 250), font=FONT)
    return w


def dataset_previews(f: Path) -> list[dict]:
    d = read_json(f)
    root = f.parent
    unc = d.get("uncertain_value", 255)
    label = d.get("public_label", "")
    made: list[dict] = []
    out = OUT / d["id"]
    out.mkdir(parents=True, exist_ok=True)
    imgs: dict[str, np.ndarray] = {}
    for o in d["observations"]:
        arr = read(root / o["file"])
        imgs[o["date"]] = arr
        present = {int(v) for v in np.unique(arr)}
        im = framed(colorize(arr, unc), f"{d['name']}: {o['date']}", f"{label} · {d['source']}", class_legend(d, present))
        p = out / f"observation_{o['date']}.png"
        im.save(p, optimize=True)
        made.append({"kind": "observation", "date": o["date"], "file": str(p.relative_to(ATLAS)).replace("\\", "/")})
    dates = sorted(imgs)
    if len(dates) >= 2:
        a, b = dates[0], dates[-1]
        union = set(np.unique(imgs[a]).tolist()) | set(np.unique(imgs[b]).tolist())
        sbs = side_by_side(colorize(imgs[a], unc), colorize(imgs[b], unc), a, b)
        im = framed(sbs, f"{d['name']}: before and after", f"{label} · first vs last observation, same footprint and colours", class_legend(d, union))
        p = out / "before_after.png"
        im.save(p, optimize=True)
        made.append({"kind": "before_after", "dates": [a, b], "file": str(p.relative_to(ATLAS)).replace("\\", "/")})
    for tif in sorted((root / "change").glob("*.difference.tif")) if (root / "change").exists() else []:
        diff = read(tif)
        rgb = np.zeros((*diff.shape, 3), np.uint8)
        rgb[:] = BG
        for code, c in DIFF_COLORS.items():
            rgb[diff == code] = c[:3]
        r, c = np.indices(diff.shape)
        rgb[(diff == 0) & (((r + c) % 6) < 2)] = HATCH[:3]
        stem = tif.name.replace(".difference.tif", "")
        summ = read_json(root / "change" / f"{stem}.summary.json", {})
        var = (summ.get("variable") or {}).get("label", stem)
        net = (summ.get("areas") or {}).get("net_ha")
        sub = f"{label} · {summ.get('outcome', '')}" + (f" · net {net:+,.0f} ha" if isinstance(net, (int, float)) else "")
        im = framed(fit(Image.fromarray(rgb)), f"{d['name']}: change in {var}", sub, LEGEND_DIFF)
        p = out / f"change_{stem}.png"
        im.save(p, optimize=True)
        made.append({"kind": "change", "variable": stem, "file": str(p.relative_to(ATLAS)).replace("\\", "/")})
    return made


def india_overview(datasets: list[dict]) -> str | None:
    states = ATLAS / "geographical_boundaries" / "states"
    files = sorted(states.glob("*.geojson")) if states.exists() else []
    if not files:
        return None
    W, H = 760, 820
    west, east, south, north = 67.5, 98.5, 6.0, 37.5
    px = lambda lon, lat: ((lon - west) / (east - west) * W, (north - lat) / (north - south) * H)  # noqa: E731
    im = Image.new("RGB", (W, H + 70), BG)
    d = ImageDraw.Draw(im)

    def draw(geom: dict) -> None:
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]] if geom["type"] == "Polygon" else []
        for poly in polys:
            for ring in poly[:1]:
                pts = [px(x, y) for x, y in ring]
                d.polygon(pts, fill=(22, 40, 70), outline=(70, 100, 150))

    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        for ft in data.get("features", [data]):
            if ft.get("geometry"):
                draw(ft["geometry"])
    for ds in datasets:
        w, s, e, n = ds["bbox"]
        x0, y1 = px(w, s)
        x1, y0 = px(e, n)
        c = (255, 190, 70) if ds["designation"] == "illustrative" else (80, 220, 150)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rr = 6 if ds["designation"] == "illustrative" else 10
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=c, width=2)
    d.text((10, H + 8), "NASAX India Historical Atlas: dataset footprints", fill=(230, 238, 250), font=FONT)
    d.ellipse([12, H + 36, 24, H + 48], outline=(80, 220, 150), width=2)
    d.text((30, H + 34), "Satellite Observations", fill=(200, 212, 230), font=SMALL)
    d.ellipse([220, H + 36, 232, H + 48], outline=(255, 190, 70), width=2)
    d.text((238, H + 34), "Illustrative Dataset", fill=(200, 212, 230), font=SMALL)
    p = OUT / "india_overview.png"
    im.save(p, optimize=True)
    return str(p.relative_to(ATLAS)).replace("\\", "/")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    index: dict = {"generated_at": now_iso(), "datasets": {}}
    metas = []
    for f in sorted((ATLAS / "processed").rglob("dataset.json")):
        d = read_json(f)
        metas.append({"id": d["id"], "bbox": d["bbox"], "designation": d.get("designation")})
        index["datasets"][d["id"]] = dataset_previews(f)
        print(f"{d['id']}: {len(index['datasets'][d['id']])} previews")
    index["india_overview"] = india_overview(metas)
    write_json(OUT / "index.json", index)
    print("wrote previews/index.json; overview:", index["india_overview"])


if __name__ == "__main__":
    main()
