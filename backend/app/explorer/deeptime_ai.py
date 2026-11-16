"""Grounded geological explanations for the Deep-Time Explorer.

The model (Groq, when GROQ_API_KEY is set) can only call tools that return records already held in the built datasets.
Without a key, on failure, or on an empty reply, a deterministic answer is composed from the same records. Every answer
separates (1) dataset records, (2) model reconstruction, (3) published interpretation and (4) uncertainty.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any

import httpx

from app.config import Settings
from app.explorer.deeptime import CAVEAT, EB, PM, DeepTimeService, ma_text
from app.explorer.schemas import ChatAnswer

log = logging.getLogger("earthtrend.explorer")

SYSTEM = (
    "You answer questions about Earth's geological history, India's plate journey, the Himalaya and Indian fossils for a general audience. "
    "Use ONLY facts returned by the tools. Never invent fossil records, ages, coordinates, formations or events; if the tools return nothing, say the available data cannot answer. "
    "Structure every answer in four labelled parts: 'Dataset records' (rows from PBDB, ICS or the paleogeography polygons), 'Model reconstruction' (positions computed from the plate models), "
    "'Published interpretation' (events and stages with their reference ids such as B09) and 'Uncertainty'. Omit a part only when it does not apply. "
    "Say 'Geological Reconstruction' for deep-time views; never call a reconstruction a satellite observation or a photograph of the past. "
    "Never place a modern city or administrative boundary in the past: only the plate under it is reconstructed. Under 250 words."
)

_AGE = {"type": "number", "description": "Age in Ma (millions of years before present); 0 is today."}
TOOLS = [
    {"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object", "properties": p, "required": r}}}
    for n, d, p, r in (
        ("get_time_slice", "Geological period, epoch, India's reconstructed position in both plate models, events and paleogeography at an age.", {"age_ma": _AGE}, ["age_ma"]),
        ("get_himalaya_stage", "Published Himalayan-Tibetan evolution stage nearest an age, with computed India-Eurasia gap.", {"age_ma": _AGE}, ["age_ma"]),
        ("get_fossil_records", "PBDB dinosaur occurrences in India whose age range includes an age (optionally widened by window_ma).", {"age_ma": _AGE, "window_ma": {"type": "number"}}, ["age_ma"]),
        ("get_events", "Geological events overlapping an age, with sources and confidence.", {"age_ma": _AGE}, ["age_ma"]),
        ("get_place_history", "Reconstructed position of the plate under a modern place (location_id such as city:hyderabad) at an age.", {"location_id": {"type": "string"}, "age_ma": _AGE}, ["location_id", "age_ma"]),
    )
]
PLACE_WORDS = {"hyderabad": "city:hyderabad", "bengaluru": "city:bengaluru", "bangalore": "city:bengaluru", "bellandur": "lake:bellandur-lake", "chennai": "city:chennai", "mumbai": "city:mumbai", "delhi": "city:delhi", "kolkata": "city:kolkata", "sundarbans": "forest:sundarbans",
               "himalaya": "mountain:himalayas", "uttarakhand": "mountain:himalayas", "dhauliganga": "river:dhauliganga-catchment", "western ghats": "mountain:western-ghats", "deccan": "plateau:deccan-plateau"}


_GENERIC = {"dinosaur", "dinosaurs", "dinosauria", "titanosaur", "titanosaurs", "sauropod", "sauropods", "theropod", "theropods", "ornithischian"}


def missing_taxa(question: str, records: list[dict]) -> list[str]:
    """Named taxa in the question (for example 'Tyrannosaurus') that have no record in the dataset. Nothing is said about them beyond that."""
    hay = " ".join((r["taxon_name"] + " " + r.get("identified_name", "") + " " + r["higher_taxonomy"]).lower() for r in records)
    out = []
    for w in re.findall(r"[A-Za-z]{5,}", question):
        lw = w.lower()
        if lw in _GENERIC or not lw.endswith(("saurus", "saur", "raptor", "ceratops", "odon", "odontid")):
            continue
        if lw.rstrip("s") not in hay and lw not in hay and w.capitalize() not in out:
            out.append(w.capitalize())
    if re.search(r"t\.? ?rex", question.lower()) and "tyrannosaurus" not in hay and "Tyrannosaurus" not in out:
        out.append("Tyrannosaurus")
    return out


def parse_age(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(million|ma\b|myr|m\.y)", text.lower())
    if m:
        return float(m.group(1))
    m = re.search(r"(\d[\d,]*)\s*years? ago", text.lower())
    if m:
        return float(m.group(1).replace(",", "")) / 1e6
    return None


class DeepTimeAI:
    def __init__(self, settings: Settings, svc: DeepTimeService, transport: httpx.BaseTransport | None = None):
        self.settings, self.svc, self.transport = settings, svc, transport

    @property
    def enabled(self) -> bool:
        return bool(self.settings.groq_api_key)

    # ------------------------------------------------------------------------------ tools
    def run_tool(self, name: str, args: dict) -> dict[str, Any]:
        s = self.svc
        age = float(args.get("age_ma", 0) or 0)
        if name == "get_time_slice":
            f = s.frame(age, EB)
            return {"kind": "model reconstruction + dataset records", "age_ma": f["age_ma"], "period": f["period"], "epoch": f["epoch"], "era": f["era"], "boundary": f["boundary"], "india_position_earthbyte": f["india"][EB]["india"], "india_position_paleomap": f["india"][PM]["india"],
                    "models_disagree_km": f["models_disagree_km"], "has_paleogeography": f["has_paleogeography"], "paleogeography_at_reference_points": f["environment"]["points"], "events": [{k: e[k] for k in ("event_id", "event_name", "start_age_ma", "end_age_ma", "confidence", "evidence_source")} for e in f["events"]], "caveat": CAVEAT}
        if name == "get_himalaya_stage":
            h = s.himalaya()["stages"]
            st = min(h, key=lambda x: abs(x["age_ma"] - age))
            return {"kind": "published interpretation + computed positions", "stage": {k: st[k] for k in ("age_ma", "stage", "collision", "process", "mountains", "evidence", "uncertainty", "sources", "india_position", "india_eurasia_gap_km")}, "references": [r["citation"] for r in st["references"]]}
        if name == "get_fossil_records":
            recs = s.fossil_records(age, float(args.get("window_ma", 0) or 0), EB)
            return {"kind": "dataset records (PBDB)", "age_ma": s.nearest(age), "count": len(recs), "records": [{k: r[k] for k in ("occurrence_id", "taxon_name", "age_label", "state", "formation", "reference_id", "reference_text")} for r in recs[:12]]}
        if name == "get_events":
            return {"kind": "published interpretation", "events": s.events(age, span=max(0.05, 0.02 * age))}
        if name == "get_place_history":
            p = s.place(str(args.get("location_id", "")), age)
            return p or {"error": "unknown location_id"}
        return {"error": f"unknown tool {name}"}

    def _groq(self, messages: list[dict[str, Any]]) -> tuple[str, list[str]]:
        st = self.settings
        used: list[str] = []
        with httpx.Client(base_url=st.groq_base_url, timeout=st.groq_timeout_s, transport=self.transport, headers={"Authorization": f"Bearer {st.groq_api_key}"}) as client:
            for _ in range(5):
                r = client.post("/chat/completions", json={"model": st.groq_model, "messages": messages, "tools": TOOLS, "tool_choice": "auto", "temperature": 0.2, "max_tokens": 700})
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
                    try:
                        args = json.loads(c["function"].get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    messages.append({"role": "tool", "tool_call_id": c["id"], "name": fn, "content": json.dumps(self.run_tool(fn, args), default=str)})
        raise ValueError("tool loop did not finish")

    # ------------------------------------------------------------------------------ public
    def chat(self, question: str, age_ma: float | None, location_id: str | None, history: list[dict[str, str]] | None = None) -> ChatAnswer:
        notice = None
        ctx = f"[Current view: {ma_text(age_ma)}{', place ' + location_id if location_id else ''}]"
        if self.enabled:
            msgs: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM}]
            for h in (history or [])[-6:]:
                if h.get("role") in ("user", "assistant") and h.get("content"):
                    msgs.append({"role": h["role"], "content": h["content"][:800]})
            msgs.append({"role": "user", "content": f"{ctx}\n{question}" if age_ma is not None else question})
            try:
                text, used = self._groq(msgs)
                return ChatAnswer(answer=text, source="groq", model=self.settings.groq_model, tools_used=used)
            except Exception as exc:  # noqa: BLE001
                log.warning("Groq deep-time chat failed: %s", type(exc).__name__)
                notice = "The AI service could not be reached; answering from the datasets directly."
        else:
            notice = "No AI key is configured (set GROQ_API_KEY); answering from the datasets directly."
        return ChatAnswer(answer=self.rule_answer(question, age_ma, location_id), source="deterministic", notice=notice)

    # ------------------------------------------------------------------------------ deterministic
    def rule_answer(self, question: str, age_ma: float | None, location_id: str | None) -> str:
        s = self.svc
        q = question.lower()
        age = parse_age(question)
        if age is None:
            age = age_ma if age_ma is not None else None
        place = next((v for k, v in PLACE_WORDS.items() if k in q), location_id)
        parts: dict[str, list[str]] = {"Dataset records": [], "Model reconstruction": [], "Published interpretation": [], "Uncertainty": []}
        if any(w in q for w in ("dinosaur", "fossil", "titanosaur", "sauropod", "theropod")):
            a = age if age is not None else 70.0
            recs = s.fossil_records(a, 0.0, EB)
            allr = s.fossils
            for name in missing_taxa(question, allr):
                parts["Dataset records"].append(f"The dataset has no PBDB record of {name} in India (query: Dinosauria, country code IN, {len(allr)} occurrences). Nothing is stated about it here.")
            if age is None or not recs:
                top = Counter(r["taxon_name"] for r in allr).most_common(6)
                parts["Dataset records"].append(f"The Paleobiology Database holds {len(allr)} dinosaur occurrences for India (ages {min(r['minimum_age_ma'] for r in allr):g} to {max(r['maximum_age_ma'] for r in allr):g} Ma). Most-recorded taxa: " + "; ".join(f"{t} ({n})" for t, n in top) + ".")
                if age is not None:
                    parts["Dataset records"].append(f"None of them has an age range that includes {a:g} Ma exactly; widen the window to see nearby records.")
            else:
                top = Counter(r["taxon_name"] for r in recs).most_common(6)
                st = Counter(r["state"] for r in recs).most_common(4)
                parts["Dataset records"].append(f"{len(recs)} PBDB occurrences in India have an age range that includes {a:g} Ma. Taxa: " + "; ".join(f"{t} ({n})" for t, n in top) + ". States: " + ", ".join(f"{t or 'not stated'} ({n})" for t, n in st) + ".")
                birds = sum(1 for r in recs if r["is_bird"])
                if birds:
                    parts["Dataset records"].append(f"{birds} of these are birds (Aves), which PBDB classifies within Dinosauria; they are not non-avian dinosaurs.")
                parts["Dataset records"].append("Examples: " + "; ".join(f"{r['occurrence_id']} {r['taxon_name']} ({r['formation'] or 'formation not stated'}, {r['state']}), reference {r['reference_id']}" for r in recs[:3]) + ".")
            f = s.frame(a, EB)
            parts["Model reconstruction"].append(f"At {ma_text(f['age_ma'])} the Indian Plate was near " + pos_text(f["india"][EB]["india"]) + " (EarthByte)" + (" and " + pos_text(f["india"][PM]["india"]) + " (PALEOMAP)" if f["india"][PM]["india"] else "") + ".")
            parts["Uncertainty"].append("A fossil at a modern coordinate shows that animals lived near that place within the stated age range; it does not show what the whole region looked like. Absence of records is not absence of animals. Age ranges are as entered in PBDB.")
        elif any(w in q for w in ("himalaya", "collision", "eurasia", "mountain", "uttarakhand", "dhauliganga")):
            a = age if age is not None else 50.0
            st = min(s.himalaya()["stages"], key=lambda x: abs(x["age_ma"] - a))
            parts["Model reconstruction"].append(f"At {st['label']} the model places the Indian Plate near {pos_text(st['india_position'][EB])} (EarthByte); the India to Eurasia rigid-plate gap is {st['india_eurasia_gap_km'][EB]} km (EarthByte) and {st['india_eurasia_gap_km'][PM]} km (PALEOMAP).")
            parts["Published interpretation"].append(f"{st['stage']}. Collision: {st['collision']} {st['process']} Mountains: {st['mountains']} (references {st['sources']}).")
            parts["Uncertainty"].append(st["uncertainty"] + " Collision onset estimates range from about 65 to 35 Ma; no single date is agreed.")
            hp = s.place("mountain:himalayas", a)
            if hp and hp.get("paleogeography_context"):
                parts["Dataset records"].append(f"Cao et al. (2017) classify the reconstructed position of the modern Himalayan reference point at {ma_text(hp['age_ma'])} as: {hp['paleogeography_context']}.")
        elif any(w in q for w in ("gondwana", "move", "journey", "where was india", "plate")):
            a = age if age is not None else 100.0
            f = s.frame(a, EB)
            parts["Model reconstruction"].append(f"At {ma_text(f['age_ma'])} ({f['period']}, {f['epoch']}) a reference point on the Indian Plate (modern 28.5N, 80E) was near {pos_text(f['india'][EB]['india'])} in the EarthByte model" + (f" and {pos_text(f['india'][PM]['india'])} in PALEOMAP; the models differ by about {f['models_disagree_km']:,} km." if f["india"][PM]["india"] and f["models_disagree_km"] is not None else "."))
            for e in f["events"][:3]:
                parts["Published interpretation"].append(f"{e['event_name']} ({e['start_age_ma']:g} to {e['end_age_ma']:g} Ma; sources {e['evidence_source']}; confidence {e['confidence']}).")
            parts["Uncertainty"].append(f["confidence"])
        elif place:
            a = age if age is not None else (age_ma if age_ma is not None else 66.0)
            p = s.place(place, a)
            if p:
                parts["Model reconstruction"].append(p["explanation"])
                ctx = p["paleogeography_context"]
                if ctx:
                    parts["Dataset records"].append(f"Cao et al. (2017) classify the reconstructed position at {ma_text(p['age_ma'])} as: {ctx}.")
                parts["Uncertainty"].append(" ".join(p["limitations"][:2]))
            else:
                parts["Uncertainty"].append("That place is not in the reference list, so no reconstruction is available for it.")
        else:
            a = age if age is not None else (age_ma or 0.0)
            f = s.frame(a, EB)
            parts["Dataset records"].append(f"ICS time scale: {ma_text(f['age_ma'])} falls in the {f['period']} period, {f['epoch']} epoch, {f['era']} era" + (f"; {f['boundary']}" if f["boundary"] else "") + ".")
            parts["Model reconstruction"].append(f"The Indian Plate reference point was near {pos_text(f['india'][EB]['india'])} (EarthByte).")
            for e in f["events"][:3]:
                parts["Published interpretation"].append(f"{e['event_name']} (sources {e['evidence_source']}).")
            parts["Uncertainty"].append(f["confidence"])
        out = [f"{k}: {' '.join(v)}" for k, v in parts.items() if v]
        return "\n".join(out) if out else "The available data cannot answer that question."


def pos_text(p) -> str:
    if not p:
        return "an unavailable position"
    return f"{abs(p[0]):.1f}{'N' if p[0] >= 0 else 'S'}, {abs(p[1]):.1f}{'E' if p[1] >= 0 else 'W'}"
