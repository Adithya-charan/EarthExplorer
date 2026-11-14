"""Download the Natural Earth layers used by the Earth Explorer and record where they came from.

Natural Earth (https://www.naturalearthdata.com) is public-domain cartographic data. This script fetches
the zipped shapefiles from the project's official download host, unpacks them into
``backend/data/naturalearth/<layer>/`` and writes ``manifest.json`` (source URL, size, SHA-256, date).

Usage (from ``backend/``)::

    python scripts/fetch_natural_earth.py            # download anything missing
    python scripts/fetch_natural_earth.py --force    # re-download everything

Nothing is downloaded at application start-up; the API only reads these local files.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data" / "naturalearth"
BASE_URL = "https://naciscdn.org/naturalearth"
USER_AGENT = "geo-explorer-dev/0.1 (data fetch script)"

# (scale, category, name, what it is used for)
LAYERS: list[tuple[str, str, str, str]] = [
    ("50m", "cultural", "admin_0_countries", "country polygons, names, continents"),
    ("50m", "cultural", "admin_0_map_units", "map units (separates e.g. French Guiana from France) for continent shapes"),
    ("10m", "cultural", "admin_1_states_provinces", "states / provinces"),
    ("10m", "cultural", "populated_places_simple", "cities and towns (points)"),
    ("10m", "physical", "geography_marine_polys", "oceans, seas, gulfs, bays"),
    ("10m", "physical", "geography_regions_polys", "mountain ranges, deserts, plateaus, peninsulas, ..."),
    ("10m", "physical", "geography_regions_points", "named physical regions without a polygon"),
    ("10m", "physical", "geography_regions_elevation_points", "named peaks with elevation"),
    ("10m", "physical", "rivers_lake_centerlines", "river centre lines"),
    ("10m", "physical", "lakes", "lake polygons"),
]


def layer_dirname(scale: str, name: str) -> str:
    return f"ne_{scale}_{name}"


def url_for(scale: str, category: str, name: str) -> str:
    return f"{BASE_URL}/{scale}/{category}/ne_{scale}_{name}.zip"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="download again even if the layer exists")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = DATA_DIR / "manifest.json"
    manifest: dict = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    layers: dict = manifest.setdefault("layers", {})
    manifest["source"] = "Natural Earth (public domain), https://www.naturalearthdata.com"

    failures = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120.0, follow_redirects=True) as client:
        for scale, category, name, purpose in LAYERS:
            key = layer_dirname(scale, name)
            target = DATA_DIR / key
            if target.is_dir() and any(target.glob("*.shp")) and key in layers and not args.force:
                print(f"  have  {key}")
                continue
            url = url_for(scale, category, name)
            print(f"  fetch {key}  <-  {url}")
            try:
                response = client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"    FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
                failures += 1
                continue
            content = response.content
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for member in zf.namelist():
                    # Flatten and refuse anything that is not a plain file name (zip-slip protection).
                    base = Path(member).name
                    if not base or base != member:
                        continue
                    (target / base).write_bytes(zf.read(member))
            layers[key] = {
                "url": url,
                "scale": scale,
                "category": category,
                "purpose": purpose,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            print(f"    ok  {len(content) / 1024 / 1024:.2f} MB")

    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Manifest written to {manifest_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
