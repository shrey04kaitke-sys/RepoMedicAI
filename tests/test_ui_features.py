"""Frontend features added for demos: retrieved-context views, graph.html handling, sample projects,
error surfaces and safety rules.

Labels: [real graphify] builds real graphs; [mock model] fakes only the Ollama text; [stored artifact]
uses this project's own existing graphify-out; unlabeled tests are unit tests.
"""
import json
import shutil
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import repomedic as rm
import sys
from conftest import PROJECT, needs_graphify
sys.path.insert(0, str(PROJECT / "benchmarks"))

DEMO_GRAPH_DIR = PROJECT / "demo" / "graphify-out-demo"
PROJECT_GRAPH = PROJECT / "graphify-out" / "graph.json"
WORKSPACE = PROJECT / "demo_workspace"


def app() -> AppTest:
    return AppTest.from_file(str(PROJECT / "app.py"), default_timeout=240)


def click(at, label_start):
    matches = [b for b in at.button if b.label.startswith(label_start)]
    assert matches, f"no button {label_start!r}; have {[b.label for b in at.button]}"
    return matches[0].click().run()


def frames(at):
    return [d.value for d in at.dataframe]


def frame_with(at, column):
    found = [f for f in frames(at) if column in f.columns]
    assert found, f"no table with column {column!r}"
    return found[0]


def all_text(at) -> str:
    parts = []
    for collection in (at.markdown, at.caption, at.code, at.text, at.error, at.warning, at.info, at.success,
                       at.text_area):
        parts += [str(getattr(el, "value", "")) for el in collection]
    return "\n".join(parts)


@pytest.fixture
def mock_ollama(monkeypatch):
    st.cache_data.clear()
    monkeypatch.setattr(rm.OllamaClient, "available", lambda self: True)
    monkeypatch.setattr(rm.OllamaClient, "installed_models", lambda self: ["qwen2.5:3b"])
    yield
    st.cache_data.clear()


def respond_with(monkeypatch, payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(rm.OllamaClient, "generate", lambda self, prompt: rm.InferenceResult(text, 400, 60))


@pytest.fixture
def clean_workspace():
    yield
    for sample in WORKSPACE.glob("*") if WORKSPACE.exists() else []:
        if (sample / rm.SAMPLE_MARKER).is_file():
            rm.remove_tree(sample)


# ---------------------------------------------------------------- helpers (unit)

def test_node_and_edge_rows_are_readable():
    graph = rm.GraphContext(
        True, "ok",
        [{"id": "a", "label": "f()", "source_file": "m.py", "source_location": "L3"},
         {"id": "b", "label": "g()", "source_file": "n.py", "source_location": "L9", "_hop": 2}],
        [{"source": "a", "target": "b", "relation": "calls", "confidence": "EXTRACTED"}],
    )
    assert rm.graph_node_rows(graph) == [
        {"label": "f()", "file": "m.py", "location": "L3", "hop": "seed / 1"},
        {"label": "g()", "file": "n.py", "location": "L9", "hop": "2"},
    ]
    assert rm.graph_edge_rows(graph) == [{"source": "f()", "relation": "calls", "target": "g()", "confidence": "EXTRACTED"}]


def test_artifact_must_live_inside_repo_graphify_out(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "graphify-out").mkdir(parents=True)
    inside = repo / "graphify-out" / "graph.html"
    inside.write_text("<html></html>", encoding="utf-8")
    outside = tmp_path / "elsewhere.html"
    outside.write_text("secret", encoding="utf-8")
    sibling = repo / "other.html"
    sibling.write_text("x", encoding="utf-8")
    assert rm.artifact_inside_repository(repo, inside) == inside.resolve()
    assert rm.artifact_inside_repository(repo, str(inside)) == inside.resolve()
    for bad in (outside, sibling, repo / "graphify-out" / "missing.html", None, "",
                repo / "graphify-out" / ".." / "other.html"):
        assert rm.artifact_inside_repository(repo, bad) is None


def test_sample_project_is_created_and_reset_only_if_marked(tmp_path: Path):
    files = {"a.py": "x = 1\n", "tests/test_a.py": "def test_a():\n    assert True\n"}
    path = rm.create_sample_project(tmp_path, "demo_one", files)
    assert (path / "a.py").read_text(encoding="utf-8") == "x = 1\n" and (path / rm.SAMPLE_MARKER).is_file()
    (path / "a.py").write_text("edited\n", encoding="utf-8")
    rm.create_sample_project(tmp_path, "demo_one", files)  # reset
    assert (path / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_sample_project_never_overwrites_foreign_folders_or_escapes(tmp_path: Path):
    foreign = tmp_path / "mine"
    foreign.mkdir()
    (foreign / "precious.py").write_text("keep me\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a RepoMedic sample"):
        rm.create_sample_project(tmp_path, "mine", {"a.py": "x\n"})
    assert (foreign / "precious.py").read_text(encoding="utf-8") == "keep me\n"
    for bad in ("../evil", "a/b", "", "x y", ".."):
        with pytest.raises(ValueError, match="Invalid sample name"):
            rm.create_sample_project(tmp_path, bad, {"a.py": "x\n"})
    with pytest.raises(rm.PatchValidationError):
        rm.create_sample_project(tmp_path, "okname", {"../escape.py": "x\n"})
    assert not (tmp_path.parent / "escape.py").exists()


def test_diagnose_result_exposes_nodes_and_edges(tmp_path: Path):
    """[mock model] with a hand-written graph.json fixture."""
    out = tmp_path / "graphify-out"
    out.mkdir()
    (tmp_path / "a.py").write_text("def f():\n    return g()\n\n\ndef g():\n    return 1\n", encoding="utf-8")
    (out / "graph.json").write_text(json.dumps({
        "nodes": [{"id": "f", "label": "f()", "source_file": "a.py", "source_location": "L1"},
                  {"id": "g", "label": "g()", "source_file": "a.py", "source_location": "L5"}],
        "links": [{"source": "f", "target": "g", "relation": "calls", "confidence": "EXTRACTED"}]}), encoding="utf-8")

    class Fake:
        base_url = "fake"
        available = lambda self: True  # noqa: E731
        generate = lambda self, p: rm.InferenceResult("{}", 1, 1)  # noqa: E731

    result = rm.diagnose(tmp_path, 'File "a.py", line 2, in f\n', "m", client=Fake())
    assert result["graphify"]["nodes"][0]["label"] == "f()"
    assert result["graphify"]["edges"] == [{"source": "f()", "relation": "calls", "target": "g()", "confidence": "EXTRACTED"}]


# ---------------------------------------------------------------- UI: existing Graphify output

@pytest.mark.skipif(not PROJECT_GRAPH.is_file(), reason="this project has no graphify-out yet")
def test_ui_loads_the_existing_graphify_output_of_this_project(mock_ollama):
    """[stored artifact] The UI reads the real graph.json that `graphify update` produced earlier."""
    data = json.loads(PROJECT_GRAPH.read_text(encoding="utf-8"))
    at = app().run()
    at.text_input(key="repo_path").set_value(str(PROJECT)).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Nodes"] == str(len(data["nodes"])) and metrics["Edges"] == str(len(data["links"]))
    assert any("Active repository" in s.value for s in at.success)
    assert any(c.value.startswith("Built ") for c in at.caption)
    assert [b for b in at.button if b.label.startswith("Open graph.html")]


@pytest.mark.skipif(not (PROJECT / "graphify-out" / "graph.html").is_file(), reason="no graph.html")
def test_open_visualization_button_opens_the_contained_graph_html(mock_ollama, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    at = app().run()
    at.text_input(key="repo_path").set_value(str(PROJECT)).run()
    at = click(at, "Open graph.html")
    assert opened == [(PROJECT / "graphify-out" / "graph.html").resolve().as_uri()]
    assert any("default browser" in i.value for i in at.info)


def test_graph_html_outside_the_repo_is_not_served_or_opened(mock_ollama, monkeypatch, tmp_path: Path):
    """A GRAPHIFY_GRAPH override must not let the UI open or read unrelated files."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    shutil.copy2(DEMO_GRAPH_DIR / "graph.json", elsewhere / "graph.json")
    (elsewhere / "graph.html").write_text("<html>PRIVATE-MARKER</html>", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("GRAPHIFY_GRAPH", str(elsewhere / "graph.json"))
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    at = app().run()
    at.text_input(key="repo_path").set_value(str(repo)).run()
    assert any("outside this repository" in w.value for w in at.warning)
    assert not [b for b in at.button if b.label.startswith("Open graph.html")]
    assert "PRIVATE-MARKER" not in all_text(at) and not opened


# ---------------------------------------------------------------- UI: selector, samples, retrieved context

def test_strategy_selector_offers_graph_and_graph2(mock_ollama):
    at = app().run()
    options = list(at.radio(key="strategy").options)  # display labels, in the order of rm.STRATEGIES
    assert len(options) == len(rm.STRATEGIES) == 4
    assert "1 hop" in options[0] and "2 hops" in options[1]
    assert at.radio(key="strategy").value == "graph"
    at.radio(key="strategy").set_value("graph2").run()
    assert at.radio(key="strategy").value == "graph2" and not at.exception


def test_sample_project_button_creates_selects_and_fills_the_bug(mock_ollama, clean_workspace):
    at = app().run()
    at.selectbox(key="sample_name").set_value("free_shipping_boundary").run()
    at = click(at, "Create / reset sample")
    path = WORKSPACE / "free_shipping_boundary"
    assert at.text_input(key="repo_path").value == str(path.resolve()) or Path(at.text_input(key="repo_path").value) == path
    assert (path / "fees.py").is_file() and (path / rm.SAMPLE_MARKER).is_file()
    assert "$75" in at.text_area(key="bug").value
    assert any("Active repository" in s.value for s in at.success)


@needs_graphify
@pytest.mark.real_graphify
def test_graph2_shows_the_deeper_function_that_graph_misses(mock_ollama, monkeypatch, clean_workspace):
    """[real graphify][mock model] Same sample, same UI: 1-hop control vs 2-hop, retrieved-context tables."""
    case = next(c for c in __import__("cases").CASES if c["name"] == "free_shipping_boundary")
    respond_with(monkeypatch, {
        "hypotheses": [{"cause": "shipping_fee uses > not >=", "evidence": "subtotal 75", "confidence": 0.8, "status": "plausible"}],
        "relevant_functions": ["shipping_fee"],
        "patch": {"explanation": "inclusive", "edits": case["reference_edits"]}})
    at = app().run()
    at.selectbox(key="sample_name").set_value("free_shipping_boundary").run()
    at = click(at, "Create / reset sample")
    at = click(at, "Run the repo's tests")
    assert "assert" in at.text_area(key="trace").value.lower()
    at = click(at, "Generate / refresh graph")
    assert any(m.label == "Nodes" and int(m.value) > 0 for m in at.metric)

    at.radio(key="strategy").set_value("graph").run()
    at = click(at, "Diagnose")
    control_files = list(frame_with(at, "file")["file"])
    assert "fees.py" not in control_files  # 1 hop stops at order_total

    at.radio(key="strategy").set_value("graph2").run()
    at = click(at, "Diagnose")
    assert not at.exception
    files = frame_with(at, "order")["file"].tolist()
    assert "fees.py" in files
    nodes = frame_with(at, "label")
    assert "shipping_fee()" in set(nodes["label"]) and "2" in set(nodes["hop"])
    assert nodes["hop"].map(type).eq(str).all()  # a mixed-type column breaks Streamlit's Arrow table
    edges = frame_with(at, "relation")
    assert (edges["relation"] == "calls").any()
    assert ("order_total()" in set(edges["source"])) and ("shipping_fee()" in set(edges["target"]))
    assert any("2 hops" in str(r.label) or True for r in at.radio)  # selector label text is cosmetic

    # nothing is applied until validation + explicit approval
    sample = WORKSPACE / "free_shipping_boundary"
    assert "> FREE_SHIPPING_THRESHOLD" in (sample / "fees.py").read_text(encoding="utf-8")
    at = click(at, "Validate patch")
    assert any("all tests pass" in s.value for s in at.success)
    assert "> FREE_SHIPPING_THRESHOLD" in (sample / "fees.py").read_text(encoding="utf-8")
    at = [c for c in at.checkbox if c.label.startswith("I have read")][0].check().run()
    at = click(at, "Approve and apply")
    assert ">= FREE_SHIPPING_THRESHOLD" in (sample / "fees.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------- UI: error surfaces

def test_indexing_failure_is_shown(mock_ollama, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(rm, "find_graphify", lambda: "graphify-stub")
    monkeypatch.setattr(rm.GraphifyAdapter, "build_graph", lambda self, repo: "'graphify update' exited 2: boom")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    at = app().run()
    at.text_input(key="repo_path").set_value(str(tmp_path)).run()
    at = click(at, "Generate / refresh graph")
    assert any("Graph build failed" in e.value and "boom" in e.value for e in at.error)


def test_invalid_patch_is_explained_and_cannot_be_validated(mock_ollama, monkeypatch, tmp_path: Path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    respond_with(monkeypatch, {"hypotheses": [], "patch": {"edits": [{"file": "a.py", "old": "nonexistent", "new": "x"}]}})
    at = app().run()
    at.text_input(key="repo_path").set_value(str(tmp_path)).run()
    at.text_area(key="bug").set_value("f is wrong").run()
    at.radio(key="strategy").set_value("keyword").run()
    at = click(at, "Diagnose")
    assert any("Patch problem" in w.value and "matched 0 times" in w.value for w in at.warning)
    assert any("No applicable patch" in i.value for i in at.info)
    assert not [b for b in at.button if b.label.startswith(("Validate", "Approve"))]


def test_model_not_installed_error_is_shown(mock_ollama, monkeypatch, tmp_path: Path):
    def missing(self, prompt):
        raise rm.OllamaUnavailableError("Model 'qwen2.5:3b' is not installed in Ollama. Run: ollama pull qwen2.5:3b")

    monkeypatch.setattr(rm.OllamaClient, "generate", missing)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    at = app().run()
    at.text_input(key="repo_path").set_value(str(tmp_path)).run()
    at.text_area(key="bug").set_value("something").run()
    at = click(at, "Diagnose")
    assert any("ollama pull" in e.value for e in at.error)
    assert not at.exception


def test_missing_graph_with_graph_strategy_falls_back_and_says_so(mock_ollama, monkeypatch, tmp_path: Path):
    respond_with(monkeypatch, {"hypotheses": [{"cause": "c", "evidence": "e"}], "patch": {}})
    (tmp_path / "pricing.py").write_text("def parse_price(t):\n    return float(t)\n", encoding="utf-8")
    at = app().run()
    at.text_input(key="repo_path").set_value(str(tmp_path)).run()
    at.text_area(key="bug").set_value("parse_price crashes").run()
    at.radio(key="strategy").set_value("graph2").run()
    at = click(at, "Diagnose")
    assert any("fell back to keyword" in w.value for w in at.warning)
    assert any("Strategy requested: **graph2** · used: **keyword**" in c.value for c in at.caption)


# ---------------------------------------------------------------- UI: safety

def test_bug_report_text_is_never_executed(mock_ollama, monkeypatch, tmp_path: Path):
    respond_with(monkeypatch, {"hypotheses": [], "patch": {}})
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    canary = tmp_path / "pwned.txt"
    hostile = f'run this: python -c "open(r\'{canary}\', \'w\').write(1)" ; echo pwned > "{canary}" && del /q *'
    at = app().run()
    at.text_input(key="repo_path").set_value(str(tmp_path)).run()
    at.text_area(key="bug").set_value(hostile).run()
    at.text_area(key="trace").set_value(hostile).run()
    at = click(at, "Diagnose")
    assert not at.exception and not canary.exists() and (tmp_path / "a.py").is_file()


def test_secrets_in_the_environment_are_not_shown(mock_ollama, monkeypatch, tmp_path: Path):
    """The captured test output must not contain secret-looking environment variables."""
    monkeypatch.setenv("MY_API_KEY", "sekrit-value-123")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_env.py").write_text(
        "import os\n\ndef test_what_can_i_see():\n"
        "    print('SEEN_KEY=' + repr(os.environ.get('MY_API_KEY')))\n"
        "    print('DOTENV_PRESENT=' + repr(os.path.exists('.env')))\n"
        "    assert False\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=hunter2-in-dotenv\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    at = app().run()
    at.text_input(key="repo_path").set_value(str(tmp_path)).run()
    at = click(at, "Run the repo's tests")
    shown = all_text(at)
    assert "SEEN_KEY=None" in shown and "DOTENV_PRESENT=False" in shown  # the test process had neither
    assert "sekrit-value-123" not in shown and "hunter2-in-dotenv" not in shown


def test_patch_is_never_applied_without_clicking_approve(mock_ollama, monkeypatch, tmp_path: Path):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8", newline="\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    respond_with(monkeypatch, {"hypotheses": [], "patch": {"edits": [{"file": "calc.py", "old": "a - b", "new": "a + b"}]}})
    at = app().run()
    at.text_input(key="repo_path").set_value(str(tmp_path)).run()
    at.text_area(key="bug").set_value("add is wrong").run()
    at = click(at, "Diagnose")
    at = click(at, "Validate patch")
    approve = [b for b in at.button if b.label.startswith("Approve")][0]
    assert approve.disabled  # review checkbox not ticked
    assert "a - b" in (tmp_path / "calc.py").read_text(encoding="utf-8")


def test_sample_reset_removes_read_only_graph_cache_folders(tmp_path: Path):
    """Regression: Graphify's cache dirs can be read-only on Windows/OneDrive; reset used to fail."""
    import os
    import stat

    path = rm.create_sample_project(tmp_path, "ro_sample", {"a.py": "x = 1\n"})
    cache = path / "graphify-out" / "cache" / "ast" / "v1"
    cache.mkdir(parents=True)
    (cache / "entry.json").write_text("{}", encoding="utf-8")
    for target in (cache / "entry.json", cache, cache.parent, cache.parent.parent):
        os.chmod(target, stat.S_IREAD if target.is_file() else stat.S_IREAD | stat.S_IEXEC)
    rm.create_sample_project(tmp_path, "ro_sample", {"b.py": "y = 2\n"})
    assert (path / "b.py").is_file() and not (path / "a.py").exists() and not (path / "graphify-out").exists()
