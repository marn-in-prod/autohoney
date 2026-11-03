"""Smoke tests — verify all modules import without errors."""

import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent


def test_import_scanner():
    from pipeline.scanner import scanner
    from pipeline.scanner.models import IncentiveType, ScanConfig, ScanResult

def test_import_deep_mapper():
    from pipeline.deep_mapper import mapper
    from pipeline.deep_mapper.models import DeepMapping, DeepMapResult

def test_import_honeypot_designer():
    from pipeline.honeypot_designer import designer
    from pipeline.honeypot_designer.models import HoneypotDesign, DesignResult

def test_import_task_designer():
    from pipeline.task_designer import task_designer
    from pipeline.task_designer.models import TaskDesign, TaskDesignResult

def test_import_packager():
    from pipeline.packager import packager

def test_import_task_qc():
    from pipeline.task_qc import task_qc

def test_import_framework():
    """Framework files exist (they run inside Docker, not as package imports)."""
    framework_dir = PROJECT_ROOT / "src" / "pipeline" / "framework"
    assert (framework_dir / "task.py").exists()
    assert (framework_dir / "scorer.py").exists()
    assert (framework_dir / "compose.yaml").exists()
    assert (framework_dir / "Dockerfile").exists()


def test_framework_git_diff_host_dependency_declared():
    """Host-side scorers import GitPython via the framework diff utilities."""
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    dependencies = {dep.split(">=", 1)[0].lower() for dep in pyproject["project"]["dependencies"]}

    assert "gitpython" in dependencies


def test_import_agent():
    from pipeline.agent import claude_agent, interface

def test_import_config():
    from pipeline.config import PipelineConfig

def test_sweep_runner_removed():
    """sweep_runner module should have been deleted."""
    import importlib
    with __import__('pytest').raises(ImportError):
        importlib.import_module('pipeline.sweep_runner')
