"""NASA Common Metadata Repository (CMR) client: collection metadata, granule listing with pagination, completeness.

CMR is public and needs no credentials. Results are returned as parsed records; nothing is guessed.
"""

from __future__ import annotations

import calendar
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from app.errors import AppError

CMR_URL = "https://cmr.earthdata.nasa.gov/search"
USER_AGENT = "earthtrend-nasa-pipeline/0.1"


@dataclass(frozen=True)
class GranuleRecord:
    granule_ur: str
    file_name: str
    begin: str
    end: str
    size_mb: float | None
    production_time: str | None
    https_url: str | None
    s3_url: str | None
    opendap_url: str | None

    @property
    def year(self) -> int:
        return int(self.begin[:4])

    @property
    def month_key(self) -> str:
        return self.begin[:7]


@dataclass
class Completeness:
    first: str | None
    last: str | None
    expected_months: int
    present_months: int
    missing_months: list[str]
    duplicate_months: list[str]
    non_calendar_months: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing_months and not self.duplicate_months and not self.non_calendar_months


class CmrClient:
    def __init__(self, base_url: str = CMR_URL, client: httpx.Client | None = None, timeout_s: float = 60.0, retries: int = 3, backoff_s: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_s, headers={"User-Agent": USER_AGENT})
        self.retries = retries
        self.backoff_s = backoff_s

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = self._client.get(f"{self.base_url}/{path}", params=params)
                if r.status_code >= 500 or r.status_code == 429:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                if r.status_code >= 400:
                    raise AppError(502, "cmr_rejected_request", f"CMR rejected the request (HTTP {r.status_code}).", r.text[:300])
                return r.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last = e
                if attempt < self.retries:
                    time.sleep(self.backoff_s * (2**attempt))
        raise AppError(502, "cmr_unavailable", f"NASA CMR could not be reached after {self.retries + 1} attempts.", type(last).__name__)

    # ---- collection -------------------------------------------------------------------------
    def find_collection(self, short_name: str, version: str) -> dict[str, Any]:
        """Return the collection record (CMR meta plus UMM) for exactly one short name and version."""
        res = self._get_json("collections.umm_json", {"short_name": short_name, "version": version, "page_size": 10})
        items = res.get("items", [])
        if len(items) != 1:
            raise AppError(404, "collection_not_found", f"Expected exactly one CMR collection for {short_name} v{version}, found {len(items)}.")
        item = items[0]
        return {"concept_id": item["meta"]["concept-id"], "provider": item["meta"].get("provider-id"), "revision": item["meta"].get("revision-id"), "umm": item["umm"], "meta": item["meta"]}

    def variable_records(self, variable_concept_ids: list[str]) -> list[dict[str, Any]]:
        return [self._get_json(f"concepts/{cid}.umm_json") for cid in variable_concept_ids]

    # ---- granules ---------------------------------------------------------------------------
    def granules(self, collection_concept_id: str, page_size: int = 200, max_pages: int = 500) -> tuple[list[GranuleRecord], int]:
        """List every granule, paging until CMR runs out. Returns (records, total hits reported by CMR)."""
        records: list[GranuleRecord] = []
        hits = 0
        for page in range(1, max_pages + 1):
            res = self._get_json(
                "granules.umm_json",
                {"collection_concept_id": collection_concept_id, "page_size": page_size, "page_num": page, "sort_key": "start_date"},
            )
            hits = res.get("hits", hits)
            items = res.get("items", [])
            if not items:
                break
            records.extend(parse_granule(i["umm"]) for i in items)
            if len(records) >= hits:
                break
        if len(records) != hits:
            raise AppError(502, "cmr_pagination_mismatch", f"CMR reported {hits} granules but {len(records)} were retrieved.")
        return records, hits


def parse_granule(umm: dict[str, Any]) -> GranuleRecord:
    ur = umm["GranuleUR"]
    tr = umm["TemporalExtent"]["RangeDateTime"]
    dg = umm.get("DataGranule", {})
    name = next((i["Identifier"] for i in dg.get("Identifiers", []) if i.get("IdentifierType") == "ProducerGranuleId"), ur.split(":", 1)[-1])
    size = None
    for a in dg.get("ArchiveAndDistributionInformation", []):
        if a.get("Size") is not None and a.get("SizeUnit") == "MB":
            size = float(a["Size"])
            break
    https = s3 = dap = None
    for u in umm.get("RelatedUrls", []):
        t, url = u.get("Type"), u.get("URL")
        if t == "GET DATA" and url and url.startswith("https://"):
            https = https or url
        elif t == "GET DATA VIA DIRECT ACCESS" and url and url.startswith("s3://"):
            s3 = s3 or url
        elif t == "USE SERVICE API" and url:
            dap = dap or url
    return GranuleRecord(ur, name, tr["BeginningDateTime"], tr["EndingDateTime"], size, dg.get("ProductionDateTime"), https, s3, dap)


def monthly_completeness(granules: list[GranuleRecord]) -> Completeness:
    """Check a monthly product for missing months, duplicates and granules that are not whole calendar months."""
    if not granules:
        return Completeness(None, None, 0, 0, [], [])
    counts = Counter(g.month_key for g in granules)
    duplicates = sorted(k for k, v in counts.items() if v > 1)
    keys = sorted(counts)
    y, m = int(keys[0][:4]), int(keys[0][5:7])
    ey, em = int(keys[-1][:4]), int(keys[-1][5:7])
    expected: list[str] = []
    while (y, m) <= (ey, em):
        expected.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    bad: list[str] = []
    for g in granules:
        d0 = date.fromisoformat(g.begin[:10])
        d1 = date.fromisoformat(g.end[:10])
        if d0.day != 1 or d1.day != calendar.monthrange(d0.year, d0.month)[1] or (d1.year, d1.month) != (d0.year, d0.month):
            bad.append(g.month_key)
    return Completeness(keys[0], keys[-1], len(expected), len(counts), [k for k in expected if k not in counts], duplicates, sorted(set(bad)))
