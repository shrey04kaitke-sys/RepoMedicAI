import json
from pathlib import Path

import pytest

from repomedic import (
    GraphifyAdapter,
    InferenceResult,
    OllamaClient,
    PatchValidationError,
    RepositoryInspector,
    TracebackParser,
    parse_model_output,
    validate_approved_patch,
)


@pytest.fixture(autouse=True)
def no_real_graphify_by_default(request, monkeypatch):
    """Mocked/fixture tests must not silently run the real tool; real tests are marked."""
    if "real_graphify" not in request.keywords:
        monkeypatch.setattr("repomedic.find_graphify", lambda: None)


def test_traceback_parser_extracts_frames():
    frames = TracebackParser.parse(
        '  File "src/app.py", line 12, in run\nValueError: bad input'
    )
    assert frames == [{"file": "src/app.py", "line": 12, "function": "run"}]


def test_repository_inspector_excludes_secrets_and_generated_directories(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("secret", encoding="utf-8")
    files = RepositoryInspector(tmp_path).files()
    assert files == [tmp_path / "src" / "main.py"]


def test_graphify_reports_unavailable_without_faking_context(tmp_path: Path):
    context = GraphifyAdapter(command="definitely-not-installed").context(tmp_path, [])
    assert context.available is False
    assert context.entities == []
    assert "not found" in context.message


def test_graphify_does_not_assume_an_unverified_cli(tmp_path: Path):
    context = GraphifyAdapter().context(tmp_path, [])
    assert context.available is False
    assert "interface is unverified" in context.message


def test_graphify_reads_official_graph_json_shape(tmp_path: Path):
    output = tmp_path / "graphify-out"
    output.mkdir()
    (output / "graph.json").write_text(
        json.dumps(
            {
                "directed": False,
                "nodes": [
                    {"id": "fn:run", "source_file": "src/app.py", "label": "run"},
                    {"id": "fn:dep", "source_file": "src/dep.py", "label": "dep"},
                ],
                "links": [{"source": "fn:run", "target": "fn:dep", "kind": "calls"}],
            }
        ),
        encoding="utf-8",
    )
    (output / "graph.html").write_text("<html></html>", encoding="utf-8")
    context = GraphifyAdapter().context(
        tmp_path, [{"file": "src/app.py", "line": 1, "function": "run"}]
    )
    assert context.available is True
    assert [n["id"] for n in context.entities] == ["fn:run", "fn:dep"]
    assert context.relationships == [{"source": "fn:run", "target": "fn:dep", "kind": "calls"}]
    assert context.graph_html == str(output / "graph.html")


def test_graphify_rejects_output_without_entities(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    command = f"{Path(__file__).parent.parent / 'repomedic.py'} {{repository}}"
    context = GraphifyAdapter(command=command).context(tmp_path, [])
    assert context.available is False


def test_adapter_accepts_explicit_json_provider_protocol(tmp_path: Path):
    provider_script = tmp_path / "provider.py"
    provider_script.write_text(
        "import json\n"
        "print(json.dumps({'entities': [{'id': 'fn', 'file': 'app.py'}], "
        "'relationships': [{'source': 'fn', 'target': 'dep'}]}))\n",
        encoding="utf-8",
    )
    provider = f'"{__import__("sys").executable}" "{provider_script}" "{{repository}}"'
    context = GraphifyAdapter(command=provider).context(
        tmp_path, [{"file": "app.py", "line": 1, "function": "run"}]
    )
    assert context.available is True
    assert context.entities == [{"id": "fn", "file": "app.py"}]
    assert context.relationships == [{"source": "fn", "target": "dep"}]


def test_model_output_requires_json_object():
    assert parse_model_output('{"hypotheses": []}') == {"hypotheses": []}
    with pytest.raises(ValueError):
        parse_model_output("not json")
    with pytest.raises(ValueError):
        parse_model_output(json.dumps(["not", "an", "object"]))


def test_approved_patch_is_validated_in_copy_and_preserves_source(tmp_path: Path):
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    patch = """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-value = 1
+value = 2
"""
    result = validate_approved_patch(tmp_path, patch)
    assert result["passed"] is None
    assert result["changed_files"] == ["app.py"]
    assert source.read_text(encoding="utf-8") == "value = 1\n"


def test_patch_rejects_path_traversal(tmp_path: Path):
    patch = """--- a/../secret.txt
+++ b/../secret.txt
@@ -1,1 +1,1 @@
-old
+new
"""
    with pytest.raises(PatchValidationError, match="Unsafe patch path"):
        validate_approved_patch(tmp_path, patch)


def test_ollama_unavailability_is_reported():
    assert OllamaClient("gemma3:1b", "http://127.0.0.1:1").available() is False


def test_inference_result_preserves_actual_token_counter_types():
    result = InferenceResult("{}", 12, 4)
    assert result.prompt_tokens == 12
    assert result.output_tokens == 4


# --- Graphify integration behaviour (graph.json fixtures follow the documented schema;
# --- they are test doubles, NOT output from a real Graphify run) ---

def _write_graph(directory: Path, payload) -> Path:
    out = directory / "graphify-out"
    out.mkdir(exist_ok=True)
    graph = out / "graph.json"
    graph.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return graph


def test_graph_context_includes_one_hop_neighbours(tmp_path: Path):
    _write_graph(
        tmp_path,
        {
            "nodes": [
                {"id": "a", "source_file": "src/app.py"},
                {"id": "b", "source_file": "src/dep.py"},
                {"id": "c", "source_file": "src/unrelated.py"},
            ],
            "links": [{"source": "a", "target": "b"}],
        },
    )
    context = GraphifyAdapter().context(
        tmp_path, [{"file": "src/app.py", "line": 1, "function": "run"}]
    )
    assert [n["id"] for n in context.entities] == ["a", "b"]
    assert "1 seed nodes matched" in context.message


def test_graph_older_than_source_is_flagged(tmp_path: Path):
    import os, time

    graph = _write_graph(tmp_path, {"nodes": [], "links": []})
    old = time.time() - 1000
    os.utime(graph, (old, old))
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    context = GraphifyAdapter().context(tmp_path, [])
    assert context.available is True
    assert "older than" in context.message


@pytest.mark.parametrize("payload", ["{not json", '{"nodes": []}', '["list"]'])
def test_malformed_graph_json_is_reported_unavailable(tmp_path: Path, payload):
    _write_graph(tmp_path, payload)
    context = GraphifyAdapter().context(tmp_path, [])
    assert context.available is False
    assert context.entities == [] and context.relationships == []


def test_missing_graphify_executable_is_reported(tmp_path: Path, monkeypatch):
    error = GraphifyAdapter().build_graph(tmp_path)
    assert "not found" in error


def test_graphify_build_uses_documented_update_command_and_loads_graph(tmp_path: Path, monkeypatch):
    import repomedic

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        _write_graph(tmp_path, {"nodes": [{"id": "a", "source_file": "app.py"}], "links": []})
        return None

    monkeypatch.setattr(repomedic, "find_graphify", lambda: "graphify")
    monkeypatch.setattr(repomedic.subprocess, "run", fake_run)
    context = GraphifyAdapter().context(tmp_path, [{"file": "app.py", "line": 1, "function": "f"}])
    assert calls == [["graphify", "update", str(tmp_path)]]
    assert context.available is True and len(context.entities) == 1


def test_graphify_build_failure_is_not_masked(tmp_path: Path, monkeypatch):
    import subprocess as sp

    import repomedic

    def failing_run(command, **kwargs):
        raise sp.CalledProcessError(2, command, stderr="boom")

    monkeypatch.setattr(repomedic, "find_graphify", lambda: "graphify")
    monkeypatch.setattr(repomedic.subprocess, "run", failing_run)
    context = GraphifyAdapter().context(tmp_path, [])
    assert context.available is False
    assert "build failed" in context.message and "boom" in context.message


# --- REAL Graphify tests: these invoke the actual installed `graphify` CLI (0.9.93 venv) ---
import subprocess as _sp
import sys as _sys

import repomedic as _rm

_GRAPHIFY = Path(__file__).resolve().parent.parent / ".venv-graphify" / "Scripts" / "graphify.exe"
needs_graphify = pytest.mark.skipif(not _GRAPHIFY.is_file(), reason="real graphify not installed")

BUGGY_APP = '''\
def parse_price(text):
    return float(text.strip("$"))


def total(items):
    return sum(parse_price(i) for i in items)


def checkout(items):
    return round(total(items), 2)
'''


def _make_buggy_repo(root: Path) -> None:
    (root / "shop.py").write_text(BUGGY_APP, encoding="utf-8")
    (root / "helpers.py").write_text("def unrelated():\n    return 1\n", encoding="utf-8")


@pytest.mark.real_graphify
@needs_graphify
def test_real_graphify_build_and_consume(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("repomedic.find_graphify", lambda: str(_GRAPHIFY))
    _make_buggy_repo(tmp_path)
    frames = [{"file": str(tmp_path / "shop.py"), "line": 2, "function": "parse_price"}]
    context = GraphifyAdapter().context(tmp_path, frames)  # builds via real `graphify update`
    assert context.available is True, context.message
    assert (tmp_path / "graphify-out" / "graph.json").is_file()
    assert (tmp_path / "graphify-out" / "graph.html").is_file()
    labels = {e.get("label") for e in context.entities}
    assert "parse_price()" in labels
    assert "total()" in labels  # one-hop caller retrieved from the real graph
    assert any(r.get("relation") == "calls" for r in context.relationships)
    assert "function-level" in context.message
    assert "unrelated()" not in labels


@pytest.mark.real_graphify
@needs_graphify
def test_real_graphify_stale_graph_is_rebuilt(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("repomedic.find_graphify", lambda: str(_GRAPHIFY))
    _make_buggy_repo(tmp_path)
    adapter = GraphifyAdapter()
    adapter.context(tmp_path, [])
    (tmp_path / "shop.py").write_text(BUGGY_APP + "\n\ndef newly_added():\n    return parse_price('1')\n", encoding="utf-8")
    context = adapter.context(tmp_path, [{"file": "shop.py", "line": 1, "function": "newly_added"}])
    assert "newly_added()" in {e.get("label") for e in context.entities}


@pytest.mark.real_graphify
@needs_graphify
def test_real_graphify_failure_on_empty_repo_is_reported(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("repomedic.find_graphify", lambda: str(_GRAPHIFY))
    context = GraphifyAdapter().context(tmp_path, [])
    assert context.available is False
    assert "build failed" in context.message


def test_venv_and_graph_output_are_never_given_to_the_model(tmp_path: Path):
    for d in (".venv-graphify", "graphify-out"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "x.py").write_text("secret = 1", encoding="utf-8")
    (tmp_path / "app.py").write_text("ok = 1", encoding="utf-8")
    assert RepositoryInspector(tmp_path).files() == [tmp_path / "app.py"]


def test_absolute_traceback_paths_match_relative_graph_paths(tmp_path: Path):
    _write_graph(
        tmp_path,
        {
            "nodes": [
                {"id": "f", "label": "run()", "source_file": "src/app.py"},
                {"id": "g", "label": "other()", "source_file": "src/app.py"},
            ],
            "links": [],
        },
    )
    frames = [{"file": str(tmp_path / "src" / "app.py"), "line": 3, "function": "run"}]
    context = GraphifyAdapter().context(tmp_path, frames)
    assert [n["id"] for n in context.entities] == ["f"]
    assert "function-level" in context.message


def test_graph_context_is_rendered_compactly_with_labels():
    from repomedic import GraphContext, format_graph_context

    graph = GraphContext(
        True, "ok",
        [{"id": "a", "label": "f()", "source_file": "m.py", "source_location": "L1"},
         {"id": "b", "label": "g()", "source_file": "m.py", "source_location": "L5"}],
        [{"source": "a", "target": "b", "relation": "calls", "confidence": "EXTRACTED"}],
    )
    text = format_graph_context(graph)
    assert "f() (m.py:L1)" in text
    assert "f() --calls--> g() [EXTRACTED]" in text
    assert "_origin" not in text


def test_ollama_request_sets_context_window(monkeypatch):
    import io

    import repomedic

    seen = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout):
        seen["body"] = json.loads(request.data)
        return Response(b'{"response": "{}", "prompt_eval_count": 5, "eval_count": 2}')

    monkeypatch.setattr(repomedic.urllib.request, "urlopen", fake_urlopen)
    OllamaClient("qwen2.5:3b", num_ctx=8192).generate("hi")
    assert seen["body"]["options"]["num_ctx"] == 8192


def test_analyze_enforces_human_review_and_never_applies(tmp_path: Path, monkeypatch):
    import repomedic

    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(repomedic.OllamaClient, "available", lambda self: True)
    monkeypatch.setattr(
        repomedic.OllamaClient,
        "generate",
        lambda self, prompt: InferenceResult('{"patch": {"review_required": false}}', 3, 2),
    )
    result = repomedic.analyze(tmp_path, "boom", "qwen2.5:3b")
    assert result["patch"]["review_required"] is True
    assert result["patch"]["applied"] is False
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "x = 1\n"
