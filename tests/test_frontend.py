"""Streamlit frontend tests using Streamlit's headless AppTest.

The UI calls the real backend: real isolated pytest runs, real validation copies, real file apply.
[mock model] marks tests where only the Ollama response is faked. [real graphify]/[real ollama]
mark tests that invoke those tools.
"""
import json
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import repomedic as rm
from conftest import PROJECT, installed_models, needs_graphify, needs_ollama

BUGGY = "def add(a, b):\n    return a - b\n"
TEST = (
    "import sys, pathlib\n"
    "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
    "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
)
FIX_RESPONSE = {
    "hypotheses": [{"cause": "add subtracts", "evidence": "test expects 5", "confidence": 0.9, "status": "verified"}],
    "relevant_functions": ["add"],
    "patch": {"explanation": "use +", "edits": [{"file": "calc.py", "old": "return a - b", "new": "return a + b"}]},
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "calc.py").write_text(BUGGY, encoding="utf-8", newline="\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8", newline="\n")
    return tmp_path


@pytest.fixture
def fake_ollama(monkeypatch):
    """[mock model] Ollama is 'running' with one model and answers with FIX_RESPONSE."""
    st.cache_data.clear()
    monkeypatch.setattr(rm.OllamaClient, "available", lambda self: True)
    monkeypatch.setattr(rm.OllamaClient, "installed_models", lambda self: ["qwen2.5:3b"])
    monkeypatch.setattr(
        rm.OllamaClient, "generate",
        lambda self, prompt: rm.InferenceResult(json.dumps(FIX_RESPONSE), 321, 45),
    )
    yield
    st.cache_data.clear()


def app() -> AppTest:
    return AppTest.from_file(str(PROJECT / "app.py"), default_timeout=180)


def click(at: AppTest, label_start: str) -> AppTest:
    matches = [b for b in at.button if b.label.startswith(label_start)]
    assert matches, f"no button starting with {label_start!r}: {[b.label for b in at.button]}"
    return matches[0].click().run()


def checkbox(at: AppTest, label_start: str):
    return [c for c in at.checkbox if c.label.startswith(label_start)][0]


def test_app_starts_without_errors_and_validates_repo_path(repo: Path, fake_ollama):
    at = app().run()
    assert not at.exception
    diagnose = [b for b in at.button if b.label.startswith("Diagnose")][0]
    assert diagnose.disabled  # nothing entered yet
    at.text_input(key="repo_path").set_value(str(repo / "does-not-exist")).run()
    assert any("Not a directory" in e.value for e in at.error)
    at.text_input(key="repo_path").set_value(str(repo)).run()
    assert not any("Not a directory" in e.value for e in at.error)
    assert any("readable source files" in c.value for c in at.caption)


def test_app_reports_unreachable_ollama(monkeypatch, repo: Path):
    st.cache_data.clear()
    monkeypatch.setattr(rm.OllamaClient, "available", lambda self: False)
    at = app().run()
    assert any("Ollama is not reachable" in e.value for e in at.sidebar.error)
    at.text_input(key="repo_path").set_value(str(repo)).run()
    at.text_area(key="bug").set_value("add is wrong").run()
    assert [b for b in at.button if b.label.startswith("Diagnose")][0].disabled
    st.cache_data.clear()


def test_app_reports_missing_graphify(monkeypatch, fake_ollama, repo: Path):
    monkeypatch.setattr(rm, "find_graphify", lambda: None)
    at = app().run()
    assert any("Graphify CLI not found" in e.value for e in at.sidebar.error)
    at.text_input(key="repo_path").set_value(str(repo)).run()
    assert any("No graph found" in w.value for w in at.warning)
    assert [b for b in at.button if b.label.startswith("Generate")][0].disabled


@needs_graphify
@pytest.mark.real_graphify
def test_full_flow_capture_graph_diagnose_validate_approve_apply(repo: Path, fake_ollama):
    """[real graphify][mock model] Every step except the LLM text is real."""
    at = app().run()
    at.text_input(key="repo_path").set_value(str(repo)).run()

    at = click(at, "Run the repo's tests")  # real isolated pytest run
    assert "assert" in at.text_area(key="trace").value.lower()
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY

    at = click(at, "Generate / refresh graph")  # real `graphify update`
    assert not at.exception and (repo / "graphify-out" / "graph.json").is_file()
    assert any(m.label == "Nodes" and int(m.value) > 0 for m in at.metric)

    at.text_area(key="bug").set_value("add returns the wrong result").run()
    at = click(at, "Diagnose")
    assert not at.exception, [str(e) for e in at.exception]
    assert any("1/2 Retrieving" in str(m.value) for m in at.markdown) or at.metric  # progress + results
    assert [m.value for m in at.metric if m.label == "Prompt tokens"] == ["321"]
    diff_blocks = [c.value for c in at.code if c.language == "diff"]
    assert diff_blocks and "+    return a + b" in diff_blocks[0]
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY  # nothing applied yet

    # approval controls must not be actionable before validation
    assert not [b for b in at.button if b.label.startswith("Approve")]

    at = click(at, "Validate patch")  # real isolated copy + pytest, before and after
    assert any("all tests pass in the isolated copy" in s.value for s in at.success)
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY  # still untouched

    approve = [b for b in at.button if b.label.startswith("Approve")][0]
    assert approve.disabled  # needs the review checkbox
    at = checkbox(at, "I have read the diff").check().run()
    at = click(at, "Approve and apply")
    assert any("Applied to calc.py" in s.value for s in at.success)
    assert "return a + b" in (repo / "calc.py").read_text(encoding="utf-8")
    assert list((repo / rm.BACKUP_DIRECTORY).rglob("calc.py"))


def test_reject_leaves_repository_unchanged(repo: Path, fake_ollama):
    """[mock model]"""
    at = app().run()
    at.text_input(key="repo_path").set_value(str(repo)).run()
    at.text_area(key="bug").set_value("add is wrong").run()
    at.radio(key="strategy").set_value("keyword").run()
    at = click(at, "Diagnose")
    at = click(at, "Validate patch")
    at = click(at, "Reject patch")
    assert any("Patch rejected" in i.value for i in at.info)
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY
    assert not (repo / rm.BACKUP_DIRECTORY).exists()


def test_failed_validation_blocks_approval(repo: Path, fake_ollama, monkeypatch):
    """[mock model] A wrong patch fails the real tests and cannot be approved."""
    bad = dict(FIX_RESPONSE, patch={"edits": [{"file": "calc.py", "old": "return a - b", "new": "return a * b"}]})
    monkeypatch.setattr(rm.OllamaClient, "generate", lambda self, p: rm.InferenceResult(json.dumps(bad), 1, 1))
    at = app().run()
    at.text_input(key="repo_path").set_value(str(repo)).run()
    at.text_area(key="bug").set_value("add is wrong").run()
    at = click(at, "Diagnose")
    at = click(at, "Validate patch")
    assert any("tests FAILED" in e.value for e in at.error)
    assert not [b for b in at.button if b.label.startswith("Approve")] or [
        b for b in at.button if b.label.startswith("Approve")][0].disabled
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY


def test_malformed_model_output_is_shown_not_crashing(repo: Path, fake_ollama, monkeypatch):
    """[mock model]"""
    monkeypatch.setattr(rm.OllamaClient, "generate", lambda self, p: rm.InferenceResult("<<not json>>", 5, 5))
    at = app().run()
    at.text_input(key="repo_path").set_value(str(repo)).run()
    at.text_area(key="bug").set_value("add is wrong").run()
    at = click(at, "Diagnose")
    assert not at.exception
    assert any("unusable output" in e.value for e in at.error)


@needs_ollama
@needs_graphify
@pytest.mark.real_ollama
@pytest.mark.real_graphify
def test_frontend_with_real_model_and_real_graph(repo: Path):
    """[real graphify][real ollama] The UI path with the real local model; asserts no crash and no writes."""
    if "qwen2.5:3b" not in installed_models():
        pytest.skip("qwen2.5:3b not installed")
    st.cache_data.clear()
    at = app().run()
    at.text_input(key="repo_path").set_value(str(repo)).run()
    at = click(at, "Run the repo's tests")
    at = click(at, "Generate / refresh graph")
    at.text_area(key="bug").set_value("add(2, 3) returns -1 instead of 5").run()
    at = click(at, "Diagnose")
    assert not at.exception
    tokens = [m.value for m in at.metric if m.label == "Prompt tokens"]
    assert tokens and int(tokens[0]) > 0  # real Ollama counter
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY
    st.cache_data.clear()
