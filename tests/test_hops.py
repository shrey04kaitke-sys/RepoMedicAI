"""2-hop graph retrieval (strategy 'graph2') versus the 1-hop control ('graph').

[fixture graph] tests use a small hand-written graph.json in Graphify's schema to test traversal
logic precisely; they are NOT evidence of Graphify integration. [real graphify] tests build real
graphs with the installed CLI and check retrieval of the real benchmark bugs.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

import repomedic as rm
from conftest import PROJECT, needs_graphify

sys.path.insert(0, str(PROJECT / "benchmarks"))
from cases import CASES, build_case  # noqa: E402

FRAMES = [{"file": "tests/test_a.py", "line": 3, "function": "test_x"}]


def node(identifier, label, source_file, **extra):
    return {"id": identifier, "label": label, "source_file": source_file, "source_location": "L1", **extra}


def edge(source, target, relation="calls"):
    return {"source": source, "target": target, "relation": relation, "confidence": "EXTRACTED"}


def chain_graph():
    """test_x -> a ; a -> b, a -> c ; b -> c ; c -> d ; c -> a (cycle). Plus hubs and an excluded node."""
    nodes = [
        node("t", "test_x()", "tests/test_a.py"), node("tf", "test_a.py", "tests/test_a.py"),
        node("a", "a()", "a.py"), node("af", "a.py", "a.py"), node("sib", "sibling()", "a.py"),
        node("b", "b()", "b.py"), node("c", "c()", "c.py"), node("d", "d()", "d.py"),
        node("venv", "leak()", ".venv-graphify/lib/leak.py"), node("sys", "sys", ""),
    ]
    links = [
        edge("t", "a"), edge("a", "b"), edge("a", "c"), edge("b", "c"), edge("c", "d"), edge("c", "a"),
        edge("a", "venv"), edge("tf", "t", "contains"), edge("af", "a", "contains"), edge("af", "sib", "contains"),
        edge("a", "sys", "imports"),
    ]
    return {"directed": False, "nodes": nodes, "links": links}


def write_graph(directory: Path, payload) -> Path:
    out = directory / "graphify-out"
    out.mkdir(exist_ok=True)
    path = out / "graph.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


def ids(context) -> list[str]:
    return [e["id"] for e in context.entities]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    write_graph(tmp_path, chain_graph())
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(tmp_path / "a.py", (old, old))  # source older than the graph: graph is fresh
    return tmp_path


# ---------- traversal depth ----------

def test_depth_grows_one_call_level_per_hop(repo: Path):
    h1 = rm.GraphifyAdapter().context(repo, FRAMES, hops=1)
    h2 = rm.GraphifyAdapter().context(repo, FRAMES, hops=2)
    h3 = rm.GraphifyAdapter().context(repo, FRAMES, hops=3)
    assert set(ids(h1)) == {"t", "tf", "a"}
    assert set(ids(h2)) == {"t", "tf", "a", "b", "c"}  # callees of a, one level deeper
    assert set(ids(h3)) == {"t", "tf", "a", "b", "c", "d"}
    assert "hops=2" in h2.message and "+2 nodes" in h2.message


def test_default_and_hops_1_are_identical_to_the_control(repo: Path):
    default = rm.GraphifyAdapter().context(repo, FRAMES)
    explicit = rm.GraphifyAdapter().context(repo, FRAMES, hops=1)
    assert default.entities == explicit.entities and default.relationships == explicit.relationships
    assert "hops=" not in default.message  # no expansion text: the control path is unchanged


def test_expanded_nodes_record_their_hop_distance(repo: Path):
    by_id = {e["id"]: e for e in rm.GraphifyAdapter().context(repo, FRAMES, hops=3).entities}
    assert by_id["b"]["_hop"] == 2 and by_id["c"]["_hop"] == 2 and by_id["d"]["_hop"] == 3
    assert "_hop" not in by_id["a"]


# ---------- cycles, duplicates, hubs ----------

def test_cycles_and_diamonds_never_duplicate_nodes_or_edges(repo: Path):
    context = rm.GraphifyAdapter().context(repo, FRAMES, hops=4)
    assert len(ids(context)) == len(set(ids(context)))
    keys = [(r["source"], r["target"], r["relation"]) for r in context.relationships]
    assert len(keys) == len(set(keys))
    assert ("c", "a", "calls") in keys  # the cycle edge is kept once; it did not loop forever


def test_only_call_flow_is_followed_beyond_hop_one(repo: Path):
    context = rm.GraphifyAdapter().context(repo, FRAMES, hops=4)
    assert "sib" not in ids(context)  # sibling reachable only via a 'contains' hub
    assert "sys" not in ids(context)  # stdlib hub reachable only via 'imports'


def test_callers_are_not_followed_backwards_beyond_hop_one(tmp_path: Path):
    graph = chain_graph()
    graph["nodes"].append(node("up", "upstream()", "up.py"))
    graph["links"].append(edge("up", "b"))  # upstream calls b: a caller of a hop-2 node
    write_graph(tmp_path, graph)
    assert "up" not in ids(rm.GraphifyAdapter().context(tmp_path, FRAMES, hops=4))


# ---------- exclusions and budgets ----------

def test_excluded_directories_are_never_expanded_into(repo: Path):
    context = rm.GraphifyAdapter().context(repo, FRAMES, hops=4)
    assert "venv" not in ids(context)
    assert not any(".venv-graphify" in str(e.get("source_file")) for e in context.entities)


@pytest.mark.parametrize("path", [".git/x.py", "graphify-out/x.py", "pkg/.env", "pkg/.env.local", ".repomedic-backup/x.py"])
def test_node_exclusion_rules(path):
    assert rm._node_is_excluded({"source_file": path}) is True


def test_normal_nodes_are_not_excluded():
    assert rm._node_is_excluded({"source_file": "src/app.py"}) is False
    assert rm._node_is_excluded({"source_file": ""}) is False


def test_node_budget_bounds_expansion(repo: Path, monkeypatch):
    monkeypatch.setattr(rm, "MAX_GRAPH_NODES", 4)  # 3 nodes already retrieved at hop 1
    context = rm.GraphifyAdapter().context(repo, FRAMES, hops=4)
    assert len(ids(context)) <= 4


def test_relationship_budget_bounds_expansion(repo: Path, monkeypatch):
    base = len(rm.GraphifyAdapter().context(repo, FRAMES, hops=1).relationships)
    monkeypatch.setattr(rm, "MAX_EXPANDED_RELATIONSHIPS", 1)
    assert len(rm.GraphifyAdapter().context(repo, FRAMES, hops=4).relationships) == base + 1


def test_context_character_budget_still_applies_to_graph2(tmp_path: Path):
    for name, body in {"a.py": "def a():\n    return b()\n", "b.py": "def b():\n    return 1\n" * 200}.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_x():\n    assert a() == 2\n", encoding="utf-8")
    graph = {"nodes": [node("t", "test_x()", "tests/test_a.py"), node("a", "a()", "a.py"), node("b", "b()", "b.py")],
             "links": [edge("t", "a"), edge("a", "b")]}
    write_graph(tmp_path, graph)
    trace = 'File "tests/test_a.py", line 2, in test_x\n'
    small = rm.retrieve(tmp_path, trace, strategy="graph2", budget=300)
    large = rm.retrieve(tmp_path, trace, strategy="graph2", budget=24_000)
    assert "b.py" in small.files and "[...truncated...]" in small.source
    assert len(small.source) < len(large.source)


# ---------- failure cases and stale graphs ----------

@pytest.mark.parametrize("hops", [0, -1, 5, 100, "2", 2.0, True, None])
def test_invalid_hops_are_rejected(repo: Path, hops):
    with pytest.raises(ValueError, match="hops must be"):
        rm.GraphifyAdapter().context(repo, FRAMES, hops=hops)


@pytest.mark.parametrize("payload", ["{not json", '{"nodes": []}', '["x"]'])
def test_malformed_graphs_fail_cleanly_at_hops_2(tmp_path: Path, payload):
    write_graph(tmp_path, payload)
    context = rm.GraphifyAdapter().context(tmp_path, FRAMES, hops=2)
    assert context.available is False and context.entities == []


def test_missing_graph_falls_back_to_keyword_for_graph2(tmp_path: Path):
    (tmp_path / "pricing.py").write_text("def parse_price(t):\n    return float(t)\n", encoding="utf-8")
    result = rm.retrieve(tmp_path, "parse_price crashes", strategy="graph2")
    assert result.strategy_requested == "graph2" and result.strategy_used == "keyword"
    assert "fell back to keyword" in result.note and "pricing.py" in result.files


def test_stale_graph_is_flagged_and_still_expands(repo: Path):
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")  # newer than the graph
    future = time.time() + 60
    os.utime(repo / "a.py", (future, future))
    context = rm.GraphifyAdapter().context(repo, FRAMES, hops=2)  # no graphify available (autouse stub)
    assert context.available and context.stale and "older than" in context.message
    assert "b" in ids(context)


def test_graph_nodes_without_the_traced_file_yield_no_expansion(repo: Path):
    context = rm.GraphifyAdapter().context(
        repo, [{"file": "nowhere.py", "line": 1, "function": "nothing"}], hops=3)
    assert context.available and context.entities == []


def test_unknown_strategy_and_hops_override(repo: Path):
    with pytest.raises(ValueError, match="Unknown retrieval strategy"):
        rm.retrieve(repo, "x", strategy="graph3")
    trace = 'File "tests/test_a.py", line 3, in test_x\n'
    assert set(rm.retrieve(repo, trace, strategy="graph").graph.entities and
               [e["id"] for e in rm.retrieve(repo, trace, strategy="graph").graph.entities]) == {"t", "tf", "a"}
    deeper = rm.retrieve(repo, trace, strategy="graph", hops=3)  # configurable override
    assert "d" in [e["id"] for e in deeper.graph.entities]


# ---------- real Graphify on the real benchmark bugs ----------

HOPS_NEEDED = {  # verified from the real graphs: call hops from the failing test to the bug function
    "price_thousands_separator": 0, "moving_average_window": 1, "free_shipping_boundary": 2,
    "mutable_default_argument": 2, "shallow_config_merge": 2, "pagination_off_by_one": 3,
}


@needs_graphify
@pytest.mark.real_graphify
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_real_graph_bug_file_retrieval_by_strategy(case, tmp_path: Path):
    """[real graphify] The control and graph2 behave as the hop distance predicts; the control is unchanged."""
    build_case(case, tmp_path)
    assert rm.GraphifyAdapter().build_graph(tmp_path) is None
    trace = rm.capture_failure(tmp_path)["output"]
    needed = HOPS_NEEDED[case["name"]]

    def found(strategy, **kw):
        return case["bug_file"] in rm.retrieve(tmp_path, trace, case["bug"], strategy, **kw).files

    assert found("graph") == (needed <= 1), "the 1-hop control changed behaviour"
    assert found("graph2") == (needed <= 2)
    assert found("graph", hops=3) == (needed <= 3)
    graph2 = rm.retrieve(tmp_path, trace, case["bug"], "graph2")
    assert graph2.strategy_used == "graph2"
    assert len(graph2.files) <= rm.MAX_RETRIEVED_FILES and len(graph2.graph.entities) <= rm.MAX_GRAPH_NODES
    assert not any(".venv" in e.get("source_file", "") or "graphify-out" in e.get("source_file", "")
                   for e in graph2.graph.entities)
