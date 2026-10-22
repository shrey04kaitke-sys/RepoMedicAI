# Contributing to RepoMedic AI

Thanks for helping. This is an early research prototype, so small, well-tested changes are the most useful.

## Setup
Follow the **Quick start** in [README.md](README.md) (Python 3.13, Ollama, `graphifyy` in `.venv-graphify`).
Run the tests with `python -m pytest`. Tests marked `real_graphify` / `real_ollama` use the real tools and are skipped
when those tools are not available; everything else runs offline.

## Ground rules
- **Safety first.** Keep the patch pipeline intact: model output is untrusted, diffs are built by RepoMedic, validation runs
  in a temporary copy, and nothing is applied to a real repository without explicit approval. Changes that weaken
  path checks, secret filtering or the approval gate will not be accepted.
- **Add tests with every change**, including a failure or adversarial case where it makes sense. Say in the test docstring
  whether it uses a mock, a fixture, a stored real artifact, or a real tool.
- **Do not edit recorded evidence.** Files under `benchmarks/results/` and `benchmarks/baseline_snapshot/` are hashed in
  `benchmarks/baseline_snapshot/MANIFEST.sha256`. Add new results in a new folder instead.
- **Report measurements honestly.** Include failed and timed-out trials in denominators and state sample sizes. Do not claim
  an improvement the data does not support.
- No secrets, personal paths, virtual environments or generated Graphify output in commits (`.gitignore` covers the usual ones).

## Pull requests
Keep them focused, describe what you verified and what you did not, and note any benchmark you ran (command and result files).
