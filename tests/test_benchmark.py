"""Benchmark harness tests: the cases themselves are validated with the real test runner (no model)."""
import sys
from pathlib import Path

import pytest

from conftest import PROJECT

sys.path.insert(0, str(PROJECT / "benchmarks"))
import run_benchmark as rb  # noqa: E402
from cases import CASES, build_case  # noqa: E402


def test_case_definitions_are_complete_and_unique():
    names = [c["name"] for c in CASES]
    assert len(names) == len(set(names)) >= 5
    for case in CASES:
        assert {"bug", "files", "bug_file", "bug_function", "relevant_files", "diagnosis_keywords",
                "reference_edits"} <= set(case)
        assert case["bug_file"] in case["files"]
        assert any(f.startswith("tests/") for f in case["files"])


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_every_case_fails_before_and_passes_after_the_reference_fix(case, tmp_path: Path):
    """Real pytest runs in isolated copies; proves the benchmark cases are valid ground truth."""
    build_case(case, tmp_path)
    checked = rb.sanity_check(case, tmp_path)
    assert "FAILED" in checked["failing_output"] or "failed" in checked["failing_output"]


def test_retrieval_scoring():
    case = CASES[0]
    scored = rb.score_retrieval(case, ["pricing.py", "cart.py", "inventory.py"])
    assert scored["bug_file_retrieved"] is True
    assert 0 < scored["precision"] < 1 and 0 < scored["relevant_recall"] < 1
    assert rb.score_retrieval(case, [])["precision"] == 0.0


def test_diagnosis_scoring_requires_both_location_and_cause():
    case = CASES[0]
    base = {"hypotheses": [], "relevant_functions": [], "patch": {"explanation": ""}}
    hit = {**base, "hypotheses": [{"cause": "parse_price fails on the comma", "evidence": ""}]}
    only_location = {**base, "hypotheses": [{"cause": "parse_price is wrong", "evidence": ""}]}
    only_cause = {**base, "hypotheses": [{"cause": "a thousand separator breaks float()", "evidence": ""}]}
    assert rb.score_diagnosis(case, hit)["diagnosis_heuristic_ok"] is True
    assert rb.score_diagnosis(case, only_location)["diagnosis_heuristic_ok"] is False
    assert rb.score_diagnosis(case, only_cause)["diagnosis_heuristic_ok"] is False


def test_summary_aggregates_and_counts_errors():
    records = [
        {"model": "m", "strategy": "graph", "prompt_tokens": 100, "prompt_chars": 400, "files": ["a.py"],
         "bug_file_retrieved": True, "relevant_recall": 1.0, "precision": 1.0, "retrieval_s": 0.1,
         "inference_s": 2.0, "located_bug": True, "diagnosis_heuristic_ok": False,
         "patch_produced": True, "patch_validated": False},
        {"model": "m", "strategy": "graph", "error": "RuntimeError: timed out"},
    ]
    (row,) = rb.summarise(records)
    assert row["runs"] == 1 and row["errors"] == 1 and row["mean_prompt_tokens"] == 100
    assert row["bug_file_recall"] == 1.0 and row["patch_validated_rate"] == 0.0
