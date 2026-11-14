"""Rule-based chat: understands "what happened in <place> from <year> to <year>" style questions.

No external AI service is used. The parser only matches region names, variable names, years and month names that exist in
the loaded dataset, tells the user exactly what it understood, and asks a clarifying question instead of guessing.
"""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

from app.errors import AppError
from app.schemas_story import ChatAction, ChatRequest, ChatResponse, StoryRequest
from app.services.story import build_story, default_variable
from app.services.store import DatasetRecord

MONTHS = {
    name: i
    for i, names in enumerate(
        [
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"),
            ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"), ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}
YEAR_RE = r"(?:19|20)\d{2}"
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def find_regions(text: str, regions: list[str]) -> list[str]:
    t = " " + _norm(re.sub(r"[^\w\s()-]", " ", text)) + " "
    found: list[tuple[int, str]] = []
    for r in sorted(regions, key=len, reverse=True):
        pat = " " + _norm(re.sub(r"[^\w\s()-]", " ", r)) + " "
        pos = t.find(pat)
        if pos < 0 and r.lower().startswith("global"):
            pos = t.find(" global ")
            if pos < 0:
                pos = t.find(" world ")
            if pos < 0:
                pos = t.find(" worldwide ")
        if pos >= 0:
            found.append((pos, r))
    return [r for _, r in sorted(found)]


def find_variable(text: str, record: DatasetRecord) -> str | None:
    t = _norm(text)
    names = record.data["variable"].dropna().unique().tolist()
    extra = {"rain": "precip", "rainfall": "precip", "precipitation": "precip"}
    for n in sorted(names, key=len, reverse=True):
        if _norm(n.replace("_", " ")) in t.replace("_", " "):
            return n
    for word, stem in extra.items():
        if re.search(rf"\b{word}\b", t):
            for n in names:
                if stem in n.lower():
                    return n
    return None


def parse_period(text: str, first: pd.Timestamp, last: pd.Timestamp) -> tuple[date, date, str] | None:
    t = _norm(text)
    # "March 2012", "mar 2012 to jun 2014"
    mon_year = [(MONTHS[m.group(1)], int(m.group(2))) for m in re.finditer(rf"\b({MONTH_RE})\.?\s+(?:of\s+)?({YEAR_RE})\b", t)]
    if len(mon_year) >= 2:
        (m1, y1), (m2, y2) = mon_year[0], mon_year[1]
        a, b = date(y1, m1, 1), date(y2, m2, 1)
        return (min(a, b), max(a, b), "months")
    if len(mon_year) == 1:
        m, y = mon_year[0]
        return (date(y, m, 1), date(y, m, 1), "month")
    last_n = re.search(r"\b(?:last|past|previous)\s+(\d{1,2})\s+years?\b", t)
    if last_n:
        n = int(last_n.group(1))
        end = last.to_period("M").to_timestamp()
        return ((end - pd.DateOffset(years=n) + pd.DateOffset(months=1)).date(), end.date(), "years")
    years = [int(y) for y in re.findall(rf"\b({YEAR_RE})\b", t)]
    if len(years) >= 2:
        a, b = min(years[0], years[1]), max(years[0], years[1])
        return (date(a, 1, 1), date(b, 12, 1), "years")
    if len(years) == 1:
        return (date(years[0], 1, 1), date(years[0], 12, 1), "year")
    if re.search(r"\b(all|whole|entire|full)\b.*\b(period|time|record|years|data)\b|\bsince the (start|beginning)\b", t):
        return (first.date(), last.to_period("M").to_timestamp().date(), "all")
    return None


def _clip(start: date, end: date, first: pd.Timestamp, last: pd.Timestamp) -> tuple[date, date, bool]:
    lo, hi = first.to_period("M").to_timestamp().date(), last.to_period("M").to_timestamp().date()
    s, e = max(start, lo), min(end, hi)
    return s, e, (s != start or e != end)


HELP = (
    "I answer questions about the loaded dataset only. Try: “What happened in India from 2010 to 2015?”, "
    "“Show me Amazon in March 2012”, or “Compare India and Amazon from 2005 to 2010”. I tell you what I understood, "
    "and I never invent data or causes."
)


def answer(record: DatasetRecord, req: ChatRequest) -> ChatResponse:
    df = record.data
    regions = sorted(df["region"].dropna().unique().tolist())
    text = req.message.strip()
    t = _norm(text)
    none = ChatAction(type="none")

    if re.fullmatch(r"(hi|hello|hey|help|\?|what can you do)\W*", t) or "what can you" in t or t.startswith("help"):
        return ChatResponse(reply=HELP, action=none, suggestions=_suggest(record, regions))

    mentioned = find_regions(text, regions)
    variable = find_variable(text, record) or req.current_variable or default_variable(record)
    understood: dict[str, str] = {}

    series = df[df["variable"] == variable] if variable else df
    if series.empty:
        return ChatResponse(reply="That dataset has no usable variable to answer from.", action=none)
    first, last = series["date"].min(), series["date"].max()

    compare = bool(re.search(r"\b(compare|versus|vs\.?|difference between)\b", t)) and len(mentioned) >= 2
    if mentioned:
        region_list = mentioned[:3] if compare else mentioned[:1]
    elif len(regions) == 1:
        region_list = regions
    elif req.current_region and req.current_region in regions and re.search(r"\b(here|this (place|region|area)|there)\b", t):
        region_list = [req.current_region]
    elif req.current_region and req.current_region in regions:
        region_list = [req.current_region]
        understood["place"] = f"{req.current_region} (the region currently selected; say another place name to change it)"
    else:
        return ChatResponse(
            reply="Which place do you mean? This dataset has: " + ", ".join(regions) + ".",
            action=none,
            suggestions=[f"What happened in {r}?" for r in regions[:3]],
        )
    understood.setdefault("place", ", ".join(region_list))
    understood["variable"] = str(variable)

    period = parse_period(text, first, last)
    if period is None:
        return ChatResponse(
            reply=(
                f"I understood the place ({', '.join(region_list)}) but not the time. This dataset covers {first:%B %Y} to {last:%B %Y}. "
                "Tell me a year, a month and year, or a range such as “from 2010 to 2015”."
            ),
            understood=understood,
            action=none,
            suggestions=[f"What happened in {region_list[0]} from {first.year} to {last.year}?"],
        )
    start, end, kind = period
    start, end, clipped = _clip(start, end, first, last)
    if start > end:
        return ChatResponse(
            reply=f"That period is outside the data. This dataset covers {first:%B %Y} to {last:%B %Y}; nothing is shown for it.",
            understood=understood,
            action=none,
        )
    understood["period"] = (f"{start:%b %Y}" if start == end else f"{start:%b %Y} – {end:%b %Y}") + (" (clipped to the data range)" if clipped else "")

    try:
        stories = [build_story(record, StoryRequest(dataset_id=record.id, region=r, variable=variable, start=start, end=end)) for r in region_list]
    except AppError as exc:
        return ChatResponse(reply=exc.message, understood=understood, action=none)

    if compare and len(stories) >= 2:
        lines = []
        for s in stories:
            st = s.stats
            extra = f", {st.anomaly_pct:+.1f}% against its usual months" if st and st.anomaly_pct is not None else ""
            lines.append(f"{s.region}: mean {st.mean:.4g} {s.unit}{extra}")
        note = " These regions come from a synthetic demo dataset, so the comparison is illustrative only." if stories[0].banner else ""
        reply = f"{stories[0].period.label} — " + "; ".join(lines) + "." + note + " No significance test is implied; use Trend analysis for tested comparisons."
        return ChatResponse(
            reply=reply,
            understood=understood,
            action=ChatAction(type="compare", regions=region_list, variable=variable, start=start, end=end),
            story=stories[0],
        )

    s = stories[0]
    top = [x.text for x in s.sentences if x.kind in ("observation", "comparison")][:3]
    reply = f"Here is what “{record.name}” shows for {s.region}, {s.period.label}. " + " ".join(top)
    if clipped:
        reply += " (Your period was clipped to the months the dataset covers.)"
    reply += " I have opened it on the 3D map."
    return ChatResponse(
        reply=reply,
        understood=understood,
        action=ChatAction(type="show_story", region=s.region, variable=variable, start=start, end=end),
        story=s,
        suggestions=_suggest(record, regions, exclude=s.region),
    )


def _suggest(record: DatasetRecord, regions: list[str], exclude: str | None = None) -> list[str]:
    s = record.data["date"]
    a, b = s.min().year, s.max().year
    out = [f"What happened in {r} from {a} to {b}?" for r in regions if r != exclude][:2]
    if len(regions) >= 2:
        out.append(f"Compare {regions[0]} and {regions[1]} from {a} to {b}")
    return out[:3]
