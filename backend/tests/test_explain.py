"""The explanation layer: deterministic, evidence-backed, cautious, and free of any external AI."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.schemas import AnalyzeRequest, CompareRequest
from app.services.analysis import analyze_series, compare_regions
from app.services.explain import explain_analysis, explain_comparison
from app.services.store import DatasetStore

from .helpers import canonical_df, make_record

DEMO = "synthetic-demo"
CAUSAL = (" caused ", " because of ", " due to ", " leads to ", " drives ", " proves ", " proof of ")


@pytest.fixture()
def demo(settings):
    store = DatasetStore(settings)
    store.load_all()
    return store.get(DEMO)


def texts(expl) -> list[str]:
    return [s.text for sec in expl.sections for s in sec.statements]


def annual(values, **kw):
    return canonical_df(values, dates=pd.date_range("1960-01-01", periods=len(values), freq="YS"), **kw)


def test_explanations_are_deterministic(demo):
    req = AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Alpha")
    a1, a2 = analyze_series(demo, req), analyze_series(demo, req)
    assert a1.explanation.model_dump_json() == a2.explanation.model_dump_json()
    assert explain_analysis(a1).model_dump_json() == a1.explanation.model_dump_json()
    creq = CompareRequest(dataset_id=DEMO, variable="Synthetic Index A", regions=["Region Alpha", "Region Beta"])
    assert compare_regions(demo, creq).explanation.model_dump_json() == compare_regions(demo, creq).explanation.model_dump_json()


def test_no_external_ai_is_required_or_imported(demo):
    analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Alpha"))
    for module in ("openai", "groq", "anthropic", "google.generativeai", "google.genai", "cohere"):
        assert module not in sys.modules, module
    reqs = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text().lower()
    for name in ("openai", "groq", "anthropic", "google-generativeai", "cohere", "langchain"):
        assert name not in reqs
    src = "".join(p.read_text(encoding="utf-8").lower() for p in (Path(__file__).resolve().parent.parent / "app").rglob("*.py"))
    assert "api_key" not in src and "import requests" not in src and "urllib.request" not in src
    expl = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Alpha")).explanation
    assert expl.uses_external_ai is False and expl.generator == "deterministic-rules-v1"


def test_significant_result_wording_and_evidence(demo):
    a = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Beta"))
    t = " ".join(texts(a.explanation))
    assert "statistical evidence of a monotonic decreasing trend" in t
    assert "synthetic demo data" in t.lower()
    assert "does not identify why" in t
    assert f"{a.coverage.n_valid} valid observations" in t
    assert str(a.coverage.first_date) in t
    # every sentence in the result section is backed by evidence pairs taken from the computed numbers
    result = next(s for s in a.explanation.sections if s.heading == "Statistical result")
    assert all(st.evidence for st in result.statements)
    slope_stmt = next(st for st in result.statements if "estimated rate of change" in st.text)
    assert any(e["label"] == "confidence interval" for e in slope_stmt.evidence)


def test_non_significant_result_never_claims_there_is_no_trend(demo):
    a = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Gamma"))
    assert not a.primary.significant
    t = " ".join(texts(a.explanation))
    assert "did not find sufficient statistical evidence of a monotonic trend" in t
    assert "does not show that no trend exists" in t
    low = t.lower()
    assert "there is no trend" not in low and "no trend exists." not in low and "proves" not in low


def test_interval_including_zero_is_called_uncertain():
    y = np.random.default_rng(31).normal(size=40)
    a = analyze_series(make_record(annual(y)), AnalyzeRequest(dataset_id="fixture-id", variable="V1", region="R1"))
    assert a.primary.slope_ci_low <= 0 <= a.primary.slope_ci_high
    assert any("includes zero" in s and "uncertain" in s for s in texts(a.explanation))


def test_opposite_regions_are_described_with_caution(demo):
    c = compare_regions(demo, CompareRequest(dataset_id=DEMO, variable="Synthetic Index A", regions=["Region Alpha", "Region Beta"]))
    t = " ".join(texts(c.explanation))
    assert "opposite" in t and "increasing in Region Alpha" in t and "decreasing in Region Beta" in t
    assert "Benjamini-Hochberg" in t
    assert "does not establish a cause" in t
    assert "represent every location" in t  # a regional series is not the whole region


def test_comparison_lists_every_region_with_its_own_statistics(demo):
    c = compare_regions(demo, CompareRequest(dataset_id=DEMO, variable="Synthetic Index A", regions=["Region Alpha", "Region Beta", "Region Gamma"]))
    result = next(s for s in c.explanation.sections if s.heading == "Statistical result")
    for region in ("Region Alpha", "Region Beta", "Region Gamma"):
        stmt = next(st for st in result.statements if st.text.startswith(region))
        row = next(r for r in c.rows if r.region == region)
        assert f"n = {row.n_valid}" in stmt.text
        assert any(e["label"] == "adjusted p value" for e in stmt.evidence)


def test_exploratory_status_is_stated_in_the_explanation():
    rng = np.random.default_rng(3)
    days = np.sort(rng.choice(np.arange(0, 6000), size=60, replace=False))
    dates = pd.Timestamp("2000-01-01") + pd.to_timedelta(days, unit="D")
    a = analyze_series(make_record(canonical_df(rng.normal(size=60), dates=dates)), AnalyzeRequest(dataset_id="fixture-id", variable="V1", region="R1"))
    t = " ".join(texts(a.explanation))
    assert a.primary.status == "exploratory_uncorrected"
    assert "exploratory" in t and "could not be assessed" in t


def test_corrected_status_is_stated_in_the_explanation():
    rng = np.random.default_rng(12)
    e = rng.normal(0, 1, 80)
    y = np.zeros(80)
    y[0] = e[0]
    for i in range(1, 80):
        y[i] = 0.75 * y[i - 1] + e[i]
    a = analyze_series(make_record(annual(y + 0.02 * np.arange(80))), AnalyzeRequest(dataset_id="fixture-id", variable="V1", region="R1"))
    assert a.primary.status == "autocorrelation_corrected"
    assert any("Hamed & Rao" in s and "corrected" in s for s in texts(a.explanation))


def test_insufficient_data_is_explained_without_speculation():
    a = analyze_series(make_record(canonical_df([1, 2, 3, 4, 5, 6])), AnalyzeRequest(dataset_id="fixture-id", variable="V1", region="R1"))
    t = " ".join(texts(a.explanation))
    assert "No trend test could be run" in t and "cannot say anything reliable" in t
    assert "increasing" not in t.lower().replace("estimated direction", "")


def test_no_sentence_asserts_causation_or_invents_mechanisms(demo):
    for variable, region in [("Synthetic Index A", "Region Alpha"), ("Synthetic Index B", "Region Beta"), ("Synthetic Index A", "Region Gamma")]:
        a = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable=variable, region=region))
        joined = " " + " ".join(texts(a.explanation)).lower() + " "
        assert not any(w in joined for w in CAUSAL), (variable, region)
        for word in ("nasa", "satellite", "climate change", "warming", "drought", "emissions", "mission"):
            assert word not in joined
    c = compare_regions(demo, CompareRequest(dataset_id=DEMO, variable="Synthetic Index A", regions=["Region Alpha", "Region Beta"]))
    joined = " " + " ".join(texts(c.explanation)).lower() + " "
    assert not any(w in joined for w in CAUSAL)
    assert "nasa" not in joined


def test_explain_functions_are_pure_functions_of_the_response(demo):
    a = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Alpha"))
    a2 = a.model_copy(deep=True)
    a2.primary.p_value = 0.5
    a2.primary.significant = False
    assert explain_analysis(a2).model_dump_json() != explain_analysis(a).model_dump_json()
    assert "did not find sufficient" in " ".join(texts(explain_analysis(a2)))
