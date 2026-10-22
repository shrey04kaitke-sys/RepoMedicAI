"""Benchmark baseline vs graph-assisted retrieval with a real local model.

Usage (from the project root):
    python benchmarks/run_benchmark.py --sanity-only            # no model; checks the cases themselves
    python benchmarks/run_benchmark.py --models qwen2.5:3b --trials 2

For every case x model x strategy x trial it records retrieval, token counts (Ollama's own
counters), latency, a heuristic diagnosis check, and whether the proposed patch passes the
repository's real tests in an isolated copy. Nothing is estimated or invented.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import repomedic as rm  # noqa: E402
from cases import CASES, build_case  # noqa: E402


def sanity_check(case: dict, repo: Path) -> dict:
    """The case must fail before the reference fix and pass after it, otherwise it is invalid."""
    before = rm.capture_failure(repo)
    if before["passed"]:
        raise SystemExit(f"[{case['name']}] invalid case: tests already pass")
    diff = rm.build_diff_from_edits(repo, case["reference_edits"])
    after = rm.validate_approved_patch(repo, diff)
    if after["passed"] is not True:
        raise SystemExit(f"[{case['name']}] invalid case: reference fix does not pass\n{after['stdout']}")
    return {"failing_output": before["output"], "reference_diff": diff}


def score_retrieval(case: dict, files: list[str]) -> dict:
    relevant = set(case["relevant_files"]) | {f for f in case["files"] if f.startswith("tests/")}
    hits = len(relevant & set(files))
    return {
        "bug_file_retrieved": case["bug_file"] in files,
        "relevant_recall": hits / len(relevant),
        "precision": hits / len(files) if files else 0.0,
        "files": files,
    }


def score_diagnosis(case: dict, result: dict) -> dict:
    text = " ".join(
        [h.get("cause", "") + " " + h.get("evidence", "") for h in result.get("hypotheses", [])]
        + result.get("relevant_functions", [])
        + [result["patch"].get("explanation", "")]
    ).lower()
    located = case["bug_function"].lower() in text or case["bug_file"].lower() in text
    cause = any(keyword.lower() in text for keyword in case["diagnosis_keywords"])
    return {"located_bug": located, "root_cause_keyword": cause, "diagnosis_heuristic_ok": located and cause}


def run_one(case, repo, trace, model, strategy, client, validations) -> dict:
    record: dict = {"case": case["name"], "model": model, "strategy": strategy}
    try:
        retrieval = rm.retrieve(repo, trace, case["bug"], strategy)
        result = rm.diagnose(repo, trace, model, case["bug"], strategy, client=client, retrieval=retrieval)
    except (RuntimeError, ValueError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record
    record.update(
        strategy_used=result["strategy"]["used"],
        prompt_tokens=result["token_usage"]["prompt_tokens"],
        output_tokens=result["token_usage"]["output_tokens"],
        prompt_chars=result["retrieval"]["prompt_chars"],
        retrieval_s=result["timing"]["retrieval_s"],
        inference_s=result["timing"]["inference_s"],
        model_json_error=result.get("error"),
    )
    record.update(score_retrieval(case, result["retrieval"]["files"]))
    record.update(score_diagnosis(case, result))
    diff = result["patch"]["unified_diff"]
    record["patch_produced"] = bool(diff)
    record["patch_errors"] = result["patch"]["errors"]
    record["diff"] = diff
    record["patch_validated"] = False
    if diff:
        key = hashlib.sha256(diff.encode()).hexdigest()
        if key not in validations:
            try:
                validations[key] = rm.validate_approved_patch(repo, diff, run_baseline=True)
            except rm.PatchValidationError as exc:
                validations[key] = {"passed": False, "error": str(exc), "changed_files": []}
        validation = validations[key]
        record["patch_validated"] = validation.get("passed") is True
        record["patch_touches_only_bug_file"] = validation.get("changed_files") == [case["bug_file"]]
        record["validation_error"] = validation.get("error")
    return record


def mean(values):
    values = [v for v in values if v is not None]
    return round(statistics.fmean(values), 3) if values else None


def summarise(records: list[dict]) -> list[dict]:
    rows = []
    for model in sorted({r["model"] for r in records}):
        for strategy in rm.STRATEGIES:
            group = [r for r in records if r["model"] == model and r["strategy"] == strategy and "error" not in r]
            if not group:
                continue
            rate = lambda key: round(sum(bool(r.get(key)) for r in group) / len(group), 3)  # noqa: E731
            rows.append(
                {
                    "model": model, "strategy": strategy, "runs": len(group),
                    "errors": sum(1 for r in records if r["model"] == model and r["strategy"] == strategy and "error" in r),
                    "mean_prompt_tokens": mean([r["prompt_tokens"] for r in group]),
                    "mean_prompt_chars": mean([r["prompt_chars"] for r in group]),
                    "mean_files_retrieved": mean([len(r["files"]) for r in group]),
                    "bug_file_recall": rate("bug_file_retrieved"),
                    "mean_relevant_recall": mean([r["relevant_recall"] for r in group]),
                    "mean_precision": mean([r["precision"] for r in group]),
                    "mean_retrieval_s": mean([r["retrieval_s"] for r in group]),
                    "mean_inference_s": mean([r["inference_s"] for r in group]),
                    "located_bug_rate": rate("located_bug"),
                    "diagnosis_heuristic_rate": rate("diagnosis_heuristic_ok"),
                    "patch_produced_rate": rate("patch_produced"),
                    "patch_validated_rate": rate("patch_validated"),
                }
            )
    return rows


def markdown(rows: list[dict], meta: dict) -> str:
    cols = [
        ("model", "model"), ("strategy", "strategy"), ("runs", "runs"), ("errors", "err"),
        ("mean_prompt_tokens", "prompt tok"), ("mean_files_retrieved", "files"),
        ("bug_file_recall", "bug-file recall"), ("mean_precision", "precision"),
        ("mean_retrieval_s", "retr. s"), ("mean_inference_s", "infer. s"),
        ("located_bug_rate", "located"), ("diagnosis_heuristic_rate", "diag. heuristic"),
        ("patch_produced_rate", "patch made"), ("patch_validated_rate", "patch passes tests"),
    ]
    lines = ["| " + " | ".join(label for _, label in cols) + " |", "|" + "---|" * len(cols)]
    for row in rows:
        lines.append("| " + " | ".join(str(row[key]) for key, _ in cols) + " |")
    header = (
        f"Run: {meta['started']} · cases: {meta['cases']} · trials: {meta['trials']} · "
        f"graphify: {meta['graphify_version']} · python {meta['python']}\n\n"
    )
    return header + "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["qwen2.5:3b", "gemma3:1b"])
    parser.add_argument("--strategies", nargs="+", default=["graph", "keyword", "all"], choices=rm.STRATEGIES)
    parser.add_argument("--cases", nargs="*", help="case names (default: all)")
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results")
    parser.add_argument("--sanity-only", action="store_true")
    args = parser.parse_args()

    cases = [c for c in CASES if not args.cases or c["name"] in args.cases]
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    adapter = rm.GraphifyAdapter()
    meta = {
        "started": started, "cases": [c["name"] for c in cases], "trials": args.trials,
        "models": args.models, "num_ctx": 8192, "temperature": 0, "context_budget_chars": 24000,
        "graphify_version": adapter.status(ROOT).get("graphify_version"), "python": platform.python_version(),
        "ollama_models": rm.OllamaClient("x").installed_models(),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    raw_path = args.out / f"raw-{stamp}.jsonl"
    records: list[dict] = []
    graph_builds: dict[str, dict] = {}

    with tempfile.TemporaryDirectory(prefix="repomedic-bench-", ignore_cleanup_errors=True) as tmp:
        for case in cases:
            repo = Path(tmp) / case["name"]
            build_case(case, repo)
            checked = sanity_check(case, repo)
            started_build = time.perf_counter()
            error = adapter.build_graph(repo)
            graph_builds[case["name"]] = {"seconds": round(time.perf_counter() - started_build, 3), "error": error}
            print(f"[{case['name']}] sanity OK (fails before, reference fix passes); graph build "
                  f"{graph_builds[case['name']]['seconds']}s {'ERROR ' + error if error else ''}", flush=True)
            if args.sanity_only:
                continue
            trace = checked["failing_output"]
            validations: dict = {}
            for model in args.models:
                client = rm.OllamaClient(model, timeout=args.timeout)
                if model not in meta["ollama_models"]:
                    print(f"  model {model} is not installed; skipping", flush=True)
                    continue
                for strategy in args.strategies:
                    for trial in range(args.trials):
                        record = run_one(case, repo, trace, model, strategy, client, validations)
                        record["trial"] = trial
                        records.append(record)
                        with raw_path.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(record) + "\n")
                        print(f"  {model:11} {strategy:8} t{trial} tokens={record.get('prompt_tokens')} "
                              f"files={len(record.get('files', []))} located={record.get('located_bug')} "
                              f"patch={record.get('patch_produced')} validated={record.get('patch_validated')} "
                              f"{record.get('error', '')}", flush=True)

    if args.sanity_only:
        print("All cases are valid.")
        return 0
    rows = summarise(records)
    meta["graph_builds"] = graph_builds
    (args.out / f"summary-{stamp}.json").write_text(json.dumps({"meta": meta, "summary": rows}, indent=2), encoding="utf-8")
    table = markdown(rows, meta)
    (args.out / f"summary-{stamp}.md").write_text(table, encoding="utf-8")
    print("\n" + table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
