"""Resumable, verified download of original NASA files plus a provenance manifest.

* Originals are never modified: a file is written as ``<name>.part``, checksummed, then renamed and made read-only.
* An interrupted download resumes with an HTTP ``Range`` request (if the server ignores it, it restarts cleanly).
* A login page served instead of data is detected and reported as an authentication problem.
* Only the source URL is recorded; no credential or token is ever written to the manifest or the log.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from app.errors import AppError
from app.nasa.cmr import GranuleRecord
from app.nasa.config import DataLayout

log = logging.getLogger("earthtrend.nasa.download")
SOFTWARE = "earthtrend-nasa-pipeline 0.1"
CHUNK = 1024 * 1024


class Session(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...


@dataclass
class ManifestEntry:
    granule_ur: str
    file_name: str
    relative_path: str
    source_url: str
    size_bytes: int
    cmr_size_mb: float | None
    sha256: str
    downloaded_at: str
    granule_begin: str
    granule_end: str
    production_time: str | None
    http_content_length: int | None
    resumed_from_bytes: int
    software: str = SOFTWARE


def sha256_file(path: Path, chunk: int = CHUNK) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class Downloader:
    def __init__(
        self,
        layout: DataLayout,
        session: Session,
        *,
        timeout: tuple[float, float] = (15.0, 120.0),
        retries: int = 4,
        backoff_s: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.layout = layout
        self.session = session
        self.timeout = timeout
        self.retries = retries
        self.backoff_s = backoff_s
        self._sleep = sleep

    # ---- manifest ---------------------------------------------------------------------------
    def load_manifest(self, short_name: str, version: str) -> dict[str, Any]:
        p = self.layout.manifest_path(short_name, version)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"entries": []}

    def _record(self, short_name: str, version: str, collection: dict[str, Any], entry: ManifestEntry) -> None:
        m = self.load_manifest(short_name, version)
        m.update(
            {
                "short_name": short_name,
                "version": version,
                "collection_concept_id": collection.get("concept_id"),
                "doi": collection.get("doi"),
                "provider": collection.get("provider"),
                "title": collection.get("title"),
            }
        )
        m["entries"] = [e for e in m.get("entries", []) if e["granule_ur"] != entry.granule_ur] + [asdict(entry)]
        m["entries"].sort(key=lambda e: e["granule_begin"])
        _write_json_atomic(self.layout.manifest_path(short_name, version), m)

    # ---- download ---------------------------------------------------------------------------
    def download(self, granule: GranuleRecord, short_name: str, version: str, collection: dict[str, Any]) -> ManifestEntry:
        if not granule.https_url:
            raise AppError(422, "no_https_link", f"Granule {granule.granule_ur} has no HTTPS download link in CMR.")
        dest = self.layout.raw_path(short_name, version, granule.year, granule.file_name)
        dest.parent.mkdir(parents=True, exist_ok=True)

        existing = next((e for e in self.load_manifest(short_name, version).get("entries", []) if e["granule_ur"] == granule.granule_ur), None)
        if dest.exists() and existing:
            if sha256_file(dest) == existing["sha256"]:
                log.info("already downloaded and verified: %s", granule.file_name)
                return ManifestEntry(**existing)
            raise AppError(409, "raw_file_modified", f"{dest.name} exists but no longer matches its recorded checksum. It was not overwritten.")
        if dest.exists():
            raise AppError(409, "raw_file_unrecorded", f"{dest} exists but is not in the manifest. It was not overwritten; move it away or record it.")

        part = dest.with_name(dest.name + ".part")
        last: Exception | None = None
        resumed_from = 0
        content_length: int | None = None
        for attempt in range(self.retries + 1):
            try:
                resumed_from, content_length = self._fetch(granule.https_url, part)
                break
            except AppError:
                raise
            except Exception as exc:  # noqa: BLE001 - network errors are retried; details kept out of the message
                last = exc
                log.warning("download attempt %d/%d failed: %s", attempt + 1, self.retries + 1, type(exc).__name__)
                if attempt < self.retries:
                    self._sleep(self.backoff_s * (2**attempt))
        else:
            raise AppError(502, "download_failed", f"Download of {granule.file_name} failed after {self.retries + 1} attempts.", type(last).__name__)

        size = part.stat().st_size
        if content_length is not None and size != content_length:
            raise AppError(502, "size_mismatch", f"Downloaded {size} bytes but the server announced {content_length}.", {"kept": str(part)})
        digest = sha256_file(part)
        os.replace(part, dest)
        dest.chmod(stat.S_IREAD)  # originals are read-only
        entry = ManifestEntry(
            granule_ur=granule.granule_ur,
            file_name=granule.file_name,
            relative_path=dest.relative_to(self.layout.root).as_posix(),
            source_url=granule.https_url,
            size_bytes=size,
            cmr_size_mb=granule.size_mb,
            sha256=digest,
            downloaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            granule_begin=granule.begin,
            granule_end=granule.end,
            production_time=granule.production_time,
            http_content_length=content_length,
            resumed_from_bytes=resumed_from,
        )
        self._record(short_name, version, collection, entry)
        return entry

    def _fetch(self, url: str, part: Path) -> tuple[int, int | None]:
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        resp = self.session.get(url, headers=headers, stream=True, timeout=self.timeout, allow_redirects=True)
        try:
            status = resp.status_code
            if status in (401, 403):
                raise AppError(401, "earthdata_auth_failed", "NASA refused the request (HTTP %d). Check the Earthdata account and that the application is authorized for GES DISC." % status)
            if status == 404:
                raise AppError(404, "granule_not_found", "NASA returned 404 for the granule URL.")
            if status == 416 and have:
                return have, have  # already complete
            if status not in (200, 206):
                raise OSError(f"HTTP {status}")
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" in ctype:
                raise AppError(401, "earthdata_login_page", "NASA returned a web page instead of data, which usually means the login was not accepted.")
            mode = "ab"
            if status == 200:  # server ignored Range or none requested: start over
                mode, have = "wb", 0
            clen = resp.headers.get("Content-Length")
            total = (int(clen) + have) if clen is not None else None
            with part.open(mode) as f:
                for block in resp.iter_content(chunk_size=CHUNK):
                    if block:
                        f.write(block)
            return have, total
        finally:
            close = getattr(resp, "close", None)
            if close:
                close()
