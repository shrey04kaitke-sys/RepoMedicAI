# RepoMedic AI — Project Audit

Audit date: 2026-10-22. Sections marked **[baseline]** describe the state *before* the
Phase 3–9 work in this session; the final state is in the "Final state" section at the end.
"Verified" means I executed it and saw the result; "code-read" means read but not executed.

## 1. Architecture and file responsibilities [baseline]

| Path | Responsibility |
|---|---|
| `repomedic.py` (605 lines) | Everything: `RepositoryInspector` (file listing/secret filter), `TracebackParser`, `GraphifyAdapter` (graph.json reader, `graphify update` runner), `OllamaClient`, `analyze()`, `main()` CLI, `apply_unified_diff`, `validate_approved_patch`, prompt builder |
| `tests/test_repomedic.py` (294 lines) | 28 tests |
| `pytest.ini` | markers `real_graphify`, `real_ollama`; `testpaths` |
| `README.md` | Docs (updated last session) |
| `demo/` | One real demo run: script, prompts, results, real graph artifacts for a temp repo |
| `graphify-out/` | Real Graphify output for this project (generated, not hand-written) |
| `.venv-graphify/` | Isolated venv with `graphifyy==0.9.93` (174 MB) |

Entry point: `python repomedic.py <repo> --failure <text> [--model M]` → `analyze()`.
Flow (code-read + verified by demo run): parse traceback → `GraphifyAdapter.context` (find or build
`graph.json`, seed nodes, 1-hop edges) → source scoped to graph files → `build_prompt` →
`OllamaClient.generate` (JSON mode) → `parse_model_output` → force `review_required=True` →
print JSON. **`analyze()` never calls patch validation and nothing applies a patch**; `validate_approved_patch`
is only a library function with no caller outside tests.

## 2. Implemented and verified
- Real `graphify update` build and consumption of the genuine `graph.json` (3 real tests + demo).
- Function-level then file-level seed matching, absolute→relative path mapping, 1-hop neighbours, stale rebuild.
- Real Ollama inference with `qwen2.5:3b` through the CLI (demo); `num_ctx` set (truncation bug fixed).
- Review flag forced in code; path traversal `..`/absolute rejection; validation in a temp copy leaves source intact (tests).

## 3. Exists but only mock/fixture tested
- Build-failure reporting and the `update` command line (mocked `subprocess.run`).
- Malformed/stale graph handling (hand-written JSON).
- `analyze()` pipeline unit test (mocked Ollama).
- The `GRAPHIFY_COMMAND` "JSON provider" protocol: **invented, not a Graphify interface**; its status message
  says "Graphify returned…", which is misleading. Retained only because a test depends on it.

## 4. Missing or broken (verified unless noted)
1. **No approval/apply step.** Nothing writes an approved patch to the original repo.
2. **Patch path validation is weak** (probe executed): `C:foo.py` (drive-relative), `.env`, `.git/config`,
   `graphify-out/...`, `NUL`, and `name:stream` are all accepted.
3. **Validation copy has no ignore list** (code-read): `shutil.copytree` copies `.env`, `.git`, and the 174 MB venv.
4. Models emit malformed unified diffs (demo: 0/6 applicable) → no usable patch with the 3B model.
5. `--failure` is the only input; no separate bug description; no timing metrics; no model-installed check
   (a missing model surfaces only as a generic "request failed").
6. No frontend; no `requirements.txt`; no `.gitignore`; not a Git repository.
7. `source_context` is char-bounded but not prioritised (failing functions may be cut off by large files).
8. No baseline-vs-graph benchmark harness beyond one demo case; accuracy never measured against ground truth.

## 5. Dependencies / environment
Python 3.13.0 (global); global packages relevant: `pytest 9.1.1`, `streamlit 1.55.0` (pre-installed, not added by me),
`networkx`, `numpy`, `pandas`. Core CLI needs only the standard library. Graphify lives only in `.venv-graphify`
(`graphifyy 0.9.93`, mirror-installed because PyPI is unreachable from this machine). Ollama 0.40.8 local with
`qwen2.5:3b` (3.1B) and `gemma3:1b` (1B). No secrets or `.env` file exist in the project; no API keys are used.

## 6. Security / reliability concerns
Items 2–3 above; also (code-read) symlinks are not rejected when applying; tests of an approved patch execute
repository test code (arbitrary code from the repo under test, run with the user's privileges — inherent to
running its tests, should be stated); `timeout=120` on validation tests but no output-size limit beyond slicing.

## 7. Frontend status
None existed. Streamlit 1.55.0 is importable and ships `AppTest`, which allows headless verification.

## 8. Graphify status
Operational and genuinely consumed (see §2). Mirror-install caveat; wheel not compared with the pinned commit.

## 9. Local model status
Reachable; both models installed. `qwen2.5:3b` gives plausible diagnoses, unreliable diffs. `gemma3:1b` not yet evaluated.

## 10. Plan (priority order)
1. Harden patch paths + validation copy; add `apply_approved_patch` (explicit approval, must have passed
   validation, hash-checked, backup, atomic) — with adversarial tests.
2. Edit-based patches: model returns `{file, old, new}` edits; RepoMedic builds the diff with `difflib`
   against the real file (model output stays untrusted; unmatched `old` text is rejected).
3. Pipeline: bug description + trace, model-presence check, timeouts, retrieval/inference timing, bounded and prioritised context.
4. Streamlit frontend over the same backend functions.
5. Benchmark harness: ≥4 ground-truth bugs × {all-files, keyword-bounded, graph} × 2 models, repeated trials.
6. Tests, README, final audit update.

---

# Final state (end of session, 2026-10-22)

Everything above this line is the baseline audit. Below is what was done and verified afterwards.

## Status of each baseline problem
| # | Baseline problem | Now | Evidence |
|---|---|---|---|
| 1 | No approval/apply step | **Fixed** | `apply_approved_patch`: needs `user_approved is True`, passed validation for the exact diff, unchanged files; backup + atomic write. 10 tests; real UI run applied a patch |
| 2 | Weak patch paths | **Fixed** | 24 adversarial path cases rejected (drive-relative, ADS, device names, `.env`, `.git`, symlink…) |
| 3 | Validation copy had secrets/venv | **Fixed** | copy ignores secrets/VCS/venvs; secret env vars stripped; tested with a real subprocess probe |
| 4 | Models emit malformed diffs | **Mitigated** | model returns edits, RepoMedic builds the diff. Models still fail often (see benchmark) |
| 5 | Single `--failure` input, no timing, no model check | **Fixed** | `--bug`/`--failure`, timings, token counters, 404 → "ollama pull", timeouts, HTTP error bodies |
| 6 | No frontend / requirements / .gitignore | **Fixed** | `app.py` (Streamlit), `requirements*.txt`, `.gitignore`, `.streamlit/config.toml`. Still not a Git repo |
| 7 | Context not prioritised | **Partly** | seeds first, per-strategy file cap, char budget with truncation marker; no function-level slicing |
| 8 | No benchmark | **Done, with negative findings** | 72 real trials; see below |

## Verified
- Tests: **132 passed, 1 skipped (symlink permission), 0 failed**; 123 use no real tool, 10 use real Graphify/Ollama (all passed).
- Real Graphify 0.9.93 builds and is consumed (graph status, retrieval, stale rebuild, UI refresh).
- Streamlit: `streamlit run app.py` serves (health `ok`, HTTP 200); 8 headless AppTests drive the real backend.
- Real end-to-end through the UI with real `qwen2.5:3b` + real Graphify: capture → graph → diagnose → validate →
  approve → applied; repo tests pass afterwards; backup exists; repo unchanged before approval (1 run).
- Secret/unsafe-pattern scan of project sources: none found (`shell=True`, `eval`, `exec`, `pickle`, hard-coded keys).

## Benchmark (72 trials; all in every denominator; raw file preserved, checksum unchanged by analysis)
See README for the table. Headlines: qwen2.5:3b valid patches all-files 4/12, graph 2/12, keyword 1/12; gemma3:1b 0/36.
Graph retrieval found the bug file in 2/6 cases (keyword 5/6, all 6/6) while using ~53% fewer prompt tokens.
7 HTTP 500s (one reproduced: `token repeat limit reached`; the rest unconfirmed), 2 timeouts (runaway generation).

## Not validated / caveats
- **The benchmark ran before** `num_predict=2048` and the HTTP-error-body change (repomedic.py modified 16:11:50; benchmark
  started 16:03:11). Those fixes are covered only by 4 mocked tests; their effect on benchmark outcomes is unmeasured.
- Graph retrieval (`graph`) is 1-hop and misses the buggy callee for assertion failures (4/6 cases). `graph2` (2-hop) was implemented and evaluated: retrieval 2/6 → 5/6, but no end-to-end improvement (see below).
- Benchmark is small and synthetic (6 cases, 2 trials, 2 small models); no statistical significance; diagnosis scoring is a keyword heuristic.
- Cause of 6 of 7 HTTP 500s is not confirmed.
- Validation executes repository tests (inherent); Graphify installed from a third-party mirror; `GRAPHIFY_COMMAND` is a non-Graphify legacy hook.
- The end-to-end UI run with a real model is one sample.

## Files added/changed this session
`repomedic.py` (pipeline, safety, apply, status, parser), `app.py`, `benchmarks/{cases,run_benchmark,analyze_results}.py`,
`benchmarks/results/*` (raw, summary, analysis), `tests/{conftest,test_patch_safety,test_pipeline,test_frontend,test_benchmark}.py`
(plus the original `test_repomedic.py`, unchanged in intent), `README.md`, `PROJECT_AUDIT.md`, `requirements*.txt`,
`.gitignore`, `.streamlit/config.toml`, `pytest.ini`, `demo/`, `.venv-graphify/` (isolated env), `graphify-out/` (generated).

## 2-hop experiment (added after the first audit)
- Implemented `graph2` (`_expand_call_hops`; `--hops`, max 4; caps 80 nodes / +40 edges; call-flow only, caller→callee; dedup; exclusions). `graph` (1-hop) unchanged as control.
- Tests: 37 new (traversal depth, cycles/diamonds, hub avoidance, exclusions, node/edge/character budgets, stale and malformed graphs, invalid hops, real Graphify on all 6 bugs). Full suite: **169 passed, 1 skipped, 0 failed** (154 without real tools, 16 with).
- Evaluation: 48 graph-only trials (control re-run under current code + graph2) in `benchmarks/results/hop_experiment/`; baseline files hash-verified unchanged.
- Result: bug file retrieved 2/6 → 5/6 (as predicted before the run); qwen valid patches 2/12 → 0/12, gemma 0/12 → 0/12. No improvement in end-to-end success; the drop is within noise at n=12. Reason untested.
- Confirmed this run: 3/3 captured HTTP 500 bodies = `prediction aborted, token repeat limit reached`; 7 trials hit the 2048-token cap (truncated JSON), 0 timeouts.

## Next steps (priority order)
1. Diagnose why correct retrieval did not yield patches: edit-quote failures (5–7/12 trials had rejected edits) are the largest measured failure mode; try function-level source slices with line numbers, an edit-repair/retry loop, or a larger local model, each evaluated against the same cases.
2. Consider one retry when Ollama reports `token repeat limit reached`.
3. More and larger cases, more trials, a larger local model if hardware allows, and human scoring of diagnoses.

---

# Frontend completion (after the 2-hop experiment)

## Pre-change inspection (2026-10-22)
- A Streamlit frontend (`app.py`) already existed; launched with `streamlit run app.py`; no launcher; `headless=true` (no auto-open).
- `graphify-out/graph.json` (107 nodes, 240 links), `graph.html`, `GRAPH_REPORT.md` existed, generated 3:43:51 PM — older than the project's current sources (stale for RepoMedic's own repo).
- Gaps found: no graph-relationship view; retrieved files/functions shown only as a caption and a label list; no open-in-browser for `graph.html`;
  `graph.html` path could be redirected by `GRAPHIFY_GRAPH`; no sample project, no launcher; server bound beyond localhost (Network/External URL printed).

## Implemented and verified
| Feature | Status | Evidence |
|---|---|---|
| Active repository banner; sample project (create/reset) | Done | UI tests; reset only for marker-bearing folders; read-only cache removal fixed (regression test) |
| Bug text + optional trace; capture real failure | Done | fixed command, isolated copy, secrets stripped (test shows the test process saw no `MY_API_KEY`/`.env`) |
| Strategy selector `graph` / `graph2` (+ baselines) | Done | UI test; real-Graphify UI test: control misses `fees.py`, graph2 retrieves it |
| Retrieved files / functions (file, line, hop) / relationships | Done | `graph_node_rows`, `graph_edge_rows`; tabs in the Results section |
| Open Graphify visualisation | Done | button + download + embedded preview; only for files inside `<repo>/graphify-out` (tested, incl. a `GRAPHIFY_GRAPH` redirect) |
| Diagnosis, patch, validate, approve/reject | Done (pre-existing) | unchanged safety path; approval cannot be clicked before validation + review box |
| Error messages | Done | tests: no Ollama, model not installed, no Graphify, no graph (fallback warning), build failure, invalid patch, failed tests |
| Localhost-only server, launcher | Done | `.streamlit/config.toml` address=localhost; `run_ui.ps1`; socket check: 127.0.0.1 / ::1 only |

Defects the new tests found and fixed: mixed int/str `hop` column (pyarrow `ArrowTypeError` when rendering); sample reset failing on read-only
Graphify cache folders (and stranding a half-deleted folder); server listening on all interfaces.

## Verification status
- Tests: **188 passed, 1 skipped (symlink permission), 0 failed**; 172 without real tools, 17 with real Graphify and/or Ollama. Benchmark files re-verified unchanged (hashes).
- Server: started via `run_ui.ps1`, `/_stcore/health` = `ok`, HTTP 200, stopped cleanly.
- One real-model UI demonstration (not a benchmark): sample `free_shipping_boundary`, `graph2` retrieved `fees.py`/`shipping_fee()` at hop 2; `qwen2.5:3b`
  blamed the wrong function and proposed a broken patch; validation reported "tests FAILED. Do not apply."; the sample stayed untouched.
- **Not verified:** the page's visual appearance in a real browser (no browser automation available), the embedded graph preview rendering, and a real browser opening `graph.html`.
  The project's own `graphify-out` is stale (older than the current sources); refresh it from the UI before demoing on RepoMedic itself.
