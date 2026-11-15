"""Download genuine official sample data and record its provenance in source_registry.json.

Nothing here is simulated. Each entry is only marked VERIFIED_DOWNLOADED after the file was fetched and opened.
Statuses: VERIFIED_DOWNLOADED, VERIFIED_METADATA_ONLY, ACCESS_REQUIRES_AUTHENTICATION, NOT_ACCESSED.

Usage:  python scripts/download_official_data.py [--only SOURCE_ID ...] [--skip-large]
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import httpx
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atlas_common import ATLAS, DOC, now_iso, read_json, sha256, today, write_json  # noqa: E402

OFFICIAL = ATLAS / "official"

# Every URL below was requested during development and answered with the stated size; see the registry for the recorded result.
FILES = [
    dict(
        id="jrc_gsw_occurrence_70E_20N", name="JRC Global Surface Water - Occurrence (v1.4, 2021 release), tile 70E_20N",
        org="European Commission Joint Research Centre (JRC)", dataset_url="https://global-surface-water.appspot.com/download",
        collection="JRC/GSW1_4/GlobalSurfaceWater (occurrence layer)", region="bengaluru", used_by=["bengaluru", "hyderabad"],
        url="https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_70E_20Nv1_4_2021.tif",
        temporal="1984-03 to 2021-12 (occurrence = share of valid observations with water)", resolution="30 m (1 arc-second)", fmt="GeoTIFF",
        license="Free and open; cite Pekel et al. (2016) Nature 540, 418-422 (JRC Global Surface Water Explorer terms).",
        covers=[70, 10, 80, 20], variable="water occurrence (%)",
    ),
    dict(
        id="jrc_gsw_transitions_70E_20N", name="JRC Global Surface Water - Transitions (v1.4, 2021 release), tile 70E_20N",
        org="European Commission Joint Research Centre (JRC)", dataset_url="https://global-surface-water.appspot.com/download",
        collection="JRC/GSW1_4/GlobalSurfaceWater (transition layer)", region="bengaluru", used_by=["bengaluru", "hyderabad"],
        url="https://storage.googleapis.com/global-surface-water/downloads2021/transitions/transitions_70E_20Nv1_4_2021.tif",
        temporal="First year (1984) versus last year (2021) water class transition", resolution="30 m (1 arc-second)", fmt="GeoTIFF",
        license="Free and open; cite Pekel et al. (2016) Nature 540, 418-422.", covers=[70, 10, 80, 20], variable="water class transition",
    ),
    dict(
        id="jrc_gsw_occurrence_80E_30N", name="JRC Global Surface Water - Occurrence (v1.4, 2021 release), tile 80E_30N",
        org="European Commission Joint Research Centre (JRC)", dataset_url="https://global-surface-water.appspot.com/download",
        collection="JRC/GSW1_4/GlobalSurfaceWater (occurrence layer)", region="sundarbans", used_by=["sundarbans"], large=True,
        url="https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_80E_30Nv1_4_2021.tif",
        temporal="1984-03 to 2021-12", resolution="30 m (1 arc-second)", fmt="GeoTIFF",
        license="Free and open; cite Pekel et al. (2016) Nature 540, 418-422.", covers=[80, 20, 90, 30], variable="water occurrence (%)",
    ),
    *[
        dict(
            id=f"ghsl_built_s_{y}_R8_C26", name=f"GHSL GHS-BUILT-S R2023A, epoch {y}, tile R8_C26 (3 arc-second, EPSG:4326)",
            org="European Commission Joint Research Centre (JRC), Global Human Settlement Layer",
            dataset_url="https://human-settlement.emergency.copernicus.eu/ghs_buE2023.php", collection=f"GHS_BUILT_S_E{y}_GLOBE_R2023A_4326_3ss_V1_0",
            region="hyderabad", used_by=["hyderabad", "bengaluru"],
            url=f"https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_BUILT_S_GLOBE_R2023A/GHS_BUILT_S_E{y}_GLOBE_R2023A_4326_3ss/V1-0/tiles/GHS_BUILT_S_E{y}_GLOBE_R2023A_4326_3ss_V1_0_R8_C26.zip",
            temporal=f"Epoch {y} (modelled from Landsat and Sentinel-2)", resolution="3 arc-seconds (about 90 m)", fmt="GeoTIFF in ZIP",
            license="CC BY 4.0 (European Commission reuse policy); cite Pesaresi and Politis (2023), GHS-BUILT-S R2023A.",
            covers=[70, 10, 80, 20], variable="built-up surface (m2 per cell)", large=(y == 2020),
        )
        for y in (2000, 2010, 2020)
    ],
    # Additional GHSL tiles (same product, same epochs) covering more of India.
    *[
        dict(
            id=f"ghsl_built_s_{y}_{tile}", name=f"GHSL GHS-BUILT-S R2023A, epoch {y}, tile {tile} (3 arc-second, EPSG:4326)",
            org="European Commission Joint Research Centre (JRC), Global Human Settlement Layer",
            dataset_url="https://human-settlement.emergency.copernicus.eu/ghs_buE2023.php", collection=f"GHS_BUILT_S_E{y}_GLOBE_R2023A_4326_3ss_V1_0",
            region=region, used_by=[region],
            url=f"https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_BUILT_S_GLOBE_R2023A/GHS_BUILT_S_E{y}_GLOBE_R2023A_4326_3ss/V1-0/tiles/GHS_BUILT_S_E{y}_GLOBE_R2023A_4326_3ss_V1_0_{tile}.zip",
            temporal=f"Epoch {y} (modelled from Landsat and Sentinel-2)", resolution="3 arc-seconds (about 90 m)", fmt="GeoTIFF in ZIP",
            license="CC BY 4.0 (European Commission reuse policy); cite Pesaresi and Politis (2023), GHS-BUILT-S R2023A.",
            covers=cover, variable="built-up surface (m2 per cell)",
        )
        for tile, region, cover in (("R8_C27", "south_east", [80, 10, 90, 20]), ("R7_C26", "north_west", [70, 20, 80, 30]), ("R7_C27", "north_east", [80, 20, 90, 30]), ("R9_C26", "south_west", [70, 0, 80, 10]))
        for y in (2000, 2010, 2020)
    ],
    # Additional JRC Global Surface Water tiles (occurrence + transitions).
    *[
        dict(
            id=f"jrc_gsw_{kind}_{tile}", name=f"JRC Global Surface Water - {kind.title()} (v1.4, 2021 release), tile {tile}",
            org="European Commission Joint Research Centre (JRC)", dataset_url="https://global-surface-water.appspot.com/download",
            collection=f"JRC/GSW1_4/GlobalSurfaceWater ({kind} layer)", region=region, used_by=[region],
            url=f"https://storage.googleapis.com/global-surface-water/downloads2021/{kind}/{kind}_{tile}v1_4_2021.tif",
            temporal="1984-03 to 2021-12" if kind == "occurrence" else "First year (1984) versus last year (2021) water class transition", resolution="30 m (1 arc-second)", fmt="GeoTIFF",
            license="Free and open; cite Pekel et al. (2016) Nature 540, 418-422.", covers=cover, variable="water occurrence (%)" if kind == "occurrence" else "water class transition",
        )
        for tile, region, cover in (("70E_30N", "north_west", [70, 20, 80, 30]), ("80E_20N", "south_east", [80, 10, 90, 20]), ("70E_10N", "south_west", [70, 0, 80, 10]), ("80E_30N", "north_east", [80, 20, 90, 30]))
        for kind in ("occurrence", "transitions")
        if not (tile == "80E_30N" and kind == "occurrence")  # already downloaded for the Sundarbans
    ],
    dict(
        id="esa_worldcover_2021_N21E087", name="ESA WorldCover 10 m 2021 v200, tile N21E087", org="European Space Agency (ESA) WorldCover consortium",
        dataset_url="https://esa-worldcover.org/en", collection="ESA WorldCover 10 m 2021 v200", region="sundarbans", used_by=["sundarbans"], large=True,
        url="https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N21E087_Map.tif",
        temporal="2021 (based on Sentinel-1 and Sentinel-2)", resolution="10 m", fmt="GeoTIFF (COG)",
        license="CC BY 4.0; cite Zanaga et al. (2022), ESA WorldCover 10 m 2021 v200.", covers=[87, 21, 90, 24], variable="land cover class (class 95 = mangroves)",
    ),
    *[
        dict(
            id=f"geoboundaries_IND_{lvl}", name=f"geoBoundaries gbOpen India {lvl} (simplified geometry)", org="geoBoundaries (William and Mary geoLab)",
            dataset_url="https://www.geoboundaries.org/", collection=f"geoBoundaries gbOpen IND {lvl}", region="boundaries", used_by=["boundaries"],
            url=f"https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/IND/{lvl}/geoBoundaries-IND-{lvl}_simplified.geojson",
            temporal="Boundary year 2021 (per geoBoundaries API)", resolution="vector (simplified)", fmt="GeoJSON",
            license="Open Data Commons Open Database License 1.0 (as reported by the geoBoundaries API); attribution to geoBoundaries required.",
            covers=[68, 6, 98, 38], variable="administrative boundaries",
        )
        for lvl in ("ADM1", "ADM2")
    ],
]

METADATA_ONLY = [
    dict(id="landsat_c2_l2_ee_catalog", name="Landsat Collection 2 Level-2 (LT05/LC08) - Earth Engine catalog entries", org="USGS / NASA",
         dataset_url="https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC08_C02_T1_L2", collection="LANDSAT/LC08/C02/T1_L2, LANDSAT/LT05/C02/T1_L2",
         access_note="Catalog pages only. Bulk access through Earth Engine needs a Google account; USGS EarthExplorer needs a free USGS login."),
    dict(id="jrc_gsw_monthly_history_ee_catalog", name="JRC Monthly Water History v1.4 - Earth Engine catalog entry", org="European Commission JRC",
         dataset_url="https://developers.google.com/earth-engine/datasets/catalog/JRC_GSW1_4_MonthlyHistory", collection="JRC/GSW1_4/MonthlyHistory",
         access_note="Monthly rasters are served through Earth Engine only (account required). The static tiles above were downloaded instead."),
    dict(id="sentinel2_sr_harmonized_ee_catalog", name="Sentinel-2 Harmonized Surface Reflectance - Earth Engine catalog entry", org="ESA / Copernicus",
         dataset_url="https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED", collection="COPERNICUS/S2_SR_HARMONIZED",
         access_note="Catalog page only; direct scene access was done through the public Earth Search STAC (see windowed Sentinel-2 entries)."),
    dict(id="copernicus_dataspace", name="Copernicus Data Space Ecosystem browser", org="ESA / European Commission", dataset_url="https://dataspace.copernicus.eu/",
         collection="Sentinel-2 L2A", access_note="Browsing is open; downloading needs a free Copernicus account.", auth=True),
    dict(id="usgs_earthexplorer", name="USGS EarthExplorer", org="USGS", dataset_url="https://earthexplorer.usgs.gov/", collection="Landsat Collection 2",
         access_note="Search is open; downloading needs a free USGS ERS login.", auth=True),
    dict(id="bhuvan_nrsc", name="ISRO / NRSC Bhuvan portal", org="ISRO National Remote Sensing Centre", dataset_url="https://bhuvan.nrsc.gov.in/",
         collection="Bhuvan thematic data (LULC, water bodies)", access_note="Portal reachable; thematic downloads require registration on Bhuvan, so none were attempted.", auth=True),
    dict(id="rgi7_glaciers_nsidc", name="Randolph Glacier Inventory v7 (glacier outlines)", org="GLIMS / NSIDC", dataset_url="https://nsidc.org/data/nsidc-0770/versions/7",
         collection="NSIDC-0770 RGI v7.0", access_note="NSIDC distribution requires a NASA Earthdata login. No glacier outline file was obtained.", auth=True),
    dict(id="gpm_imerg", name="NASA GPM IMERG precipitation", org="NASA GES DISC", dataset_url="https://gpm.nasa.gov/data/imerg", collection="GPM IMERG V07",
         access_note="Data needs an Earthdata login; coarse rainfall is context only and is not used for boundaries.", auth=True),
]

STAC_SEARCH = "https://earth-search.aws.element84.com/v1/search"


def inspect_raster(path: str) -> dict:
    with rasterio.open(path) as src:
        return {
            "driver": src.driver, "width": src.width, "height": src.height, "bands": src.count, "dtype": src.dtypes[0],
            "crs": src.crs.to_string() if src.crs else None, "bounds": [round(v, 6) for v in src.bounds], "resolution": [round(v, 8) for v in src.res],
            "nodata": src.nodata, "overviews": src.overviews(1),
        }


def download(url: str, dest: Path, client: httpx.Client) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0)) as r:
        r.raise_for_status()
        with open(part, "wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
    part.replace(dest)
    return dest.stat().st_size


def fetch_file(spec: dict, client: httpx.Client) -> dict:
    region_dir = OFFICIAL / spec["region"] / "originals" if spec["region"] != "boundaries" else ATLAS / "geographical_boundaries" / "originals"
    dest = region_dir / Path(spec["url"]).name
    entry = {k: spec[k] for k in ("id", "name", "org", "dataset_url", "collection", "temporal", "resolution", "fmt", "license", "variable")}
    entry.update(providing_organization=spec["org"], official_dataset_url=spec["dataset_url"], dataset_identifier=spec["collection"], original_file_name=dest.name,
                 acquisition_or_temporal_coverage=spec["temporal"], geographical_coverage_bbox=spec["covers"], spatial_resolution=spec["resolution"],
                 original_file_format=spec["fmt"], license_or_terms=spec["license"], download_url=spec["url"], used_by_regions=spec["used_by"])
    for k in ("name", "org", "dataset_url", "collection", "temporal", "resolution", "fmt", "license"):
        entry.pop(k, None)
    try:
        if dest.exists():
            size = dest.stat().st_size
        else:
            print(f"downloading {spec['id']} ...", flush=True)
            size = download(spec["url"], dest, client)
        entry.update(local_path=str(dest.relative_to(ATLAS.parent.parent)).replace("\\", "/"), size_bytes=size, sha256=sha256(dest), download_date=today(), downloaded_at=now_iso())
        if dest.suffix == ".tif":
            info = inspect_raster(str(dest))
        elif dest.suffix == ".zip":
            with zipfile.ZipFile(dest) as z:
                tifs = [n for n in z.namelist() if n.lower().endswith(".tif")]
                if not tifs:
                    raise ValueError("zip contains no GeoTIFF")
                info = inspect_raster(f"zip://{dest.as_posix()}!/{tifs[0]}")
                info["zip_members"] = z.namelist()
        else:
            import json
            gj = json.loads(dest.read_text(encoding="utf-8"))
            info = {"type": gj.get("type"), "features": len(gj.get("features", []))}
        entry.update(crs=info.get("crs"), inspection=info, processing_operations=["none (original preserved unmodified)"], verification_status="VERIFIED_DOWNLOADED",
                     verification_note="File obtained over HTTPS, checksum computed, opened and inspected.")
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        entry.update(verification_status="ACCESS_REQUIRES_AUTHENTICATION" if code in (401, 403) else "NOT_ACCESSED", verification_note=f"HTTP {code} from {spec['url']}")
    except Exception as exc:  # network failure, corrupt file, ...
        entry.update(verification_status="NOT_ACCESSED", verification_note=f"{type(exc).__name__}: {str(exc)[:200]}")
    return entry


def probe_page(spec: dict, client: httpx.Client) -> dict:
    entry = dict(id=spec["id"], providing_organization=spec["org"], dataset_name=spec["name"], official_dataset_url=spec["dataset_url"], dataset_identifier=spec["collection"],
                 download_date=today(), access_note=spec["access_note"], sha256=None, local_path=None)
    try:
        r = client.get(spec["dataset_url"], follow_redirects=True, timeout=30.0)
        entry["http_status"] = r.status_code
        if r.status_code < 400:
            entry["verification_status"] = "ACCESS_REQUIRES_AUTHENTICATION" if spec.get("auth") else "VERIFIED_METADATA_ONLY"
            entry["verification_note"] = f"Page reachable (HTTP {r.status_code}). No data file was obtained from this entry."
        else:
            entry["verification_status"] = "NOT_ACCESSED"
            entry["verification_note"] = f"HTTP {r.status_code}"
    except Exception as exc:
        entry.update(verification_status="NOT_ACCESSED", verification_note=f"{type(exc).__name__}: {str(exc)[:160]}")
    return entry


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--skip-large", action="store_true", help="skip the biggest tiles (>60 MB)")
    args = ap.parse_args()
    registry_path = DOC / "source_registry.json"
    registry = read_json(registry_path, {"schema": "nasax-source-registry-1", "entries": []})
    by_id = {e["id"]: e for e in registry["entries"]}
    with httpx.Client(headers={"User-Agent": "NASAX-atlas-builder/1.0 (research prototype)"}) as client:
        for spec in FILES:
            if args.only and spec["id"] not in args.only:
                continue
            if args.skip_large and spec.get("large"):
                continue
            by_id[spec["id"]] = fetch_file(spec, client)
            print(spec["id"], "->", by_id[spec["id"]]["verification_status"], flush=True)
            registry["entries"] = list(by_id.values())
            write_json(registry_path, registry)
        for spec in METADATA_ONLY:
            if args.only and spec["id"] not in args.only:
                continue
            by_id[spec["id"]] = probe_page(spec, client)
            print(spec["id"], "->", by_id[spec["id"]]["verification_status"], flush=True)
    registry["entries"] = list(by_id.values())
    registry["generated_at"] = now_iso()
    write_json(registry_path, registry)


if __name__ == "__main__":
    main()
