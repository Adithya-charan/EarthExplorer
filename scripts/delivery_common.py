"""Shared helpers for the complete dataset delivery (build_complete_delivery.py and finalize_delivery.py)."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from atlas_common import ATLAS, DOC, REGION_BBOX, ROOT, now_iso, read_json, sha256, write_json  # noqa: E402,F401

OUT_ROOT = Path(os.environ.get("NASAX_DELIVERY_OUT", "F:/NASAX_DELIVERY_OUTPUT"))
PKG = OUT_ROOT / "NASAX_COMPLETE_DATASET_DELIVERY"
REGION_DIR = {"himalayas": "HIMALAYAS", "sundarbans": "SUNDARBANS", "hyderabad": "HYDERABAD", "bengaluru": "BENGALURU"}
REGION_NAME = {"himalayas": "Indian Himalayas, Dhauliganga catchment", "sundarbans": "Indian Sundarbans", "hyderabad": "Hyderabad metropolitan region", "bengaluru": "Bellandur Lake, Bengaluru"}
BG = (11, 20, 38)
FONT = ImageFont.load_default(size=15)
SMALL = ImageFont.load_default(size=12)

# Class colours: identical to backend/app/explorer/rendering.py so previews match the application.
from app.explorer.rendering import DIFF_COLORS, HATCH, OBS_COLORS  # noqa: E402


def region_of(root: Path) -> str:
    return root.parent.name if root.parent.name not in ("synthetic", "official") else root.name


def datasets() -> list[dict]:
    out = []
    for f in sorted((ATLAS / "processed").rglob("dataset.json")):
        d = read_json(f)
        d["_dir"] = f.parent
        d["_region"] = region_of(f.parent)
        d["_official"] = d.get("designation") != "illustrative"
        out.append(d)
    return out


def rel(p: Path, base: Path = PKG) -> str:
    return str(p.relative_to(base)).replace("\\", "/")


def cp(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def jdump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else [])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def raster_info(path: str | Path) -> dict:
    """Facts read from the file itself (never typed in)."""
    with rasterio.open(path) as s:
        res = s.res
        return {
            "format": s.driver, "crs": s.crs.to_string() if s.crs else "", "width": s.width, "height": s.height, "dimensions": f"{s.width} x {s.height}", "bands": s.count,
            "dtype": s.dtypes[0], "nodata": s.nodata, "resolution_deg": round(res[0], 12) if s.crs and s.crs.is_geographic else None, "resolution_m": round(res[0], 3) if s.crs and s.crs.is_projected else None,
            "bounds": [round(v, 6) for v in s.bounds], "tiled": bool(s.profile.get("tiled")), "overviews": s.overviews(1) if s.count else [], "compression": str(s.compression.value) if s.compression else "",
            "layout": s.tags(ns="IMAGE_STRUCTURE").get("LAYOUT", ""), "tags": s.tags(),
        }


def approx_res_m(info: dict) -> str:
    if info.get("resolution_m"):
        return f"{info['resolution_m']:.1f} m"
    if info.get("resolution_deg"):
        lat = (info["bounds"][1] + info["bounds"][3]) / 2
        return f"~{info['resolution_deg'] * 111320 * math.cos(math.radians(lat)):.1f} m ({info['resolution_deg']:.8g} deg)"
    return ""


def write_geotiff_plain(src: Path, dst: Path, tags: dict | None = None) -> None:
    """A plain (striped, no overviews) compressed GeoTIFF copy of a raster, values and georeferencing unchanged."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(src) as s:
        prof = s.profile.copy()
        prof.update(driver="GTiff", tiled=False, compress="DEFLATE")
        for k in ("blockxsize", "blockysize"):
            prof.pop(k, None)
        data = s.read()
        t = s.tags()
        with rasterio.open(dst, "w", **prof) as d:
            d.write(data)
            d.update_tags(**(t | (tags or {})))


def write_cog(src: Path, dst: Path, resampling: str = "NEAREST") -> None:
    import rasterio.shutil as sh

    dst.parent.mkdir(parents=True, exist_ok=True)
    sh.copy(str(src), str(dst), driver="COG", compress="DEFLATE", overview_resampling=resampling, blocksize=256)


def class_legend(classes: dict, present: set[int] | None = None) -> list[tuple[tuple[int, int, int], str]]:
    out = []
    for k, name in classes.items():
        k = int(k)
        if k in OBS_COLORS and (present is None or k in present):
            out.append((OBS_COLORS[k][:3], name))
    return out


def fit(img: Image.Image, maxpx: int = 900) -> Image.Image:
    s = maxpx / max(img.size)
    if s >= 1:
        return img
    return img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.NEAREST)


def framed(img: Image.Image, title: str, subtitle: str, legend: list[tuple[tuple[int, int, int], str]], footer: str = "") -> Image.Image:
    h = 52
    cols = 3
    leg = 14 + 20 * ((len(legend) + cols - 1) // cols) + (18 if footer else 0) if legend or footer else 6
    canvas = Image.new("RGB", (max(img.width, 640), img.height + h + leg), BG)
    canvas.paste(img, (0, h))
    d = ImageDraw.Draw(canvas)
    d.text((8, 6), title, fill=(230, 238, 250), font=FONT)
    d.text((8, 28), subtitle, fill=(150, 170, 200), font=SMALL)
    for i, (c, name) in enumerate(legend):
        x, y = 8 + (i % cols) * 250, h + img.height + 8 + (i // cols) * 20
        d.rectangle([x, y, x + 12, y + 12], fill=c)
        d.text((x + 18, y - 1), name, fill=(200, 212, 230), font=SMALL)
    if footer:
        d.text((8, canvas.height - 18), footer, fill=(140, 156, 184), font=SMALL)
    return canvas


def colorize_classes(arr: np.ndarray, uncertain: int = 255) -> Image.Image:
    rgb = np.zeros((*arr.shape, 3), np.uint8)
    rgb[:] = BG
    for code, c in OBS_COLORS.items():
        rgb[arr == code] = c[:3]
    r, c = np.indices(arr.shape)
    rgb[(arr == uncertain) & (((r + c) % 6) < 2)] = HATCH[:3]
    return fit(Image.fromarray(rgb))


def line_chart(series: dict[str, list[tuple[str, float]]], title: str, ylabel: str, subtitle: str = "") -> Image.Image:
    """A simple labelled line chart (dates on x, measured values on y) drawn with PIL."""
    W, H, L, R, T, B = 900, 460, 80, 30, 70, 70
    im = Image.new("RGB", (W, H), (250, 251, 253))
    d = ImageDraw.Draw(im)
    d.text((14, 10), title, fill=(15, 25, 45), font=FONT)
    if subtitle:
        d.text((14, 32), subtitle, fill=(90, 100, 120), font=SMALL)
    pts = [("", v) for vs in series.values() for v in vs]
    if not pts:
        return im
    dates = sorted({p[1][0] for p in pts})
    vals = [p[1][1] for p in pts]
    lo, hi = min(0.0, min(vals)), max(vals) * 1.08 or 1.0
    x = lambda dt: L + (dates.index(dt) / max(1, len(dates) - 1)) * (W - L - R)  # noqa: E731
    y = lambda v: H - B - (v - lo) / ((hi - lo) or 1) * (H - T - B)  # noqa: E731
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        d.line([(L, y(v)), (W - R, y(v))], fill=(225, 230, 238))
        d.text((6, y(v) - 6), f"{v:,.0f}", fill=(80, 90, 110), font=SMALL)
    for dt in dates:
        d.line([(x(dt), H - B), (x(dt), H - B + 4)], fill=(120, 130, 150))
        d.text((x(dt) - 22, H - B + 8), dt[:7] if len(dt) > 4 else dt, fill=(80, 90, 110), font=SMALL)
    palette = [(36, 99, 235), (220, 60, 60), (30, 160, 90), (200, 130, 20), (130, 70, 190), (20, 150, 170)]
    for n, (name, vs) in enumerate(series.items()):
        c = palette[n % len(palette)]
        xy = [(x(dt), y(v)) for dt, v in vs]
        if len(xy) > 1:
            d.line(xy, fill=c, width=3)
        for px, py in xy:
            d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=c)
        d.rectangle([L + n * 190, H - 28, L + n * 190 + 12, H - 16], fill=c)
        d.text((L + n * 190 + 18, H - 30), name[:24], fill=(40, 50, 70), font=SMALL)
    d.text((L, T - 20), ylabel, fill=(90, 100, 120), font=SMALL)
    return im


def simple_pdf(path: Path, title: str, blocks: list[tuple], landscape_page: bool = False) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    small = st["BodyText"].clone("s", fontSize=7.5, leading=9.5)
    size = landscape(A4) if landscape_page else A4
    width = size[0] - 72
    story = [Paragraph(title, st["Title"]), Paragraph(f"Generated {now_iso()}", small), Spacer(1, 8)]
    for b in blocks:
        k = b[0]
        if k == "h":
            story += [Spacer(1, 6), Paragraph(b[1], st["Heading2"])]
        elif k == "h3":
            story += [Paragraph(b[1], st["Heading3"])]
        elif k == "p":
            story += [Paragraph(b[1], st["BodyText"]), Spacer(1, 4)]
        elif k == "small":
            story += [Paragraph(b[1], small), Spacer(1, 3)]
        elif k == "table":
            rows = [[Paragraph(str(c), small) for c in r] for r in b[1]]
            t = Table(rows, repeatRows=1, colWidths=b[2] if len(b) > 2 and b[2] else None)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9e4f5")), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [t, Spacer(1, 6)]
        elif k == "img":
            p = Path(b[1])
            if p.exists():
                with Image.open(p) as im:
                    w, h = im.size
                sc = min(width / w, (b[2] if len(b) > 2 else 380) / h)
                story += [RLImage(str(p), width=w * sc, height=h * sc), Paragraph(b[3] if len(b) > 3 else p.name, small), Spacer(1, 6)]
        elif k == "pb":
            story.append(PageBreak())
    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=size, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36, title=title).build(story)
