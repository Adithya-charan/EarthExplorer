"""AIExplanationService: plain-language explanation of MEASURED results.

The Groq API (OpenAI-compatible) is used when ``GROQ_API_KEY`` is set. The model never sees raw rasters; it can only call
structured tools that return numbers already computed by the change-detection service. Without a key, on any network or
API failure, or when a reply is empty, a deterministic report built from the same numbers is returned instead.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import Settings
from app.explorer.change import AnalysisRecord, ChangeDetectionService
from app.explorer.schemas import ChatAnswer, Explanation

log = logging.getLogger("earthtrend.explorer")

SYSTEM = (
    "You explain satellite-style land and water change results to a general audience. Use ONLY numbers returned by the tools; "
    "never invent measurements, dates or places. Cover what changed, where, when, how much, how it progressed, possible factors "
    "(clearly marked as possibilities, not findings) and what the data cannot establish. Never claim a cause. If the dataset is "
    "synthetic, say it is a simulated demonstration. Never call anything live or real-time. Be concise and clear (under 220 words)."
)

TOOLS = [
    {"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object", "properties": {}}}}
    for n, d in (
        ("get_change_summary", "Measured areas, outcome, period, observations used, confidence and limitations."),
        ("get_hotspots", "Ranked change hotspots with area, compass region and centroid."),
        ("get_water_area_series", "Yearly same-season water area, cumulative loss/gain, and the trend test."),
        ("get_observation_quality", "Quality, valid-pixel shares, excluded observations and data limitations."),
    )
]


def _a(v: float | None, nd: int = 1) -> str:
    return "n/a" if v is None else f"{v:,.{nd}f}"


class AIExplanationService:
    def __init__(self, settings: Settings, changes: ChangeDetectionService, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.changes = changes
        self.transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.settings.groq_api_key)

    # ------------------------------------------------------------------------------ tools
    def run_tool(self, name: str, rec: AnalysisRecord) -> dict[str, Any]:
        s = rec.summary
        if name == "get_change_summary":
            return {"outcome": s.outcome, "headline": s.headline, "dataset": s.dataset.name if s.dataset else None, "is_synthetic": s.is_synthetic, "simulated_label": s.simulated_label,
                    "period": s.period.effective if s.period else None, "first_observation": s.first_observation and s.first_observation["date"], "last_observation": s.last_observation and s.last_observation["date"],
                    "areas_ha": s.areas, "most_affected": s.most_affected, "confidence": s.confidence, "what_was_analysed": s.what_was_analysed}
        if name == "get_hotspots":
            return {"hotspots": [h.model_dump() for h in s.hotspots]}
        if name == "get_water_area_series":
            return {"series": [p.model_dump() for p in s.progression], "trend": s.trend}
        if name == "get_observation_quality":
            return {"quality": s.quality, "observations_used": s.observations_used, "confidence_reasons": s.confidence_reasons, "limitations": s.limitations}
        return {"error": f"unknown tool {name}"}

    # ------------------------------------------------------------------------- groq loop
    def _groq(self, messages: list[dict[str, Any]], rec: AnalysisRecord) -> tuple[str, list[str]]:
        st = self.settings
        used: list[str] = []
        with httpx.Client(base_url=st.groq_base_url, timeout=st.groq_timeout_s, transport=self.transport, headers={"Authorization": f"Bearer {st.groq_api_key}"}) as client:
            for _ in range(4):
                r = client.post("/chat/completions", json={"model": st.groq_model, "messages": messages, "tools": TOOLS, "tool_choice": "auto", "temperature": 0.2, "max_tokens": 600})
                r.raise_for_status()
                msg = r.json()["choices"][0]["message"]
                calls = msg.get("tool_calls") or []
                if not calls:
                    text = (msg.get("content") or "").strip()
                    if not text:
                        raise ValueError("empty reply")
                    return text, used
                messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
                for c in calls:
                    fn = c["function"]["name"]
                    used.append(fn)
                    messages.append({"role": "tool", "tool_call_id": c["id"], "name": fn, "content": json.dumps(self.run_tool(fn, rec), default=str)})
        raise ValueError("tool loop did not finish")

    # --------------------------------------------------------------------- deterministic
    def report(self, rec: AnalysisRecord) -> str:
        s = rec.summary
        a = s.areas
        tag = f"{s.simulated_label}. " if s.simulated_label else ""
        eff = s.period.effective if s.period and s.period.effective else None
        per = f"{eff['start_year']}–{eff['end_year']}" if eff else "the requested period"
        if s.outcome == "insufficient_data":
            ins = s.insufficient
            parts = [tag + s.headline, ins.reason if ins else ""]
            if ins and ins.missing:
                parts.append("Missing: " + "; ".join(m for m in ins.missing if m) + ".")
            if ins and ins.suggested_period:
                parts.append(f"A period with enough usable observations is {ins.suggested_period['start_year']}–{ins.suggested_period['end_year']}.")
            parts.append("No conclusion about change, or its absence, can be drawn from this.")
            return " ".join(p for p in parts if p)
        out = [tag + f"What the data show: between {per} the mapped water extent changed by a net {_a(a.get('net_ha'))} ha ({_a(a.get('pct_net_change'))}%), made up of {_a(a.get('lost_ha'))} ha lost and {_a(a.get('gained_ha'))} ha gained, measured from {s.observations_used.get('start_count')} and {s.observations_used.get('end_count')} same-season observations ({s.observations_used.get('matched_months')})."]
        if s.outcome == "no_clear_change":
            out.append("No change large enough to rule out normal variation was found, so none is claimed.")
        if s.hotspots:
            out.append("Where: " + "; ".join(f"{h.description}" for h in s.hotspots[:3]) + ".")
        if s.progression and len(s.progression) >= 3:
            first, last = s.progression[0], s.progression[-1]
            out.append(f"Progression: estimated water area went from {_a(first.water_ha)} ha in {first.year} to {_a(last.water_ha)} ha in {last.year}" + (f"; the yearly trend is {s.trend['direction']} ({_a(s.trend['slope_ha_per_year'], 2)} ha/yr, p={s.trend['p_value']})." if s.trend else "."))
        out.append(f"Confidence is {s.confidence}: " + "; ".join(s.confidence_reasons[:3]) + ".")
        out.append("Possible factors (not established by this data): land-use or construction near the shoreline, changes in water management or inflow, and multi-year rainfall variation. Distinguishing them needs other evidence.")
        out.append("What this cannot tell you: why the change happened, or conditions between observation dates.")
        return " ".join(out)

    # ----------------------------------------------------------------------------- public
    def explain(self, rec: AnalysisRecord) -> Explanation:
        notice = None
        if self.enabled:
            msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Explain the measured change for the current analysis. Call the tools you need first."}]
            try:
                text, used = self._groq(msgs, rec)
                if rec.summary.is_synthetic and "simulat" not in text.lower():
                    text = f"{rec.summary.simulated_label}. " + text
                return Explanation(text=text, source="groq", model=self.settings.groq_model, tools_used=used)
            except Exception as exc:
                log.warning("Groq explanation failed: %s", type(exc).__name__)
                notice = "The AI service could not be reached, so this report was written directly from the measurements."
        else:
            notice = "No AI key is configured (set GROQ_API_KEY), so this report was written directly from the measurements."
        return Explanation(text=self.report(rec), source="deterministic", notice=notice)

    def chat(self, question: str, rec: AnalysisRecord | None, history: list[dict[str, str]] | None = None) -> ChatAnswer:
        if rec is None:
            return ChatAnswer(answer="Search for a place and run the analysis first; I answer from measured results only.", source="deterministic")
        notice = None
        if self.enabled:
            msgs: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM}]
            for h in (history or [])[-6:]:
                if h.get("role") in ("user", "assistant") and h.get("content"):
                    msgs.append({"role": h["role"], "content": h["content"][:800]})
            msgs.append({"role": "user", "content": question})
            try:
                text, used = self._groq(msgs, rec)
                return ChatAnswer(answer=text, source="groq", model=self.settings.groq_model, tools_used=used)
            except Exception as exc:
                log.warning("Groq chat failed: %s", type(exc).__name__)
                notice = "The AI service could not be reached; answering from the measurements directly."
        else:
            notice = "No AI key is configured (set GROQ_API_KEY); answering from the measurements directly."
        return ChatAnswer(answer=self._rule_answer(question.lower(), rec), source="deterministic", notice=notice)

    def _rule_answer(self, q: str, rec: AnalysisRecord) -> str:
        s = rec.summary
        a = s.areas
        if s.outcome == "insufficient_data":
            return self.report(rec)
        if any(w in q for w in ("why", "cause", "reason", "because")):
            return "The measurements show where and how much the water changed, not why. Possible factors, which need other evidence to confirm, include shoreline construction, water-management changes and rainfall variation. " + (f"{s.simulated_label}." if s.simulated_label else "")
        if any(w in q for w in ("where", "hotspot", "region", "area affected", "which part")):
            return ("Hotspots: " + "; ".join(h.description for h in s.hotspots[:4]) + ".") if s.hotspots else "No hotspot above the minimum size was found."
        if any(w in q for w in ("when", "progress", "timeline", "trend", "over time", "how fast")):
            t = s.trend
            if not s.progression:
                return "There are too few yearly composites to describe progression."
            f, l = s.progression[0], s.progression[-1]
            return f"Estimated water area went from {_a(f.water_ha)} ha ({f.year}) to {_a(l.water_ha)} ha ({l.year})." + (f" The yearly trend is {t['direction']} ({_a(t['slope_ha_per_year'], 2)} ha per year)." if t else "")
        if any(w in q for w in ("how much", "area", "percent", "%", "size", "lost", "gain")):
            return f"{_a(a.get('lost_ha'))} ha lost, {_a(a.get('gained_ha'))} ha gained, net {_a(a.get('net_ha'))} ha ({_a(a.get('pct_net_change'))}% of the starting water area)."
        if any(w in q for w in ("confiden", "quality", "trust", "reliab", "missing", "limit", "cloud")):
            return f"Confidence is {s.confidence}. " + " ".join(s.limitations[:3])
        return self.report(rec)
