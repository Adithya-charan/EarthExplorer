"""Fetch the original scientific sources for the Deep-Time explorer and write a provenance registry.

Everything is downloaded unchanged into DEEPTIME_ROOT/originals (default F:/NASAX_DEEPTIME). Nothing is generated here.
Run:  python scripts/fetch_deeptime_sources.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(os.environ.get("DEEPTIME_ROOT", "F:/NASAX_DEEPTIME"))
ORIG = ROOT / "originals"
UA = {"User-Agent": "NASAX-research-client"}
PBDB = "https://paleobiodb.org/data1.2"
MACRO = "https://macrostrat.org/api/v2"

DOWNLOADS = [
    # id, folder, filename, url, provider, product, license, citation, note
    ("gplates_2_5_geodata", "GPLATES", "gplates_2.5.0_geodata.zip", "https://zenodo.org/records/14194897/files/gplates_2.5.0_geodata.zip?download=1", "EarthByte Group / GPlates (Zenodo record 14194897)", "GPlates 2.5 GeoData: Zahirovic et al. 2022 rotation model, static polygons, coastlines, continental polygons, Cao et al. 2017 paleogeography, Seton et al. 2020 age grid", "CC BY 4.0 (Zenodo record); the EarthByte page states CC BY 3.0", "EarthByte Group, GPlates 2.5.0 GeoData, Zenodo, doi:10.5281/zenodo.8307322; rotation model: Zahirovic et al. 2022, doi:10.1002/gdj3.146", "official page: https://www.earthbyte.org/gplates-2-5-software-and-data-sets/"),
    ("scotese_paleoatlas_v3", "EARTHBYTE", "Scotese_PaleoAtlas_v3.zip", "https://www.earthbyte.org/webdav/ftp/earthbyte/Scotese_PaleoAtlas_v3.zip", "EarthByte / PALEOMAP Project (C. R. Scotese)", "PALEOMAP PaleoAtlas for GPlates v3: 90 paleogeographic maps and the PALEOMAP global plate model", "Not stated on the download page; credit the PALEOMAP Project", "Scotese, C.R., 2016. PALEOMAP PaleoAtlas for GPlates and the PaleoData Plotter Program, PALEOMAP Project, http://www.earthbyte.org/paleomap-paleoatlas-for-gplates/", "official page: https://www.earthbyte.org/paleomap-paleoatlas-for-gplates/"),
    ("ics_chart_2024_12", "GEOLOGICAL_TIME_SCALE", "ICS_ChronostratChart2024-12.pdf", "https://stratigraphy.org/ICSchart/ChronostratChart2024-12.pdf", "International Commission on Stratigraphy", "International Chronostratigraphic Chart v2024/12", "CC BY 4.0 (stated on the chart)", "Cohen, K.M., Finney, S.C., Gibbard, P.L. and Fan, J.-X. (2013; updated) The ICS International Chronostratigraphic Chart. Episodes 36: 199-204", "official page: https://stratigraphy.org/chart"),
]
API = [
    ("pbdb_dinosauria_india_occurrences_csv", "PALEOBIOLOGY_DATABASE", "pbdb_occs_Dinosauria_IN.csv", f"{PBDB}/occs/list.csv?base_name=Dinosauria&cc=IN&show=coords,loc,strat,stratext,ref,refattr,class,classext,time,ident,env,lith&limit=all&datainfo&rowcount", "The Paleobiology Database", "occurrences of Dinosauria with country code IN", "CC0", "The Paleobiology Database, https://paleobiodb.org (data service 1.2)"),
    ("pbdb_dinosauria_india_json", "PALEOBIOLOGY_DATABASE", "pbdb_occs_Dinosauria_IN.json", f"{PBDB}/occs/list.json?base_name=Dinosauria&cc=IN&show=coords,loc,strat,ref,class,time&limit=all&datainfo&rowcount", "The Paleobiology Database", "same query, JSON", "CC0", "The Paleobiology Database"),
    ("pbdb_dinosauria_india_collections_csv", "PALEOBIOLOGY_DATABASE", "pbdb_collections_Dinosauria_IN.csv", f"{PBDB}/colls/list.csv?base_name=Dinosauria&cc=IN&show=loc,stratext,time,ref&limit=all&datainfo", "The Paleobiology Database", "collections containing Dinosauria in India", "CC0", "The Paleobiology Database"),
    ("pbdb_dinosauria_india_references_csv", "PALEOBIOLOGY_DATABASE", "pbdb_refs_Dinosauria_IN.csv", f"{PBDB}/occs/refs.csv?base_name=Dinosauria&cc=IN&show=both&limit=all", "The Paleobiology Database", "bibliographic references behind those occurrences", "CC0", "The Paleobiology Database"),
    ("pbdb_mesozoic_india_occurrences_csv", "PALEOBIOLOGY_DATABASE", "pbdb_occs_Mesozoic_IN.csv", f"{PBDB}/occs/list.csv?cc=IN&min_ma=66&max_ma=252&show=coords,loc,strat,stratext,ref,class,time,env,lith&limit=all", "The Paleobiology Database", "all Mesozoic (66-252 Ma) occurrences in India, used for formations and environments", "CC0", "The Paleobiology Database"),
    ("macrostrat_intervals_ages", "MACROSTRAT", "macrostrat_intervals_ages.json", f"{MACRO}/defs/intervals?timescale={urllib.parse.quote('international ages')}&format=json", "Macrostrat", "interval definitions of the international ages timescale (ICS-derived)", "CC BY 4.0", "Peters, S.E. et al. 2018, Macrostrat: A platform for geological data integration and deep-time Earth crust research, G-Cubed 19, doi:10.1029/2018GC007467"),
]
for ts in ("periods", "epochs", "eras"):
    API.append((f"macrostrat_intervals_{ts}", "MACROSTRAT", f"macrostrat_intervals_{ts}.json", f"{MACRO}/defs/intervals?timescale={urllib.parse.quote('international ' + ts)}&format=json", "Macrostrat", f"interval definitions of the international {ts} timescale (ICS-derived)", "CC BY 4.0", "Peters et al. 2018, doi:10.1029/2018GC007467"))


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def get(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(dst, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def entry(sid, folder, name, url, prov, prod, lic, cite, note, access):
    p = ORIG / folder / name
    if not p.exists():
        print("fetch", name)
        get(url, p)
    return {"source_id": sid, "folder": folder, "original_filename": name, "provider": prov, "product": prod, "source_url": url.split("?download")[0], "license": lic, "citation": cite, "note": note, "bytes": p.stat().st_size, "sha256": sha(p), "downloaded_utc": dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds"), "access": access}


def main() -> None:
    reg = [entry(*d[:8], d[8], "direct file download") for d in DOWNLOADS]
    reg += [entry(*a[:8], "API response saved unchanged", "API query") for a in API]
    (ORIG / "_source_registry.json").write_text(json.dumps({"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "sources": reg}, indent=1), encoding="utf-8")
    print(len(reg), "sources registered")
    # unpack the members the build needs; the zips themselves stay untouched
    g = ORIG / "GPLATES" / "extracted"
    if not g.exists():
        with zipfile.ZipFile(ORIG / "GPLATES" / "gplates_2.5.0_geodata.zip") as z:
            keep = ("Rotations/", "Coastlines/", "ContinentalPolygons/", "StaticPolygons/", "COBs/", "Paleogeography/", "Seton_etal_2020_PresentDay_AgeGrid.nc", "Scotese_PALEOMAP_GlobalPlateModel/")
            for n in z.namelist():
                if not n.endswith("/") and any(k in n for k in keep) and "__MACOSX" not in n:
                    z.extract(n, g)
    e = ORIG / "EARTHBYTE" / "extracted"
    if not e.exists():
        with zipfile.ZipFile(ORIG / "EARTHBYTE" / "Scotese_PaleoAtlas_v3.zip") as z:
            for n in z.namelist():
                if ("Global Plate Model" in n or n.endswith(".pdf") or "Rasters" in n) and not n.endswith("/"):
                    z.extract(n, e)


if __name__ == "__main__":
    sys.exit(main())
