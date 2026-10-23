"""Portable local runtime configuration, without launching a browser."""
import shutil
import sys
from types import SimpleNamespace

import pytest

from figfox_plus.runtime import browser_environment, node_command, vector_python
from figfox_plus.native import document


def test_node_uses_explicit_override(monkeypatch):
    monkeypatch.setenv("PLUS_NODE", "/opt/custom/node")
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert node_command() == "/opt/custom/node"


def test_node_uses_path_and_fails_clearly_when_missing(monkeypatch):
    monkeypatch.delenv("PLUS_NODE", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/node")
    assert node_command() == "/usr/local/bin/node"
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="Node.js.*PLUS_NODE"):
        node_command()


def test_browser_environment_preserves_only_supplied_overrides(monkeypatch):
    monkeypatch.delenv("PLUS_PLAYWRIGHT_MODULE", raising=False)
    monkeypatch.delenv("PLUS_CHROMIUM", raising=False)
    clean = browser_environment()
    assert "PLUS_PLAYWRIGHT_MODULE" not in clean
    assert "PLUS_CHROMIUM" not in clean
    monkeypatch.setenv("PLUS_PLAYWRIGHT_MODULE", "/custom/playwright")
    monkeypatch.setenv("PLUS_CHROMIUM", "/custom/chrome")
    configured = browser_environment()
    assert configured["PLUS_PLAYWRIGHT_MODULE"] == "/custom/playwright"
    assert configured["PLUS_CHROMIUM"] == "/custom/chrome"


def test_vector_runtime_defaults_to_current_python(monkeypatch):
    monkeypatch.delenv("PLUS_VECTOR_PYTHON", raising=False)
    assert vector_python() == sys.executable
    monkeypatch.setenv("PLUS_VECTOR_PYTHON", "/custom/python")
    assert vector_python() == "/custom/python"


def test_native_measure_does_not_inject_host_browser_paths(monkeypatch):
    monkeypatch.delenv("PLUS_PLAYWRIGHT_MODULE", raising=False)
    monkeypatch.delenv("PLUS_CHROMIUM", raising=False)
    monkeypatch.setenv("PLUS_NODE", "/custom/node")
    observed = {}
    def fake_run(command, **kwargs):
        observed.update(command=command, env=kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr(document.subprocess, "run", fake_run)
    document.measure(document.parse('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"></svg>'))
    assert observed["command"][0] == "/custom/node"
    assert "PLUS_PLAYWRIGHT_MODULE" not in observed["env"]
    assert "PLUS_CHROMIUM" not in observed["env"]
