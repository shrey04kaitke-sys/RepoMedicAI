"""Retrieval, diagnosis pipeline, Ollama error handling, graph status.

Labels: [real graphify] [real ollama] invoke the real tools; [stored artifact] reads a genuine
Graphify output file saved in demo/; [mock model] uses a fake Ollama client.
"""
import io
import json
import shutil
import urllib.error
from pathlib import Path

import pytest

import repomedic as rm
from conftest import PROJECT, installed_models, needs_graphify, needs_ollama

DEMO_GRAPH = PROJECT / "demo" / "graphify-out-demo" / "graph.json"  # genuine `graphify update` output
DEMO_FAILURE = PROJECT / "demo" / "failure.txt"  # genuine pytest output

PRICING = 'def parse_price(text):\n    return float(text.strip("$"))\n\n\ndef line_total(price_text, quantity):\n    return parse_price(price_text) * quantity\n'
CART = "from pricing import line_total\n\n\ndef cart_total(lines):\n    return round(sum(line_total(p, q) for p, q in lines), 2)\n"
TRACEBACK = (
    'Traceback (most recent call last):\n'
    '  File "{root}/cart.py", line 5, in cart_total\n    return 1\n'
    '  File "{root}/pricing.py", line 6, in line_total\n    return 1\n'
    '  File "{root}/pricing.py", line 2, in parse_price\n    return 1\n'
    "ValueError: could not convert string to float: '1,299.00'\n"
)


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    (tmp_path / "pricing.py").write_text(PRICING, encoding="utf-8", newline="\n")
    (tmp_path / "cart.py").write_text(CART, encoding="utf-8", newline="\n")
    for name in ("inventory", "shipping", "users"):
        (tmp_path / f"{name}.py").write_text(f"def {name}_task(records):\n    return len(records)\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_cart.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
        "from cart import cart_total\n\n\ndef test_thousands():\n    assert cart_total([('$1,299.00', 1)]) == 1299.0\n",
        encoding="utf-8",
    )
    return tmp_path


def traceback_for(root: Path) -> str:
    return TRACEBACK.format(root=str(root).replace("\\", "/"))


class FakeClient:
    """[mock model] Stands in for Ollama."""

    base_url = "fake://ollama"

    def __init__(self, response, up=True):
        self.response, self.up, self.prompt = response, up, None

    def available(self):
        return self.up

    def generate(self, prompt):
        self.prompt = prompt
        text = self.response if isinstance(self.response, str) else json.dumps(self.response)
        return rm.InferenceResult(text, 111, 22)


GOOD = {
    "hypotheses": [{"cause": "comma not stripped", "evidence": "ValueError on '1,299.00'", "confidence": 0.8, "status": "verified"}],
    "relevant_functions": ["parse_price"],
    "patch": {
        "explanation": "strip commas",
        "edits": [{"file": "pricing.py", "old": 'text.strip("$")', "new": 'text.strip("$").replace(",", "")'}],
    },
}


# ---------- traceback parsing ----------

def test_parser_handles_real_pytest_output():
    frames = rm.TracebackParser.parse(DEMO_FAILURE.read_text(encoding="utf-8"))
    pairs = {(Path(f["file"]).name, f["line"]) for f in frames}
    assert ("pricing.py", 3) in pairs and ("cart.py", 5) in pairs and ("pricing.py", 7) in pairs


def test_parser_handles_pytest_short_format_with_functions():
    frames = rm.TracebackParser.parse("src/a.py:12: in compute\n    x()\nsrc/b.py:4: ValueError\n")
    assert frames == [
        {"file": "src/a.py", "line": 12, "function": "compute"},
        {"file": "src/b.py", "line": 4, "function": ""},
    ]


# ---------- retrieval ----------

def test_keyword_baseline_ranks_relevant_files_first(shop: Path):
    files = rm.keyword_files(rm.RepositoryInspector(shop), "parse_price fails on 1,299.00 in pricing")
    assert files[0] == "pricing.py"
    assert "inventory.py" not in files


def test_graph_strategy_falls_back_honestly_when_no_graph(shop: Path):
    result = rm.retrieve(shop, traceback_for(shop), strategy="graph")
    assert result.strategy_requested == "graph" and result.strategy_used == "keyword"
    assert "fell back to keyword" in result.note
    assert result.graph.available is False


def test_unknown_strategy_is_rejected(shop: Path):
    with pytest.raises(ValueError, match="Unknown retrieval strategy"):
        rm.retrieve(shop, "x", strategy="magic")


def test_all_strategy_sends_every_file(shop: Path):
    result = rm.retrieve(shop, "boom", strategy="all")
    assert set(result.files) >= {"pricing.py", "cart.py", "inventory.py", "tests/test_cart.py"}


def test_source_budget_is_enforced_and_marked(tmp_path: Path):
    (tmp_path / "big.py").write_text("x = 1\n" * 5000, encoding="utf-8")
    text, included = rm.RepositoryInspector(tmp_path).source_bundle(limit=500)
    assert included == ["big.py"] and len(text) < 700 and "[...truncated...]" in text


@needs_graphify
@pytest.mark.real_graphify
def test_real_graph_retrieval_selects_only_related_files(shop: Path):
    """[real graphify] Builds a real graph for the repo and retrieves from it."""
    result = rm.retrieve(shop, traceback_for(shop), bug="comma in price", strategy="graph")
    assert result.strategy_used == "graph", result.note
    assert result.graph.available and (shop / "graphify-out" / "graph.json").is_file()
    assert {"pricing.py", "cart.py"} <= set(result.files)
    assert not {"inventory.py", "shipping.py", "users.py"} & set(result.files)
    labels = {e.get("label") for e in result.graph.entities}
    assert {"parse_price()", "line_total()", "cart_total()"} <= labels
    assert any(r.get("relation") == "calls" for r in result.graph.relationships)


@needs_graphify
@pytest.mark.real_graphify
def test_real_graph_seeds_from_bug_text_without_a_traceback(shop: Path):
    """[real graphify] No traceback: functions named in the bug report seed retrieval."""
    result = rm.retrieve(shop, "", bug="parse_price crashes on thousands separators", strategy="graph")
    assert result.strategy_used == "graph"
    assert "name-mentioned" in result.graph.message
    assert "pricing.py" in result.files


def test_stored_real_graph_seeds_from_bug_text(tmp_path: Path):
    """[stored artifact] Same behaviour against a saved genuine graph.json."""
    out = tmp_path / "graphify-out"
    out.mkdir()
    shutil.copy2(DEMO_GRAPH, out / "graph.json")
    context = rm.GraphifyAdapter().context(tmp_path, [], hints="parse_price fails with a comma")
    assert context.available and "name-mentioned" in context.message
    assert "parse_price()" in {e.get("label") for e in context.entities}


# ---------- graph status ----------

def test_status_reports_facts_from_stored_real_graph(tmp_path: Path):
    """[stored artifact]"""
    status = rm.GraphifyAdapter(graph_path=DEMO_GRAPH).status(tmp_path)
    assert status["exists"] and status["nodes"] > 50 and status["edges"] > 50
    assert "calls" in status["relations"] and status["communities"] >= 1
    assert status["graph_html"] and status["report"]


def test_status_without_graph_gives_instructions(tmp_path: Path):
    status = rm.GraphifyAdapter().status(tmp_path)
    assert status["exists"] is False and "graphify update" in status["message"]


def test_status_flags_invalid_graph(tmp_path: Path):
    bad = tmp_path / "graph.json"
    bad.write_text("{oops", encoding="utf-8")
    assert "invalid" in rm.GraphifyAdapter(graph_path=bad).status(tmp_path)["error"]


def test_cli_graph_only_prints_status(tmp_path: Path, capsys):
    out = tmp_path / "graphify-out"
    out.mkdir()
    shutil.copy2(DEMO_GRAPH, out / "graph.json")
    assert rm.main([str(tmp_path), "--graph-only"]) == 0
    assert json.loads(capsys.readouterr().out)["nodes"] > 50


def test_cli_requires_a_bug_or_failure(tmp_path: Path, capsys):
    assert rm.main([str(tmp_path)]) == 1
    assert "bug description" in capsys.readouterr().err


# ---------- diagnose with a mock model ----------

def test_diagnose_builds_reviewable_diff_from_edits(shop: Path):
    """[mock model] Model output is untrusted; RepoMedic derives the diff itself."""
    client = FakeClient(GOOD)
    result = rm.diagnose(shop, traceback_for(shop), "m", bug="thousands separator", client=client)
    patch = result["patch"]
    assert patch["diff_source"] == "edits" and patch["unified_diff"].startswith("--- a/pricing.py")
    assert patch["review_required"] is True and patch["applied"] is False and patch["validated"] is False
    assert result["hypotheses"][0]["status"] == "plausible"  # "verified" is downgraded
    assert result["timing"]["retrieval_s"] >= 0 and result["token_usage"]["prompt_tokens"] == 111
    assert "thousands separator" in client.prompt and "BUG REPORT" in client.prompt
    assert (shop / "pricing.py").read_text(encoding="utf-8") == PRICING


def test_diagnose_handles_malformed_model_json(shop: Path):
    result = rm.diagnose(shop, traceback_for(shop), "m", client=FakeClient("this is not json"))
    assert "malformed JSON" in result["error"] and result["patch"]["unified_diff"] == ""


def test_diagnose_rejects_hallucinated_edits(shop: Path):
    bad = {"hypotheses": [], "patch": {"edits": [{"file": "pricing.py", "old": "does not exist", "new": "x"}]}}
    result = rm.diagnose(shop, traceback_for(shop), "m", client=FakeClient(bad))
    assert result["patch"]["unified_diff"] == ""
    assert "matched 0 times" in result["patch"]["errors"][0]


def test_diagnose_falls_back_to_a_model_diff_only_if_it_applies(shop: Path):
    good_diff = rm.build_diff_from_edits(shop, GOOD["patch"]["edits"])
    ok = rm.diagnose(shop, traceback_for(shop), "m", client=FakeClient({"patch": {"unified_diff": good_diff}}))
    assert ok["patch"]["diff_source"] == "model_diff"
    bad = rm.diagnose(shop, traceback_for(shop), "m", client=FakeClient({"patch": {"unified_diff": "@@ -1 +1 @@\n-a\n+b\n"}}))
    assert bad["patch"]["unified_diff"] == "" and "model diff rejected" in bad["patch"]["errors"][0]


def test_diagnose_sanitises_odd_model_types(shop: Path):
    weird = {"hypotheses": [5, None, "just a string", {"cause": 3, "confidence": True, "status": "bogus"}],
             "relevant_functions": "nope", "patch": ["x"]}
    result = rm.diagnose(shop, traceback_for(shop), "m", client=FakeClient(weird))
    assert [h["status"] for h in result["hypotheses"]] == ["unverified", "unverified"]
    assert result["hypotheses"][1]["confidence"] is None and result["relevant_functions"] == []


def test_diagnose_requires_input_and_reachable_ollama(shop: Path):
    with pytest.raises(ValueError, match="bug description"):
        rm.diagnose(shop, "", "m", client=FakeClient({}))
    with pytest.raises(rm.OllamaUnavailableError, match="ollama serve"):
        rm.diagnose(shop, "boom", "m", client=FakeClient({}, up=False))


@needs_graphify
@pytest.mark.real_graphify
def test_real_graph_feeds_the_prompt_sent_to_the_model(shop: Path):
    """[real graphify][mock model] Real graph context ends up in the prompt; unrelated code does not."""
    client = FakeClient(GOOD)
    result = rm.diagnose(shop, traceback_for(shop), "m", bug="comma bug", client=client)
    assert result["graphify"]["available"] and result["strategy"]["used"] == "graph"
    assert "cart_total() --calls--> line_total()" in client.prompt
    assert "inventory_task" not in client.prompt
    assert result["patch"]["diff_source"] == "edits"


# ---------- Ollama client errors ----------

def _patch_urlopen(monkeypatch, generate_error):
    def fake(request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        if url.endswith("/api/tags"):
            return io.BytesIO(b'{"models": [{"name": "qwen2.5:3b"}]}')
        raise generate_error

    monkeypatch.setattr(rm.urllib.request, "urlopen", fake)


def test_missing_model_gives_pull_instructions(monkeypatch):
    err = urllib.error.HTTPError("http://x/api/generate", 404, "Not Found", {}, None)
    _patch_urlopen(monkeypatch, err)
    with pytest.raises(rm.OllamaUnavailableError, match=r"ollama pull nope.*qwen2\.5:3b|qwen2\.5:3b.*ollama pull nope"):
        rm.OllamaClient("nope").generate("hi")


def test_inference_timeout_is_reported(monkeypatch):
    _patch_urlopen(monkeypatch, TimeoutError("timed out"))
    with pytest.raises(RuntimeError, match="timed out after 5s"):
        rm.OllamaClient("m", timeout=5).generate("hi")


def test_server_error_and_bad_json_are_reported(monkeypatch):
    _patch_urlopen(monkeypatch, urllib.error.HTTPError("http://x", 500, "boom", {}, None))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        rm.OllamaClient("m").generate("hi")


# ---------- real Ollama ----------

@needs_ollama
@pytest.mark.real_ollama
def test_real_ollama_returns_token_counters():
    """[real ollama]"""
    model = "qwen2.5:3b"
    if model not in installed_models():
        pytest.skip(f"{model} not installed")
    result = rm.OllamaClient(model).generate('Reply with exactly this JSON: {"ok": true}')
    assert isinstance(result.prompt_tokens, int) and isinstance(result.output_tokens, int)
    assert json.loads(result.text)  # JSON mode returns parseable JSON


@needs_ollama
@needs_graphify
@pytest.mark.real_ollama
@pytest.mark.real_graphify
def test_real_end_to_end_pipeline_runs_and_never_touches_the_repo(shop: Path):
    """[real graphify][real ollama] Full pipeline. Asserts structure and safety, not model accuracy."""
    model = "qwen2.5:3b"
    if model not in installed_models():
        pytest.skip(f"{model} not installed")
    before = {p: p.read_bytes() for p in shop.rglob("*.py")}
    result = rm.diagnose(shop, traceback_for(shop), model, bug="cart total crashes on '$1,299.00'")
    assert result["graphify"]["available"] and result["strategy"]["used"] == "graph"
    assert {"pricing.py", "cart.py"} <= set(result["retrieval"]["files"])
    assert isinstance(result["token_usage"]["prompt_tokens"], int)
    assert result["patch"]["applied"] is False and result["patch"]["review_required"] is True
    assert result.get("error") or result["hypotheses"]
    assert all(p.read_bytes() == data for p, data in before.items())


# ---------- num_predict cap and HTTP error body [mock server] ----------

def _capture_generate_payload(monkeypatch, **client_kwargs):
    seen = {}

    def fake(request, timeout=None):
        seen["body"] = json.loads(request.data)
        seen["timeout"] = timeout
        return io.BytesIO(b'{"response": "{}", "prompt_eval_count": 3, "eval_count": 2}')

    monkeypatch.setattr(rm.urllib.request, "urlopen", fake)
    rm.OllamaClient("m", **client_kwargs).generate("hi")
    return seen


def test_generate_caps_output_length_by_default(monkeypatch):
    seen = _capture_generate_payload(monkeypatch)
    options = seen["body"]["options"]
    assert options["num_predict"] == 2048
    assert options["num_ctx"] == 8192 and options["temperature"] == 0


def test_generate_num_predict_is_configurable(monkeypatch):
    assert _capture_generate_payload(monkeypatch, num_predict=64)["body"]["options"]["num_predict"] == 64


def test_http_500_error_includes_the_response_body(monkeypatch):
    body = io.BytesIO(b'{"error": "model runner has unexpectedly stopped"}')
    err = urllib.error.HTTPError("http://x/api/generate", 500, "Internal Server Error", {}, body)
    _patch_urlopen(monkeypatch, err)
    with pytest.raises(RuntimeError) as info:
        rm.OllamaClient("m").generate("hi")
    message = str(info.value)
    assert "HTTP 500" in message and "model runner has unexpectedly stopped" in message


def test_http_error_body_is_truncated_and_tolerates_unreadable_bodies(monkeypatch):
    big = io.BytesIO(b"x" * 5000)
    _patch_urlopen(monkeypatch, urllib.error.HTTPError("http://x", 500, "boom", {}, big))
    with pytest.raises(RuntimeError) as info:
        rm.OllamaClient("m").generate("hi")
    assert len(str(info.value)) < 700

    class Unreadable(io.BytesIO):
        def read(self, *a):
            raise OSError("closed")

    _patch_urlopen(monkeypatch, urllib.error.HTTPError("http://x", 500, "boom", {}, Unreadable()))
    with pytest.raises(RuntimeError, match="HTTP 500: boom"):
        rm.OllamaClient("m").generate("hi")
