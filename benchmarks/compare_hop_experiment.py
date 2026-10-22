"""Compare the 2-hop experiment with the 1-hop control and the original baseline.

    python benchmarks/compare_hop_experiment.py <baseline analysis .json> <experiment analysis .json>

Inputs are the `analysis-*.json` files written by analyze_results.py (one record per trial with a
`category`). Every trial is counted in every denominator. Output: Markdown on stdout.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

FIXED_TARGET = {"valid_patch", "regression_target_fixed_others_fail"}
FAILURES = ["timeout", "http_error", "other_error", "unusable_model_output", "no_patch_proposed",
            "patch_application_failure", "patch_applies_bug_not_fixed", "regression_target_fixed_others_fail"]


def load(path: str) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rate(group: list[dict], predicate) -> str:
    n = len(group)
    k = sum(1 for r in group if predicate(r))
    return f"{k}/{n} ({100 * k / n:.0f}%)" if n else "n/a"


def mean(values) -> str:
    values = [v for v in values if v is not None]
    return str(round(statistics.fmean(values))) if values else "n/a"


def median(values) -> str:
    values = [v for v in values if v is not None]
    return f"{statistics.median(values):.2f}" if values else "n/a"


def main(baseline_path: str, experiment_path: str) -> None:
    sources = {
        "baseline run (old code) · graph (1-hop)": [r for r in load(baseline_path) if r["strategy"] == "graph"],
        "control run (current code) · graph (1-hop)": [r for r in load(experiment_path) if r["strategy"] == "graph"],
        "experiment (current code) · graph2 (2-hop)": [r for r in load(experiment_path) if r["strategy"] == "graph2"],
    }
    models = sorted({r["model"] for rows in sources.values() for r in rows})
    out = ["# 2-hop experiment: results", "",
           "Every trial is in every denominator. 'Bug file retrieved' is retrieval only; errored trials still have a",
           "deterministic retrieval, but the raw records of errored trials carry no file list, so it is recomputed in the",
           "analysis files only for completed trials: here it is reported over completed trials with n shown.", ""]
    for model in models:
        out += [f"## {model}", "",
                "| run | trials | valid patch (all tests pass) | target test fixed | patch produced | "
                "timeouts | HTTP errors | unusable output | bug file retrieved (completed) | mean prompt tok (completed) | median inference s |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, rows in sources.items():
            group = [r for r in rows if r["model"] == model]
            done = [r for r in group if "error" not in r]
            out.append(
                f"| {name} | {len(group)} | {rate(group, lambda r: r['category'] == 'valid_patch')} "
                f"| {rate(group, lambda r: r['category'] in FIXED_TARGET)} "
                f"| {rate(group, lambda r: bool(r.get('patch_produced')))} "
                f"| {rate(group, lambda r: r['category'] == 'timeout')} "
                f"| {rate(group, lambda r: r['category'] == 'http_error')} "
                f"| {rate(group, lambda r: r['category'] == 'unusable_model_output')} "
                f"| {rate(done, lambda r: r.get('bug_file_retrieved'))} "
                f"| {mean(r.get('prompt_tokens') for r in done)} "
                f"| {median(r.get('inference_s') for r in done)} |")
        out.append("")
        out += ["Outcome breakdown (counts of all trials):", "",
                "| run | valid_patch | " + " | ".join(FAILURES) + " |", "|---|---|" + "---|" * len(FAILURES)]
        for name, rows in sources.items():
            group = [r for r in rows if r["model"] == model]
            counts = [sum(1 for r in group if r["category"] == c) for c in ["valid_patch"] + FAILURES]
            out.append(f"| {name} | " + " | ".join(str(c) for c in counts) + " |")
        out.append("")
        out += ["Per case, valid patches / trials:", "",
                "| case | " + " | ".join(sources) + " |", "|---|" + "---|" * len(sources)]
        for case in sorted({r["case"] for rows in sources.values() for r in rows}):
            cells = []
            for rows in sources.values():
                group = [r for r in rows if r["model"] == model and r["case"] == case]
                cells.append(f"{sum(r['category'] == 'valid_patch' for r in group)}/{len(group)}")
            out.append(f"| {case} | " + " | ".join(cells) + " |")
        out.append("")
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
