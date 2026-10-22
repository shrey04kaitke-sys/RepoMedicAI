# demo/ — evidence from the first real end-to-end run

These files were produced by `run_demo.py` against a temporary shop app with one bug (`parse_price` does not
handle `$1,299.00`), using the real Graphify CLI and a real local `qwen2.5:3b`:

- `failure.txt`, `traceback.txt` — the real pytest output and traceback.
- `graphify-out-demo/` — the real `graph.json`, `graph.html` and `GRAPH_REPORT.md` that `graphify update` produced.
- `prompt_*.txt`, `results.json` — the prompts sent to the model and the raw responses.

The test suite uses `failure.txt` and `graphify-out-demo/graph.json` as stored genuine artifacts.
The local Windows user name inside temporary paths was replaced by `<user>` before publishing; nothing else was edited.
This is a single illustrative run, not a benchmark — see `benchmarks/` for the 72-trial evaluation.
