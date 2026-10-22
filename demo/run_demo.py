"""Reproducible RepoMedic demo: real bug, real Graphify graph, real Ollama, baseline vs graph."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
RUNS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
sys.path.insert(0, str(PROJECT))
import repomedic as rm  # noqa: E402

GRAPHIFY = PROJECT / ".venv-graphify" / "Scripts" / "graphify.exe"
rm.find_graphify = lambda: str(GRAPHIFY)  # use the real isolated install

work = Path(tempfile.mkdtemp(prefix="repomedic-demo-"))
repo = work / "shopapp"
(repo / "tests").mkdir(parents=True)

(repo / "pricing.py").write_text('''def parse_price(text):
    """Convert a price string such as '$12.50' into a float."""
    return float(text.strip("$"))


def line_total(price_text, quantity):
    return parse_price(price_text) * quantity
''', encoding="utf-8")
(repo / "cart.py").write_text('''from pricing import line_total


def cart_total(lines):
    return round(sum(line_total(price, qty) for price, qty in lines), 2)
''', encoding="utf-8")
# Unrelated modules (realistic but independent of the bug).
for name in ["inventory", "shipping", "users", "reports", "notifications", "audit"]:
    body = [f'"""{name} helpers."""', ""]
    for i in range(1, 9):
        body += [
            f"def {name}_task_{i}(records, limit={i * 10}):",
            f'    """Process {name} records (variant {i})."""',
            "    cleaned = [r for r in records if r is not None]",
            "    cleaned.sort(key=lambda r: str(r))",
            "    if len(cleaned) > limit:",
            "        cleaned = cleaned[:limit]",
            f"    return {{'module': '{name}', 'variant': {i}, 'count': len(cleaned)}}",
            "",
            "",
        ]
    (repo / f"{name}.py").write_text("\n".join(body), encoding="utf-8")
(repo / "tests" / "test_cart.py").write_text('''import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from cart import cart_total


def test_cart_total_with_thousands_separator():
    assert cart_total([("$1,299.00", 1), ("$5.00", 2)]) == 1309.0
''', encoding="utf-8")

failing = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "--tb=long"], cwd=repo,
                         capture_output=True, text=True)
failure = failing.stdout
(OUT / "failure.txt").write_text(failure, encoding="utf-8")
print("== 1. ORIGINAL FAILURE (pytest exit", failing.returncode, ") ==")
print(failure[-1500:])

# pytest --tb=long prints '/path/pricing.py:3: ValueError'; add python-style frames the parser understands
frames_text = "\n".join(
    f'  File "{m[0]}", line {m[1]}, in {m[2]}'
    for m in __import__("re").findall(r"^(\S+\.py):(\d+): in (\S+)|^", failure, flags=__import__("re").M) if m[0]
)

# Build the failure text with python-traceback style frames from a direct run for reliable parsing.
direct = subprocess.run([sys.executable, "-c",
    "import sys; sys.path.insert(0, 'tests'); sys.path.insert(0, '.');"
    "from cart import cart_total; cart_total([('$1,299.00', 1)])"],
    cwd=repo, capture_output=True, text=True)
traceback_text = direct.stderr
(OUT / "traceback.txt").write_text(traceback_text, encoding="utf-8")
print("== direct traceback ==")
print(traceback_text)
frames = rm.TracebackParser.parse(traceback_text)
print("frames:", frames)

adapter = rm.GraphifyAdapter()
graph = adapter.context(repo, frames)
print("== 2. GRAPHIFY CONTEXT ==")
print(graph.message)
print("graph.json:", graph.graph_json, "| graph.html:", graph.graph_html)
print("entities:", [(e.get("label"), e.get("source_file"), e.get("source_location")) for e in graph.entities])
ids = {e["id"]: e.get("label") for e in graph.entities}
print("relationships:", [(ids.get(r["source"], r["source"]), r["relation"], ids.get(r["target"], r["target"]),
                          r.get("confidence")) for r in graph.relationships])
(OUT / "graphify-out-demo").mkdir(exist_ok=True)
for art in ("graph.json", "graph.html", "GRAPH_REPORT.md"):
    shutil.copy2(repo / "graphify-out" / art, OUT / "graphify-out-demo" / art)

inspector = rm.RepositoryInspector(repo)
client = rm.OllamaClient("qwen2.5:3b")
assert client.available(), "Ollama not responding"
no_graph = rm.GraphContext(False, "Graphify not used (baseline).", [], [])
focus = {str(e["source_file"]).replace("\\", "/") for e in graph.entities if e.get("source_file")}
variants = {
    "baseline_all_files": (no_graph, inspector.source_context()),
    "graph_assisted": (graph, inspector.source_context(only=focus)),
}
results = {}
for name, (g, source) in variants.items():
    prompt = rm.build_prompt(traceback_text, source, frames, g)
    (OUT / f"prompt_{name}.txt").write_text(prompt, encoding="utf-8")
    runs = []
    for i in range(RUNS):
        res = client.generate(prompt)
        record = {"prompt_tokens": res.prompt_tokens, "output_tokens": res.output_tokens,
                  "prompt_chars": len(prompt), "source_chars": len(source)}
        try:
            out = rm.parse_model_output(res.text)
            diff = out.get("patch", {}).get("unified_diff", "") if isinstance(out.get("patch"), dict) else ""
            record["hypotheses"] = out.get("hypotheses")
            record["diff"] = diff
            try:
                v = rm.validate_approved_patch(repo, diff, [sys.executable, "-m", "pytest", "-q"])
                record["validation"] = {"passed": v["passed"], "returncode": v.get("returncode"),
                                        "changed": v["changed_files"]}
            except Exception as exc:  # noqa: BLE001 - recorded, not hidden
                record["validation"] = {"error": f"{type(exc).__name__}: {exc}"}
        except ValueError as exc:
            record["parse_error"] = str(exc)
        runs.append(record)
        print(name, i, {k: record.get(k) for k in ("prompt_tokens", "output_tokens", "validation", "parse_error")})
    results[name] = runs
(OUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print("source untouched:", (repo / "pricing.py").read_text(encoding="utf-8").count('strip("$")') == 1)
print("work dir:", work)
