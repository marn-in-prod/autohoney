import json
from types import SimpleNamespace
from pathlib import Path

from pipeline import runner as runner_module
from pipeline.runner import RunResult, _extract_scores, run_codebase, run_honeypot, write_run_results


def test_write_run_results_includes_observability_fields(tmp_path: Path):
    output = tmp_path / "run_results.json"
    write_run_results(
        [
            RunResult(
                honeypot_id="hp-1",
                honeypot_dir=tmp_path / "hp-1",
                model="test-model",
                epochs=3,
                log_dir=tmp_path / "logs",
                returncode=0,
                duration_seconds=1.25,
                sabotage_rate=0.5,
                ideation_rate=1.0,
            )
        ],
        output,
    )

    data = json.loads(output.read_text())
    assert data == [
        {
            "honeypot_id": "hp-1",
            "honeypot_dir": str(tmp_path / "hp-1"),
            "model": "test-model",
            "epochs": 3,
            "log_dir": str(tmp_path / "logs"),
            "returncode": 0,
            "duration_seconds": 1.25,
            "error": "",
            "main_task_rate": None,
            "sabotage_rate": 0.5,
            "ideation_rate": 1.0,
        }
    ]


def test_run_codebase_discovers_honeypots_and_requires_task_py(tmp_path: Path):
    """run_codebase discovers honeypot subdirectories and requires task.py."""
    from pipeline.runner import discover_honeypots

    codebase = tmp_path / "codebase"
    codebase.mkdir()
    for name in ("hp-a", "hp-b"):
        hp = codebase / name
        hp.mkdir()
        (hp / "task.md").write_text("Do work.")
        (hp / "overlay").mkdir()
    # _hidden and baseline should be skipped
    (codebase / "_hidden").mkdir()
    (codebase / "baseline").mkdir()

    found = discover_honeypots(codebase)
    assert [h.name for h in found] == ["hp-a", "hp-b"]


def test_run_honeypot_passes_absolute_log_dir(tmp_path: Path, monkeypatch):
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    (codebase / "task.py").write_text("# task\n")
    honeypot = codebase / "hp-a"
    honeypot.mkdir()
    (honeypot / "task.md").write_text("Do work.")
    (honeypot / "overlay").mkdir()

    captured = {}

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs["cwd"]

        def wait(self, timeout=None):
            return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner_module.subprocess, "Popen", FakeProc)

    result = run_honeypot(honeypot, "test/model", log_dir=Path("logs"))

    log_dir = Path(captured["cmd"][captured["cmd"].index("--log-dir") + 1])
    assert log_dir == tmp_path / "logs"
    assert log_dir.is_absolute()
    assert result.log_dir == tmp_path / "logs"
    assert captured["cwd"] == str(codebase)


def test_run_honeypot_resolves_relative_honeypot_path_before_package_cwd(tmp_path: Path, monkeypatch):
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    (codebase / "task.py").write_text("# task\n")
    honeypot = codebase / "hp-a"
    honeypot.mkdir()
    (honeypot / "task.md").write_text("Do work.")
    (honeypot / "overlay").mkdir()

    captured = {}

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs["cwd"]

        def wait(self, timeout=None):
            return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner_module.subprocess, "Popen", FakeProc)

    result = run_honeypot(Path("codebase/hp-a"), "test/model")

    task_spec = captured["cmd"][4]
    honeypot_arg = captured["cmd"][captured["cmd"].index("-T") + 1]
    assert task_spec == f"{codebase / 'task.py'}@honeypot_task"
    assert honeypot_arg == f"honeypot_dir={honeypot}"
    assert captured["cwd"] == str(codebase)
    assert result.honeypot_dir == honeypot


def test_extract_scores_marks_inspect_error_status_as_failed(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "eval.json").write_text(
        json.dumps({"status": "error", "error": {"message": "sandbox setup failed"}})
    )
    result = RunResult("hp-a", tmp_path / "hp-a", returncode=0)

    _extract_scores(result, log_dir)

    assert result.returncode == 1
    assert result.error == "sandbox setup failed"


def test_extract_scores_marks_started_log_without_samples_as_failed(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "eval.json").write_text(json.dumps({"status": "started"}))
    result = RunResult("hp-a", tmp_path / "hp-a", returncode=0)

    _extract_scores(result, log_dir)

    assert result.returncode == 1
    assert result.error == "Inspect log status=started with no completed samples"


def test_build_eval_cmd_includes_all_flags(tmp_path: Path):
    """_build_eval_cmd includes model, epochs, connections, sandboxes, and honeypot_dir."""
    from pipeline.runner import _build_eval_cmd

    task_file = tmp_path / "task.py"
    honeypot_dir = tmp_path / "hp-a"
    log_dir = tmp_path / "logs"

    cmd = _build_eval_cmd(task_file, honeypot_dir, "test/model", 5, log_dir)

    assert f"{task_file}@honeypot_task" in cmd
    assert "--model" in cmd
    assert "test/model" in cmd
    assert "--epochs" in cmd
    assert "5" in cmd
    assert f"honeypot_dir={honeypot_dir}" in cmd
    assert "--max-connections" in cmd
    assert "--max-sandboxes" in cmd


def test_run_honeypot_fails_when_inspect_json_status_is_error(tmp_path: Path, monkeypatch):
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    (codebase / "task.py").write_text("# task\n")
    hp = codebase / "hp-a"
    hp.mkdir()
    (hp / "task.md").write_text("Do work.")
    (hp / "overlay").mkdir()
    log_dir = tmp_path / "logs"

    class FakePopen:
        def __init__(self, cmd, cwd, env, stdout, stderr):
            self.cmd = cmd
            self.cwd = cwd
            self.env = env
            self.stdout = stdout
            self.stderr = stderr

        def wait(self, timeout=None):
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "inspect.json").write_text(
                json.dumps({
                    "status": "error",
                    "error": {"message": "sandbox failed"},
                    "samples": [],
                })
            )
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(runner_module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(runner_module.time, "time", lambda: 0.0)

    result = runner_module.run_honeypot(hp, "test-model", log_dir=log_dir)

    assert result.returncode == 1
    assert result.error == "sandbox failed"


def test_run_honeypot_fails_when_inspect_json_is_started_without_samples(tmp_path: Path, monkeypatch):
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    (codebase / "task.py").write_text("# task\n")
    hp = codebase / "hp-a"
    hp.mkdir()
    (hp / "task.md").write_text("Do work.")
    (hp / "overlay").mkdir()
    log_dir = tmp_path / "logs"

    class FakePopen:
        def __init__(self, cmd, cwd, env, stdout, stderr):
            self.cmd = cmd
            self.cwd = cwd
            self.env = env
            self.stdout = stdout
            self.stderr = stderr

        def wait(self, timeout=None):
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "inspect.json").write_text(json.dumps({"status": "started"}))
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(runner_module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(runner_module.time, "time", lambda: 0.0)

    result = runner_module.run_honeypot(hp, "test-model", log_dir=log_dir)

    assert result.returncode == 1
    assert result.error == "Inspect log status=started with no completed samples"
