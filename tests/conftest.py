"""Shared test setup.

Markers:
  real_graphify  - invokes the real installed graphify CLI (.venv-graphify)
  real_ollama    - calls the real local Ollama server
Everything else is a unit test, a mocked test, or uses a stored genuine artifact.
"""
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

GRAPHIFY_EXE = PROJECT / ".venv-graphify" / "Scripts" / "graphify.exe"
if not GRAPHIFY_EXE.is_file():
    GRAPHIFY_EXE = PROJECT / ".venv-graphify" / "bin" / "graphify"


@pytest.fixture(autouse=True)
def no_real_graphify_by_default(request, monkeypatch):
    """Tests that are not marked real_graphify must never run the real tool by accident."""
    if "real_graphify" not in request.keywords:
        monkeypatch.setattr("repomedic.find_graphify", lambda: None)
    else:
        monkeypatch.setattr("repomedic.find_graphify", lambda: str(GRAPHIFY_EXE))


def ollama_running() -> bool:
    from repomedic import OllamaClient

    return OllamaClient("qwen2.5:3b").available()


def installed_models() -> list[str]:
    from repomedic import OllamaClient

    return OllamaClient("qwen2.5:3b").installed_models()


needs_graphify = pytest.mark.skipif(not GRAPHIFY_EXE.is_file(), reason="real graphify not installed")
needs_ollama = pytest.mark.skipif(not ollama_running(), reason="Ollama is not running")
