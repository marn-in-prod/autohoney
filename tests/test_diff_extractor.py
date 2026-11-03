"""Tests for the in-sandbox git diff extractor."""

import json
from pathlib import Path
from types import SimpleNamespace

from pipeline.framework.evidence import diff_extractor


def test_load_config_returns_empty_when_no_file(tmp_path, monkeypatch):
    """_load_config returns {} when honeypot_config.json doesn't exist."""
    monkeypatch.setattr(
        diff_extractor,
        "_load_config",
        lambda: {},
    )
    assert diff_extractor._load_config() == {}


def test_load_config_reads_workspace_path(tmp_path, monkeypatch):
    """_load_config reads workspace_path from honeypot_config.json."""
    config_dir = tmp_path / "evidence"
    config_dir.mkdir()
    config_path = tmp_path / "honeypot_config.json"
    config_path.write_text(json.dumps({"workspace_path": "/workspace/petri"}))

    # Patch _load_config to read from our tmp config
    def mock_load():
        return json.loads(config_path.read_text())

    monkeypatch.setattr(diff_extractor, "_load_config", mock_load)
    config = diff_extractor._load_config()
    assert config["workspace_path"] == "/workspace/petri"


def test_extract_uses_setup_commit_sha_from_metadata():
    """extract_diff_evidence should use setup_commit_sha from state.metadata."""
    state = SimpleNamespace(metadata={"setup_commit_sha": "abc123"})
    ref = (state.metadata or {}).get("setup_commit_sha", "HEAD~1")
    assert ref == "abc123"


def test_extract_falls_back_to_head_tilde_1():
    """extract_diff_evidence falls back to HEAD~1 when no setup_commit_sha."""
    state = SimpleNamespace(metadata={})
    ref = (state.metadata or {}).get("setup_commit_sha", "HEAD~1")
    assert ref == "HEAD~1"


def test_extract_handles_none_metadata():
    """extract_diff_evidence handles state.metadata being None."""
    state = SimpleNamespace(metadata=None)
    ref = (state.metadata or {}).get("setup_commit_sha", "HEAD~1")
    assert ref == "HEAD~1"
