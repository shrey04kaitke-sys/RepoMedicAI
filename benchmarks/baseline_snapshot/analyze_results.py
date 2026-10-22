"""Re-analyse a raw benchmark file with ALL trials in every denominator.

    python benchmarks/analyze_results.py benchmarks/results/raw-<stamp>.jsonl

No model is called. Retrieval is deterministic, so it is recomputed per case/strategy; every
stored patch is re-validated in an isolated copy to split "target test still fails" from
"target fixed but other tests broke". The raw file is only read, never modified.
"""
from __future__ import annotations

import hashlib
import json
import re
import statistics
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import repomedic as rm  # noqa: E402
from cases import CASES, build_case  # noqa: E402

CATEGORIES = [
    "valid_patch",
    "regression_target_fixed_others_fail",
    "patch_applies_bug_not_fixed",
    "patch_application_failure",
    "no_patch_proposed",
    "unusable_model_output",
    "timeout",
    "http_error",
    "other_error",
]
FAILED = re.compile(r"^FAILED (\S+)", re.MULTILINE)


def failing_tests(output: str) -> set[str]:
    return set(FAILED.findall(output))


def classify(record: dict, baseline_failures: set[str], outcome: dict | None) -> str:
    error = record.get("error")
    if error:
        if "timed out" in error:
            return "timeout"
        if "HTTP" in error:
            return "http_error"
        return "other_error"
    if record.get("model_json_error"):
        return "unusable_model_output"
    if not record.get("patch_produced"):
        return "no_patch_proposed"
    if outcome is None or outcome.get("error"):
        return "patch_application_failure"
    if outcome["passed"] is True:
        return "valid_patch"
    remaining = failing_tests(outcome.get("stdout", "") + outcome.get("stderr", ""))
    if baseline_failures and not (baseline_failures & remaining):
        return "regression_target_fixed_others_fail"
    return "patch_applies_bug_not_fixed"


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"


def med(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 2) if values else None


def main(raw: Path) -> None:
    records = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = {c["name"]: c for c in CASES}
    outcomes: dict[tuple[str, str], dict] = {}
    baselines: dict[str, set[str]] = {}
    retrieval: dict[tuple[str, str], dict] = {}
    with tempfile.TemporaryDirectory(prefix="repomedic-analysis-", ignore_cleanup_errors=True) as tmp:
        for name, case in cases.items():
            repo = Path(tmp) / name
            build_case(case, repo)
            first = rm.capture_failure(repo, [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"])
            baselines[name] = failing_tests(first["output"])
            rm.GraphifyAdapter().build_graph(repo)
            trace = rm.capture_failure(repo)["output"]
            for strategy in rm.STRATEGIES:
                got = rm.retrieve(repo, trace, case["bug"], strategy)
                relevant = set(case["relevant_files"]) | {f for f in case["files"] if f.startswith("tests/")}
                hits = len(relevant & set(got.files))
                retrieval[(name, strategy)] = {
                    "files": got.files, "used": got.strategy_used,
                    "bug_file": case["bug_file"] in got.files,
                    "recall": hits / len(relevant), "precision": hits / len(got.files) if got.files else 0,
                }
            for record in records:
                diff = record.get("diff")
                if record["case"] == name and diff:
                    key = (name, hashlib.sha256(diff.encode()).hexdigest())
                    if key not in outcomes:
                        try:
                            outcomes[key] = rm.validate_approved_patch(repo, diff)
                        except rm.PatchValidationError as exc:
                            outcomes[key] = {"error": str(exc)}
    for record in records:
        diff = record.get("diff")
        outcome = outcomes.get((record["case"], hashlib.sha256(diff.encode()).hexdigest())) if diff else None
        record["category"] = classify(record, baselines[record["case"]], outcome)

    lines: list[str] = [f"# Benchmark analysis of `{raw.name}`", "",
                        f"{len(records)} trials; **every trial is in every denominator**.", ""]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in records:
        groups[(record["model"], record["strategy"])].append(record)

    lines += ["## Outcomes by model and strategy (denominator = all trials)", "",
              "| model | strategy | trials | " + " | ".join(CATEGORIES) + " |",
              "|---|---|---|" + "---|" * len(CATEGORIES)]
    for (model, strategy), group in sorted(groups.items()):
        counts = [sum(1 for r in group if r["category"] == c) for c in CATEGORIES]
        lines.append(f"| {model} | {strategy} | {len(group)} | " + " | ".join(str(c) for c in counts) + " |")

    lines += ["", "## Headline rates (all trials in the denominator)", "",
              "| model | strategy | valid patch | bug located* | diagnosis heuristic* | timeouts | HTTP errors |",
              "|---|---|---|---|---|---|---|"]
    for (model, strategy), group in sorted(groups.items()):
        n = len(group)
        lines.append(
            f"| {model} | {strategy} | {pct(sum(r['category'] == 'valid_patch' for r in group), n)} "
            f"| {pct(sum(bool(r.get('located_bug')) for r in group), n)} "
            f"| {pct(sum(bool(r.get('diagnosis_heuristic_ok')) for r in group), n)} "
            f"| {pct(sum(r['category'] == 'timeout' for r in group), n)} "
            f"| {pct(sum(r['category'] == 'http_error' for r in group), n)} |")
    lines += ["", "\\* errored trials produced no diagnosis and count as not located / not correct. "
              "The diagnosis check is a keyword heuristic, not a human judgement.", ""]

    lines += ["## Tokens and latency (completed inferences only; n shown)", "",
              "| model | strategy | n done | mean prompt tokens | median inference s | max inference s | mean output tokens |",
              "|---|---|---|---|---|---|---|"]
    for (model, strategy), group in sorted(groups.items()):
        done = [r for r in group if "error" not in r]
        tokens = [r["prompt_tokens"] for r in done if r.get("prompt_tokens") is not None]
        outs = [r["output_tokens"] for r in done if r.get("output_tokens") is not None]
        inf = [r["inference_s"] for r in done]
        lines.append(f"| {model} | {strategy} | {len(done)}/{len(group)} | "
                     f"{round(statistics.fmean(tokens)) if tokens else 'n/a'} | {med(inf)} | "
                     f"{round(max(inf), 1) if inf else 'n/a'} | {round(statistics.fmean(outs)) if outs else 'n/a'} |")

    lines += ["", "## Retrieval quality (deterministic; independent of the model)", "",
              "| case | strategy | used | files | bug file retrieved | recall | precision |", "|---|---|---|---|---|---|---|"]
    for (name, strategy), info in sorted(retrieval.items()):
        lines.append(f"| {name} | {strategy} | {info['used']} | {len(info['files'])} | {info['bug_file']} | "
                     f"{info['recall']:.2f} | {info['precision']:.2f} |")
    for strategy in rm.STRATEGIES:
        rows = [v for (n, s), v in retrieval.items() if s == strategy]
        lines.append(f"| **all cases** | **{strategy}** | | {statistics.fmean(len(r['files']) for r in rows):.1f} | "
                     f"{sum(r['bug_file'] for r in rows)}/{len(rows)} | {statistics.fmean(r['recall'] for r in rows):.2f} | "
                     f"{statistics.fmean(r['precision'] for r in rows):.2f} |")

    lines += ["", "## Per case (valid patches / trials, all models pooled by strategy)", "",
              "| case | model | graph | keyword | all |", "|---|---|---|---|---|"]
    for name in cases:
        for model in sorted({r["model"] for r in records}):
            cells = []
            for strategy in rm.STRATEGIES:
                group = [r for r in records if r["case"] == name and r["model"] == model and r["strategy"] == strategy]
                cells.append(f"{sum(r['category'] == 'valid_patch' for r in group)}/{len(group)}")
            lines.append(f"| {name} | {model} | " + " | ".join(cells) + " |")

    lines += ["", "## Every non-completed trial", "", "| case | model | strategy | trial | error |", "|---|---|---|---|---|"]
    for r in records:
        if "error" in r:
            lines.append(f"| {r['case']} | {r['model']} | {r['strategy']} | {r['trial']} | {r['error'][:90]} |")

    lines += ["", "## Run-to-run variation", ""]
    varied = 0
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        by_key[(r["case"], r["model"], r["strategy"])].append(r)
    for key, pair in sorted(by_key.items()):
        if len({p["category"] for p in pair}) > 1:
            varied += 1
            lines.append(f"- {key[0]} / {key[1]} / {key[2]}: " + " vs ".join(p["category"] for p in pair))
    lines.insert(len(lines) - varied, f"{varied} of {len(by_key)} identical (case, model, strategy) pairs gave different "
                 "outcomes across the 2 trials, although temperature is 0:")

    out = raw.with_name(raw.name.replace("raw-", "analysis-").replace(".jsonl", ".md"))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    raw.with_name(out.stem + ".json").write_text(
        json.dumps([{k: v for k, v in r.items() if k != "diff"} | {"category": r["category"]} for r in records], indent=1),
        encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
