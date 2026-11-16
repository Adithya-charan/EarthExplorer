"""Build the additional regional datasets (more Indian states) from the downloaded official GHSL and JRC tiles.

Each place below is clipped from the tile that fully contains its analysis window; the tile is chosen from the real raster
bounds recorded in source_registry.json (GHSL tiles are offset from whole degrees, so the tile name alone is not enough).
A dataset whose result is empty (no built-up cells, or no water at either end) is removed and reported, never kept.

Run:  python scripts/process_satellite_data.py --new-regions
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from process_satellite_data import PROC, build_ghsl, build_jrc_transitions  # noqa: E402

GHSL_TILES = ["R8_C26", "R8_C27", "R7_C26", "R7_C27", "R9_C26"]
JRC_TILES = ["70E_20N", "80E_20N", "70E_30N", "80E_30N", "70E_10N"]

# (name, state folder, state label, window west/south/east/north, centre lat/lon, extra aliases)
CITIES = [
    ("Chennai", "tamil_nadu", "Tamil Nadu", (80.05, 12.85, 80.45, 13.25), (13.0827, 80.2707), []),
    ("Coimbatore", "tamil_nadu", "Tamil Nadu", (76.85, 10.90, 77.10, 11.15), (11.0168, 76.9558), []),
    ("Madurai", "tamil_nadu", "Tamil Nadu", (78.00, 9.80, 78.25, 10.05), (9.9252, 78.1198), []),
    ("Kanyakumari", "tamil_nadu", "Tamil Nadu", (77.40, 8.05, 77.70, 8.30), (8.0883, 77.5385), []),
    ("Visakhapatnam", "andhra_pradesh", "Andhra Pradesh", (83.05, 17.55, 83.50, 17.90), (17.6868, 83.2185), ["vizag"]),
    ("Vijayawada", "andhra_pradesh", "Andhra Pradesh", (80.50, 16.40, 80.80, 16.65), (16.5062, 80.6480), []),
    ("Kochi", "kerala", "Kerala", (76.15, 9.85, 76.45, 10.10), (9.9312, 76.2673), ["cochin"]),
    ("Thiruvananthapuram", "kerala", "Kerala", (76.80, 8.35, 77.15, 8.65), (8.5241, 76.9366), ["trivandrum"]),
    ("Kozhikode", "kerala", "Kerala", (75.70, 11.15, 75.90, 11.35), (11.2588, 75.7804), ["calicut"]),
    ("Mangaluru", "karnataka", "Karnataka", (74.75, 12.80, 74.95, 12.98), (12.9141, 74.8560), ["mangalore"]),
    ("Mysuru", "karnataka", "Karnataka", (76.55, 12.20, 76.75, 12.40), (12.2958, 76.6394), ["mysore"]),
    ("Panaji", "goa", "Goa", (73.70, 15.40, 74.05, 15.60), (15.4909, 73.8278), ["panjim", "goa"]),
    ("Pune", "maharashtra", "Maharashtra", (73.70, 18.40, 74.00, 18.65), (18.5204, 73.8567), []),
    ("Nagpur", "maharashtra", "Maharashtra", (78.95, 21.05, 79.25, 21.25), (21.1458, 79.0882), []),
    ("Surat", "gujarat", "Gujarat", (72.70, 21.05, 72.95, 21.30), (21.1702, 72.8311), []),
    ("Ahmedabad", "gujarat", "Gujarat", (72.40, 22.90, 72.80, 23.20), (23.0225, 72.5714), []),
    ("Jaipur", "rajasthan", "Rajasthan", (75.65, 26.75, 75.95, 27.05), (26.9124, 75.7873), []),
    ("Delhi NCR", "delhi", "Delhi", (76.85, 28.35, 77.50, 28.90), (28.6139, 77.2090), ["delhi", "new delhi", "national capital region"]),
    ("Bhopal", "madhya_pradesh", "Madhya Pradesh", (77.30, 23.15, 77.55, 23.35), (23.2599, 77.4126), []),
    ("Lucknow", "uttar_pradesh", "Uttar Pradesh", (80.80, 26.70, 81.10, 27.00), (26.8467, 80.9462), []),
    ("Patna", "bihar", "Bihar", (85.00, 25.50, 85.30, 25.75), (25.5941, 85.1376), []),
    ("Bhubaneswar", "odisha", "Odisha", (85.65, 20.15, 85.95, 20.45), (20.2961, 85.8245), []),
    ("Kolkata", "west_bengal", "West Bengal", (88.15, 22.40, 88.55, 22.80), (22.5726, 88.3639), ["calcutta"]),
    ("Raipur", "chhattisgarh", "Chhattisgarh", (81.50, 21.15, 81.80, 21.40), (21.2514, 81.6296), []),
]

# (name, state folder, state label, window, centre, extra aliases)
WATER = [
    ("Chilika Lake", "odisha", "Odisha", (85.05, 19.45, 85.48, 19.95), (19.72, 85.32), ["chilka lake", "chilika"]),
    ("Hirakud Reservoir", "odisha", "Odisha", (83.60, 21.45, 84.05, 21.95), (21.53, 83.87), ["hirakud", "hirakud dam"]),
    ("Pulicat Lake", "andhra_pradesh", "Andhra Pradesh and Tamil Nadu", (80.00, 13.40, 80.24, 13.85), (13.67, 80.17), ["pulicat"]),
    ("Kolleru Lake", "andhra_pradesh", "Andhra Pradesh", (81.00, 16.45, 81.40, 16.75), (16.62, 81.20), ["kolleru"]),
    ("Nagarjuna Sagar", "andhra_pradesh", "Telangana and Andhra Pradesh", (79.05, 16.45, 79.50, 16.80), (16.5756, 79.3110), ["nagarjuna sagar reservoir", "nagarjuna sagar dam"]),
    ("Vembanad Lake", "kerala", "Kerala", (76.30, 9.45, 76.55, 9.90), (9.60, 76.40), ["vembanad", "kochi backwaters"]),
    ("Ashtamudi Lake", "kerala", "Kerala", (76.54, 8.92, 76.66, 9.06), (8.98, 76.59), ["ashtamudi"]),
    ("Krishnaraja Sagara", "karnataka", "Karnataka", (76.45, 12.35, 76.65, 12.55), (12.4244, 76.5722), ["krs reservoir", "krishnarajasagara", "krs dam"]),
    ("Tungabhadra Reservoir", "karnataka", "Karnataka", (76.20, 15.10, 76.50, 15.40), (15.2686, 76.3366), ["tungabhadra dam", "tungabhadra"]),
    ("Ujani Reservoir", "maharashtra", "Maharashtra", (74.95, 17.95, 75.30, 18.25), (18.07, 75.12), ["ujani dam", "bhima reservoir"]),
    ("Sambhar Lake", "rajasthan", "Rajasthan", (74.85, 26.85, 75.25, 27.05), (26.97, 75.08), ["sambhar salt lake"]),
    ("Nal Sarovar", "gujarat", "Gujarat", (71.85, 22.65, 72.20, 22.95), (22.80, 72.03), ["nal sarovar bird sanctuary"]),
    ("Gandhi Sagar", "madhya_pradesh", "Madhya Pradesh", (75.40, 24.55, 75.75, 24.85), (24.70, 75.55), ["gandhi sagar reservoir"]),
    ("Upper Lake Bhopal", "madhya_pradesh", "Madhya Pradesh", (77.30, 23.19, 77.48, 23.30), (23.25, 77.37), ["bhoj wetland", "upper lake"]),
]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def pick_tile(reg: dict, kind: str, bbox, tiles: list[str]) -> str:
    w, s, e, n = bbox
    for t in tiles:
        rid = f"ghsl_built_s_2020_{t}" if kind == "ghsl" else f"jrc_gsw_transitions_{t}"
        b = reg[rid]["inspection"]["bounds"]
        if b[0] <= w and b[1] <= s and e <= b[2] and n <= b[3]:
            return t
    raise SystemExit(f"No downloaded {kind} tile fully contains window {bbox}")


def build_all(reg: dict) -> None:
    kept, dropped = [], []
    for name, folder, state, bbox, loc, extra in CITIES:
        ds_id = f"ghsl-built-up-{slug(name)}"
        tile = pick_tile(reg, "ghsl", bbox, GHSL_TILES)
        aliases = sorted({name.lower(), f"{name.lower()} metro", f"{name.lower()} metropolitan area", *[a.lower() for a in extra]})
        build_ghsl(folder, ds_id, f"{name} metropolitan area (GHSL built-up)", f"{state}, India", bbox, aliases, loc, reg, tile=tile)
        d = json.loads((PROC / folder / ds_id / "dataset.json").read_text(encoding="utf-8"))
        built = [o["class_area_ha"].get("Built-up (at least 15% of the cell)", 0) for o in d["observations"]]
        if max(built) <= 0:
            shutil.rmtree(PROC / folder / ds_id)
            dropped.append((ds_id, "no built-up cells"))
        else:
            kept.append((ds_id, tile, built))
    for name, folder, state, bbox, loc, extra in WATER:
        ds_id = f"jrc-water-{slug(name)}"
        tile = pick_tile(reg, "jrc", bbox, JRC_TILES)
        aliases = sorted({name.lower(), *[a.lower() for a in extra]})
        build_jrc_transitions(folder, ds_id, f"{name} (JRC surface water)", f"{state}, India", bbox, aliases, loc, reg, tile=tile)
        d = json.loads((PROC / folder / ds_id / "dataset.json").read_text(encoding="utf-8"))
        water = [o["class_area_ha"].get("Water", 0) for o in d["observations"]]
        if max(water) < 20:  # under 20 ha at both ends: nothing meaningful to compare
            shutil.rmtree(PROC / folder / ds_id)
            dropped.append((ds_id, f"water area {water} ha"))
        else:
            kept.append((ds_id, tile, water))
    print("\nKEPT")
    for k in kept:
        print(" ", k)
    print("DROPPED")
    for k in dropped:
        print(" ", k)
