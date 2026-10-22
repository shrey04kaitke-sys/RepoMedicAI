"""Patch construction, validation and approval-gated apply. All subprocess/pytest runs are real."""
import os
import sys
from pathlib import Path

import pytest

import repomedic as rm
from repomedic import PatchValidationError

BUGGY = "def add(a, b):\n    return a - b\n"
TEST = (
    "import sys, pathlib\n"
    "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
    "from calc import add\n\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n"
)
FIX = [{"file": "calc.py", "old": "return a - b", "new": "return a + b"}]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "calc.py").write_text(BUGGY, encoding="utf-8", newline="\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8", newline="\n")
    return tmp_path


# ---------- path safety (adversarial) ----------

@pytest.mark.parametrize(
    "raw",
    [
        "C:foo.py", "D:/x.py", "..\\x.py", "\\\\srv\\share\\x.py", "/etc/x.py", "tests/../x.py",
        "a/.env", "sub/.env.local", ".git/config", "graphify-out/graph.json", ".venv-graphify/x.py",
        ".repomedic-backup/x.py", "NUL", "con.py", "COM1.txt", "b.py:stream", "x.py.", "sub /x.py",
        "tool.exe", "image.png", "", "   ", "a//b.py", "x\x00.py",
    ],
)
def test_unsafe_patch_paths_are_rejected(raw):
    with pytest.raises(PatchValidationError, match="Unsafe patch path"):
        rm._safe_patch_path(raw)


def test_safe_patch_paths_are_normalised():
    assert rm._safe_patch_path("a/src/app.py") == "src/app.py"
    assert rm._safe_patch_path("b/src\\app.py") == "src/app.py"
    assert rm._safe_patch_path("README.md") == "README.md"


def test_symlink_targets_are_rejected(repo: Path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    try:
        (repo / "link.py").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this system")
    with pytest.raises(PatchValidationError, match="symlink|outside"):
        rm.build_diff_from_edits(repo, [{"file": "link.py", "old": "x = 1", "new": "x = 2"}])


# ---------- edits -> diff ----------

def test_edits_build_a_diff_that_applies_and_fixes_the_bug(repo: Path):
    diff = rm.build_diff_from_edits(repo, FIX)
    assert diff.startswith("--- a/calc.py\n+++ b/calc.py\n")
    rm.dry_run_diff(repo, diff)
    result = rm.validate_approved_patch(repo, diff, run_baseline=True)
    assert result["baseline"]["passed"] is False  # the real test fails before the patch
    assert result["passed"] is True  # and passes after, in the isolated copy
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY  # original untouched


@pytest.mark.parametrize(
    "edits,message",
    [
        ([], "no edits"),
        ("not a list", "no edits"),
        ([{"file": "calc.py", "old": "nothing like this", "new": "x"}], "matched 0 times"),
        ([{"file": "calc.py", "old": "a", "new": "x"}], "matched"),  # 'a' occurs several times
        ([{"file": "missing.py", "old": "x", "new": "y"}], "does not exist"),
        ([{"file": "../calc.py", "old": "x", "new": "y"}], "Unsafe patch path"),
        ([{"file": "calc.py", "old": "   ", "new": "y"}], "must not be empty"),
        ([{"file": "calc.py", "old": "return a - b", "new": "return a - b"}], "change nothing"),
        ([{"file": "calc.py", "old": 1, "new": "y"}], "string"),
        (["calc.py"], "string"),
        ([{"file": "calc.py", "old": "x", "new": "y"}] * 11, "Too many"),
    ],
)
def test_bad_edits_are_rejected(repo: Path, edits, message):
    with pytest.raises(PatchValidationError, match=message):
        rm.build_diff_from_edits(repo, edits)


def test_edits_preserve_crlf_line_endings(tmp_path: Path):
    (tmp_path / "m.py").write_bytes(b"def f():\r\n    return 1\r\n")
    diff = rm.build_diff_from_edits(tmp_path, [{"file": "m.py", "old": "return 1", "new": "return 2"}])
    rm.validate_approved_patch(tmp_path, diff, test_command=[sys.executable, "-c", "pass"])
    stage = tmp_path / "copy"
    stage.mkdir()
    (stage / "m.py").write_bytes((tmp_path / "m.py").read_bytes())
    rm.apply_unified_diff(stage, diff)
    assert (stage / "m.py").read_bytes() == b"def f():\r\n    return 2\r\n"


def test_edit_to_file_without_trailing_newline_still_produces_valid_diff(tmp_path: Path):
    (tmp_path / "m.py").write_bytes(b"x = 1")
    diff = rm.build_diff_from_edits(tmp_path, [{"file": "m.py", "old": "x = 1", "new": "x = 2"}])
    rm.dry_run_diff(tmp_path, diff)


def test_single_line_edit_tolerates_wrong_indentation(tmp_path: Path):
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8", newline="\n")
    diff = rm.build_diff_from_edits(tmp_path, [{"file": "m.py", "old": "return 1", "new": "return 2"}])
    assert "+    return 2" in diff


def test_form_feed_in_source_does_not_corrupt_diff(tmp_path: Path):
    (tmp_path / "m.py").write_text("a = 1\n\x0c\nb = 2\n", encoding="utf-8", newline="\n")
    diff = rm.build_diff_from_edits(tmp_path, [{"file": "m.py", "old": "b = 2", "new": "b = 3"}])
    rm.dry_run_diff(tmp_path, diff)


def test_dry_run_rejects_malformed_model_diffs_and_never_writes(repo: Path):
    # Real malformed output captured from qwen2.5:3b (see demo/results.json)
    bad = '@@ -3 +3 @@ -3,1 +3,1 @@ - return float(text.strip("$")) + return float(text.strip(\'$\'))\n'
    with pytest.raises(PatchValidationError):
        rm.dry_run_diff(repo, bad)
    with pytest.raises(PatchValidationError):
        rm.dry_run_diff(repo, "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n-nope\n+yes\n")
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY


# ---------- isolated validation ----------

def test_validation_copy_excludes_secrets_and_secret_env_vars(repo: Path, monkeypatch):
    (repo / ".env").write_text("TOKEN=hunter2\n", encoding="utf-8")
    (repo / ".venv-graphify").mkdir()
    (repo / ".venv-graphify" / "big.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("MY_API_KEY", "super-secret-value")
    probe = (
        "import os,sys;"
        "sys.exit(1 if (os.path.exists('.env') or os.path.exists('.venv-graphify') "
        "or 'MY_API_KEY' in os.environ) else 0)"
    )
    diff = rm.build_diff_from_edits(repo, FIX)
    result = rm.validate_approved_patch(repo, diff, test_command=[sys.executable, "-c", probe])
    assert result["passed"] is True, result
    assert (repo / ".env").exists()  # the original keeps its secret file


def test_failing_patch_is_reported_and_original_is_unchanged(repo: Path):
    diff = rm.build_diff_from_edits(repo, [{"file": "calc.py", "old": "return a - b", "new": "return a * b"}])
    result = rm.validate_approved_patch(repo, diff)
    assert result["passed"] is False
    assert "assert" in (result["stdout"] + result["stderr"]).lower()
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY


def test_test_timeout_is_reported_not_raised(repo: Path):
    diff = rm.build_diff_from_edits(repo, FIX)
    result = rm.validate_approved_patch(
        repo, diff, test_command=[sys.executable, "-c", "import time; time.sleep(30)"], timeout=1
    )
    assert result["passed"] is False and result["timed_out"] is True


def test_validation_rejects_shell_strings_and_missing_repo(repo: Path, tmp_path: Path):
    diff = rm.build_diff_from_edits(repo, FIX)
    with pytest.raises(PatchValidationError):
        rm.validate_approved_patch(repo, diff, test_command="rm -rf /")  # type: ignore[arg-type]
    with pytest.raises(PatchValidationError):
        rm.validate_approved_patch(tmp_path / "nope", diff)


def test_repository_without_tests_reports_untested(tmp_path: Path):
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
    diff = rm.build_diff_from_edits(tmp_path, [{"file": "m.py", "old": "x = 1", "new": "x = 2"}])
    assert rm.validate_approved_patch(tmp_path, diff)["passed"] is None


# ---------- approval-gated apply ----------

def _validated(repo: Path):
    diff = rm.build_diff_from_edits(repo, FIX)
    return diff, rm.validate_approved_patch(repo, diff)


@pytest.mark.parametrize("approval", [False, None, "yes", 1])
def test_apply_requires_explicit_true_approval(repo: Path, approval):
    diff, validation = _validated(repo)
    with pytest.raises(PermissionError):
        rm.apply_approved_patch(repo, diff, validation, user_approved=approval)
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY


def test_apply_refuses_unvalidated_or_failed_patches(repo: Path):
    diff, validation = _validated(repo)
    with pytest.raises(PatchValidationError, match="not passed"):
        rm.apply_approved_patch(repo, diff, {**validation, "passed": False}, user_approved=True)
    with pytest.raises(PatchValidationError, match="not passed"):
        rm.apply_approved_patch(repo, diff, {**validation, "passed": None}, user_approved=True)
    with pytest.raises(PatchValidationError, match="does not match"):
        rm.apply_approved_patch(repo, diff + "\n", validation, user_approved=True)
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY


def test_apply_refuses_if_file_changed_after_validation(repo: Path):
    diff, validation = _validated(repo)
    (repo / "calc.py").write_text(BUGGY + "# edited by someone else\n", encoding="utf-8", newline="\n")
    with pytest.raises(PatchValidationError, match="changed since"):
        rm.apply_approved_patch(repo, diff, validation, user_approved=True)


def test_apply_writes_patch_and_backup_after_approval(repo: Path):
    diff, validation = _validated(repo)
    outcome = rm.apply_approved_patch(repo, diff, validation, user_approved=True)
    assert outcome["applied"] is True and outcome["changed_files"] == ["calc.py"]
    assert "return a + b" in (repo / "calc.py").read_text(encoding="utf-8")
    backups = list((repo / rm.BACKUP_DIRECTORY).rglob("calc.py"))
    assert backups and backups[0].read_text(encoding="utf-8") == BUGGY
    assert not list(repo.glob("*.repomedic-tmp"))
    # the fix really works in the real repo now
    import subprocess

    assert subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=repo, capture_output=True).returncode == 0


def test_untested_patch_needs_explicit_opt_in(tmp_path: Path):
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
    diff = rm.build_diff_from_edits(tmp_path, [{"file": "m.py", "old": "x = 1", "new": "x = 2"}])
    validation = rm.validate_approved_patch(tmp_path, diff)
    with pytest.raises(PatchValidationError):
        rm.apply_approved_patch(tmp_path, diff, validation, user_approved=True)
    rm.apply_approved_patch(tmp_path, diff, validation, user_approved=True, allow_untested=True)
    assert (tmp_path / "m.py").read_text(encoding="utf-8") == "x = 2\n"
