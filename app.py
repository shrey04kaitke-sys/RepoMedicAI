"""RepoMedic AI - Streamlit frontend. Run: streamlit run app.py

A thin UI over repomedic.py: every number and diff shown here comes from the real Graphify
artifacts, the real Ollama response and real isolated test runs. Nothing is hard-coded.
"""
from __future__ import annotations

import hashlib
import sys
import webbrowser
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import repomedic as rm

PROJECT_DIR = Path(__file__).resolve().parent
try:  # the benchmark bug cases double as sample projects for demos
    sys.path.insert(0, str(PROJECT_DIR / "benchmarks"))
    from cases import CASES, FILLER_FILES
except ImportError:
    CASES, FILLER_FILES = [], {}

st.set_page_config(page_title="RepoMedic AI", page_icon="🩺", layout="wide")

STRATEGY_HELP = {
    "graph": "Graph-assisted, 1 hop (official Graphify graph, falls back to keyword if no graph)",
    "graph2": "Graph-assisted, 2 hops (follows calls one level deeper; experimental)",
    "keyword": "Baseline: keyword-ranked files",
    "all": "Baseline: send every source file",
}
INSTALL_HELP = (
    "Install the official tool in an isolated environment, e.g.\n\n"
    "`python -m venv .venv-graphify` then `.venv-graphify\\Scripts\\pip install graphifyy==0.9.93` "
    "(add `--index-url <mirror>` if PyPI is unreachable). RepoMedic finds it automatically in "
    "`.venv-graphify`, on PATH, or via `GRAPHIFY_EXECUTABLE`."
)

for key, default in (("result", None), ("validation", None), ("applied", None), ("repo_used", None),
                     ("notice", None), ("capture_info", None), ("sample_info", None)):
    st.session_state.setdefault(key, default)


@st.cache_data(ttl=20, show_spinner=False)
def cached_graph_status(repo: str) -> dict:
    return rm.GraphifyAdapter().status(Path(repo))


@st.cache_data(ttl=60, show_spinner=False)
def ollama_info() -> tuple[bool, list[str]]:
    client = rm.OllamaClient(rm.DEFAULT_MODEL)
    up = client.available()
    return up, (client.installed_models() if up else [])


def capture_failure_callback() -> None:
    repo = Path(st.session_state.repo_path).expanduser()
    try:
        outcome = rm.capture_failure(repo)
    except (ValueError, OSError) as exc:
        st.session_state.capture_info = ("error", str(exc))
        return
    if outcome["passed"]:
        st.session_state.capture_info = ("passed", "All tests pass in the isolated copy; there is no failure to capture.")
    else:
        st.session_state.trace = outcome["output"][-6000:]
        st.session_state.capture_info = ("failed", "Captured real failing test output (run in an isolated copy).")


def create_sample_callback() -> None:
    case = next(c for c in CASES if c["name"] == st.session_state.sample_name)
    try:
        path = rm.create_sample_project(PROJECT_DIR / "demo_workspace", case["name"],
                                        {**FILLER_FILES, **case["files"]})
    except (ValueError, OSError) as exc:
        st.session_state.sample_info = ("error", str(exc))
        return
    st.session_state.update(repo_path=str(path), bug=case["bug"], trace="", result=None, validation=None,
                            applied=None, notice=None, capture_info=None)
    st.session_state.sample_info = ("ok", f"Sample ready: {path}. Next: capture the failure, generate the graph, diagnose.")


# ------------------------------------------------------------------ sidebar
st.sidebar.title("🩺 RepoMedic AI")
st.sidebar.caption("Local-first, graph-assisted debugging. No cloud APIs.")
ollama_up, models = ollama_info()
if not ollama_up:
    st.sidebar.error("Ollama is not reachable at 127.0.0.1:11434. Start it with `ollama serve`.")
elif not models:
    st.sidebar.warning(f"Ollama is running but no models are installed. Run `ollama pull {rm.DEFAULT_MODEL}`.")
else:
    st.sidebar.success(f"Ollama running · {len(models)} model(s)")
model = st.sidebar.selectbox(
    "Local model", models or [rm.DEFAULT_MODEL],
    index=(models.index(rm.DEFAULT_MODEL) if rm.DEFAULT_MODEL in models else 0), key="model",
)
strategy = st.sidebar.radio("Retrieval strategy", rm.STRATEGIES, format_func=STRATEGY_HELP.get, key="strategy")
graphify_exe = rm.find_graphify()
if graphify_exe:
    st.sidebar.success("Graphify CLI found")
    st.sidebar.caption(graphify_exe)
else:
    st.sidebar.error("Graphify CLI not found")
    st.sidebar.markdown(INSTALL_HELP)
if CASES:
    st.sidebar.divider()
    st.sidebar.subheader("Sample project")
    st.sidebar.selectbox("Buggy sample", [c["name"] for c in CASES], key="sample_name")
    st.sidebar.button("Create / reset sample and select it", on_click=create_sample_callback,
                      help="Writes a small buggy project to demo_workspace/ inside RepoMedic. Only a folder "
                           "RepoMedic created itself is ever replaced.")
    if st.session_state.sample_info:
        {"ok": st.sidebar.success, "error": st.sidebar.error}[st.session_state.sample_info[0]](
            st.session_state.sample_info[1])
st.sidebar.divider()
if st.sidebar.button("Reset session"):
    for key in ("result", "validation", "applied", "notice", "capture_info"):
        st.session_state[key] = None
    st.rerun()

# ------------------------------------------------------------------ 1. repository
st.title("RepoMedic AI")
st.header("1 · Repository")
repo_text = st.text_input("Repository path", key="repo_path", placeholder=r"C:\path\to\your\project")
repo = Path(repo_text).expanduser() if repo_text.strip() else None
repo_ok = bool(repo and repo.is_dir())
if repo_text.strip() and not repo_ok:
    st.error(f"Not a directory: {repo_text}")
elif repo_ok:
    count = len(rm.RepositoryInspector(repo).files())
    st.success(f"Active repository: {repo.resolve()}")
    st.caption(f"{count} readable source files (secrets, virtualenvs, VCS and generated folders are excluded).")
else:
    st.info("Enter a repository path, or create a sample project from the sidebar.")

# ------------------------------------------------------------------ 2. bug report
st.header("2 · Bug report")
st.text_area("Bug description", key="bug", height=90,
             placeholder="What goes wrong? e.g. 'cart total crashes on prices like $1,299.00'")
st.text_area("Error trace or failing-test output (optional)", key="trace", height=180)
st.button("Run the repo's tests (isolated copy) to capture a failure", disabled=not repo_ok,
          on_click=capture_failure_callback)
st.caption("The button runs the repository's own tests with a fixed command in a temporary copy (no secrets, "
           "no shell). Text typed in the bug report is never executed.")
info = st.session_state.capture_info
if info:
    {"error": st.error, "passed": st.success, "failed": st.info}[info[0]](info[1])

# ------------------------------------------------------------------ 3. graph
st.header("3 · Code graph (Graphify)")
if repo_ok:
    status = cached_graph_status(str(repo.resolve()))
    if not status["exists"]:
        st.warning(status["message"])
    elif status.get("error"):
        st.error(status["error"])
    else:
        cols = st.columns(4)
        cols[0].metric("Nodes", status["nodes"])
        cols[1].metric("Edges", status["edges"])
        cols[2].metric("Communities", status["communities"])
        cols[3].metric("Source files", status["source_files"])
        st.caption(f"Built {status['built_at']} · Graphify {status.get('graphify_version') or 'version unknown'} · {status['graph_json']}")
        if status["stale"]:
            st.warning(f"Graph is older than {len(status['stale_files'])}+ changed file(s), e.g. {status['stale_files'][0]}. Refresh before debugging.")
        st.bar_chart(status["relations"], horizontal=True)
        html_path = rm.artifact_inside_repository(repo, status.get("graph_html"))
        if html_path:
            open_col, download_col = st.columns(2)
            if open_col.button("Open graph.html in my browser",
                               help="Opens Graphify's own visualization with your default browser. The page loads "
                                    "vis-network from unpkg.com, so it needs internet."):
                opened = webbrowser.open(html_path.as_uri())
                st.info(f"Asked your default browser to open {html_path}" if opened
                        else f"Could not launch a browser; open this file manually: {html_path}")
            download_col.download_button("Download graph.html", html_path.read_bytes(), "graph.html", "text/html")
            with st.expander("Preview the interactive graph here (needs internet for vis-network)"):
                components.html(html_path.read_text(encoding="utf-8"), height=650, scrolling=True)
        elif status.get("graph_html"):
            st.warning("graph.html is outside this repository's graphify-out folder, so it was not opened or served.")
        else:
            st.warning("graph.json exists but graph.html does not; run 'Generate / refresh graph' to recreate it.")
    if st.button("Generate / refresh graph", disabled=not graphify_exe,
                 help="Runs `graphify update <repo>`: tree-sitter AST extraction, no LLM, runs locally."):
        with st.spinner("Running graphify update…"):
            error = rm.GraphifyAdapter().build_graph(repo.resolve())
        cached_graph_status.clear()
        if error:
            st.error(f"Graph build failed: {error}")
        else:
            st.success("Graph updated.")
            st.rerun()
else:
    st.info("Enter a valid repository path to see graph status.")

# ------------------------------------------------------------------ 4. diagnose
st.header("4 · Diagnose")
can_run = repo_ok and ollama_up and bool(models) and bool(st.session_state.bug.strip() or st.session_state.trace.strip())
if st.button("Diagnose with local model", type="primary", disabled=not can_run):
    st.session_state.update(result=None, validation=None, applied=None, notice=None)
    with st.status("Debugging…", expanded=True) as box:
        try:
            st.write(f"1/2 Retrieving context ({strategy})…")
            retrieval = rm.retrieve(repo, st.session_state.trace, st.session_state.bug, strategy)
            st.write(f"→ {len(retrieval.files)} file(s) via **{retrieval.strategy_used}** in {retrieval.seconds:.2f}s")
            if retrieval.note:
                st.warning(retrieval.note)
            st.write(f"2/2 Asking {model} (this can take a while on CPU)…")
            result = rm.diagnose(repo, st.session_state.trace, model, st.session_state.bug, strategy, retrieval=retrieval)
            st.session_state.result, st.session_state.repo_used = result, str(repo.resolve())
            box.update(label="Done - diagnosis is unvalidated until a patch passes tests", state="complete")
        except rm.OllamaUnavailableError as exc:
            box.update(label="Local model unavailable", state="error")
            st.error(str(exc))
        except (RuntimeError, ValueError, OSError) as exc:
            box.update(label="Failed", state="error")
            st.error(f"{type(exc).__name__}: {exc}")
if not can_run:
    st.caption("Needs: a valid repository, a bug description or trace, and a running Ollama with an installed model.")

result = st.session_state.result
if result:
    st.divider()
    st.header("Results")
    if result.get("error"):
        st.error(f"The model returned unusable output: {result['error']}")
        with st.expander("Raw model response"):
            st.code(result.get("raw_response", ""))
    st.caption(result["diagnosis_status"])
    m = st.columns(4)
    m[0].metric("Prompt tokens", result["token_usage"]["prompt_tokens"])
    m[1].metric("Output tokens", result["token_usage"]["output_tokens"])
    m[2].metric("Retrieval (s)", result["timing"]["retrieval_s"])
    m[3].metric("Inference (s)", result["timing"]["inference_s"])
    st.caption("Token counts are Ollama's own counters. Retrieval strategy used: "
               f"**{result['strategy']['used']}** · files: {', '.join(result['retrieval']['files']) or 'none'}")

    left, right = st.columns(2)
    with left:
        st.subheader("Diagnosis")
        for h in result["hypotheses"] or []:
            conf = f"{h['confidence']:.0%}" if h["confidence"] is not None else "n/a"
            st.markdown(f"**{h['cause'] or '(no cause given)'}**  \nstatus: `{h['status']}` · model confidence: {conf}")
            if h["evidence"]:
                st.caption(f"Evidence: {h['evidence']}")
        if not result["hypotheses"]:
            st.info("The model gave no hypotheses.")
        if result["relevant_functions"]:
            st.markdown("**Relevant functions:** " + ", ".join(f"`{f}`" for f in result["relevant_functions"]))
    with right:
        st.subheader("Graph context")
        g = result["graphify"]
        st.caption(g["message"])
        if result["strategy"]["note"]:
            st.warning(result["strategy"]["note"])
        if g["entity_labels"]:
            st.write(f"{g['entities']} nodes · {g['relationships']} relationships retrieved (details below)")
        elif result["strategy"]["requested"].startswith("graph"):
            st.warning("No graph context was used for this run.")

    st.subheader("Retrieved context")
    st.caption(f"Strategy requested: **{result['strategy']['requested']}** · used: **{result['strategy']['used']}**")
    files_tab, nodes_tab, edges_tab = st.tabs(["Files sent to the model", "Functions / nodes", "Graph relationships"])
    with files_tab:
        st.dataframe({"order": list(range(1, len(result["retrieval"]["files"]) + 1)),
                      "file": result["retrieval"]["files"]}, hide_index=True)
        st.caption(f"{result['retrieval']['source_chars']} characters of source in a "
                   f"{result['retrieval']['prompt_chars']}-character prompt.")
    with nodes_tab:
        if g["nodes"]:
            st.dataframe(g["nodes"], hide_index=True)
            st.caption("hop: 'seed / 1' = matched the failure or is a direct neighbour; 2+ = reached by following calls.")
        else:
            st.info("No graph nodes: the graph was not used (keyword/all strategy, or the graph was unavailable).")
    with edges_tab:
        if g["edges"]:
            st.dataframe(g["edges"], hide_index=True)
        else:
            st.info("No graph relationships were retrieved for this run.")

    patch = result["patch"]
    st.subheader("Proposed patch")
    if patch["explanation"]:
        st.write(patch["explanation"])
    for err in patch["errors"]:
        st.warning(f"Patch problem: {err}")
    diff = patch["unified_diff"]
    if not diff:
        st.info("No applicable patch was produced. Nothing can be validated or applied.")
    else:
        st.caption(f"Diff generated by RepoMedic from the model's edits ({patch['diff_source']}); the model's text is untrusted.")
        st.code(diff, language="diff")
        diff_id = hashlib.sha256(diff.encode()).hexdigest()
        repo_used = Path(st.session_state.repo_used)

        st.subheader("Validate in an isolated copy")
        if st.button("Validate patch (apply to a temporary copy and run tests)"):
            try:
                with st.spinner("Copying repo, applying patch, running tests…"):
                    validation = rm.validate_approved_patch(repo_used, diff, run_baseline=True)
                st.session_state.validation = (diff_id, validation)
            except (rm.PatchValidationError, OSError) as exc:
                st.session_state.validation = (diff_id, {"error": str(exc)})
        stored = st.session_state.validation
        validation = stored[1] if stored and stored[0] == diff_id else None
        if validation:
            if validation.get("error"):
                st.error(f"Validation could not run: {validation['error']}")
            else:
                base = validation.get("baseline")
                if base:
                    st.write("Before the patch: " + ("tests **passed**" if base["passed"] else "tests **failed** (the bug reproduces)"))
                outcome = validation["passed"]
                if outcome is True:
                    st.success("After the patch: all tests pass in the isolated copy. Your repository is unchanged.")
                elif outcome is False:
                    st.error("After the patch: tests FAILED" + (" (timed out)" if validation.get("timed_out") else "") + ". Do not apply.")
                else:
                    st.warning("This repository has no tests, so the patch could not be tested.")
                with st.expander("Test output"):
                    st.code((validation.get("stdout", "") + "\n" + validation.get("stderr", "")).strip() or "(no output)")

        st.subheader("Approval")
        applied = st.session_state.applied
        if applied:
            st.success(f"Applied to {', '.join(applied['changed_files'])}. Backup: {applied['backup_dir']}")
            st.info("The code changed: refresh the graph before the next debugging session.")
        elif validation and not validation.get("error"):
            untested_ok = False
            if validation["passed"] is None:
                untested_ok = st.checkbox("Allow applying this untested patch (no tests exist)")
            ready = validation["passed"] is True or (validation["passed"] is None and untested_ok)
            reviewed = st.checkbox("I have read the diff above and approve applying it to my repository", disabled=not ready)
            c1, c2 = st.columns(2)
            if c1.button("Approve and apply", type="primary", disabled=not (ready and reviewed)):
                try:
                    st.session_state.applied = rm.apply_approved_patch(
                        repo_used, diff, validation, user_approved=True, allow_untested=untested_ok)
                    cached_graph_status.clear()
                    st.rerun()
                except (rm.PatchValidationError, PermissionError, OSError) as exc:
                    st.error(f"Not applied: {exc}")
            if c2.button("Reject patch"):
                st.session_state.update(result=None, validation=None, notice="Patch rejected. Your repository was not modified.")
                st.rerun()
        else:
            st.caption("Validate the patch first; approval is only offered for a validated patch.")

if st.session_state.notice:
    st.info(st.session_state.notice)
