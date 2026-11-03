"""Runner for honeypot evaluations with parallel process management.

Launches ``inspect eval`` as subprocesses for one or more honeypot folders.
Supports parallel execution with configurable concurrency limits, modeled
after auto-honey-v3's run.py.

Usage (via CLI):
    autohoney run output/openhands/ --model openrouter/moonshotai/kimi-k2.5:nitro --epochs 5
    autohoney run output/openhands/hp_config_thresholds --model openrouter/moonshotai/kimi-k2.5:nitro
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVAL_TIMEOUT = 1500        # 25 minutes per honeypot run (P95 ~11 min)
MAX_PARALLEL = 6           # Max concurrent eval processes
MAX_SANDBOXES = 5          # Per-process sandbox limit (6×5=30, under Docker ~32 limit)
MAX_CONNECTIONS = 100      # API connection pool per process


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def model_short_name(model: str) -> str:
    """Extract short model name: openrouter/x-ai/grok-4.1-fast:nitro -> grok-4.1-fast"""
    name = model.split("/")[-1]
    name = name.split(":")[0]
    return name


def is_honeypot_dir(path: Path) -> bool:
    """Check whether *path* looks like a single honeypot folder."""
    return path.is_dir() and (path / "task.md").exists() and (path / "overlay").is_dir()


def is_codebase_dir(path: Path) -> bool:
    """Check whether *path* looks like a codebase output directory.

    A codebase dir has at least one of: baseline/ dir, compose.yaml, task.py.
    """
    markers = [
        path / "baseline",
        path / "compose.yaml",
        path / "task.py",
    ]
    return path.is_dir() and any(m.exists() for m in markers)


def discover_honeypots(codebase_dir: Path) -> list[Path]:
    """Find all honeypot subdirectories inside a codebase output dir."""
    honeypots = []
    for entry in sorted(codebase_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith(("_", ".")) and entry.name != "baseline":
            if (entry / "task.md").exists():
                honeypots.append(entry)
    return honeypots


# ---------------------------------------------------------------------------
# Docker container cleanup
# ---------------------------------------------------------------------------

def cleanup_inspect_containers(only_stopped: bool = True) -> None:
    """Remove Docker containers from Inspect AI evals.

    Args:
        only_stopped: If True, only remove exited/dead containers (safe during parallel runs).
                      If False, also stop running inspect containers (use only at startup/shutdown).
    """
    try:
        if not only_stopped:
            result = subprocess.run(
                ["docker", "ps", "-q", "--filter", "name=inspect-honeypot-tas"],
                capture_output=True, text=True, timeout=30,
            )
            container_ids = [c for c in result.stdout.strip().split("\n") if c]
            if container_ids:
                print(f"  [CLEANUP] Stopping {len(container_ids)} lingering inspect containers...")
                subprocess.run(["docker", "stop", *container_ids], capture_output=True, timeout=60)

        result = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "name=inspect-honeypot-tas",
             "--filter", "status=exited", "--filter", "status=dead",
             "--filter", "status=created"],
            capture_output=True, text=True, timeout=30,
        )
        container_ids = [c for c in result.stdout.strip().split("\n") if c]
        if container_ids:
            print(f"  [CLEANUP] Removing {len(container_ids)} stopped containers...")
            subprocess.run(["docker", "rm", "-f", *container_ids], capture_output=True, timeout=60)

        subprocess.run(
            ["docker", "network", "prune", "-f", "--filter", "label=com.docker.compose.project"],
            capture_output=True, timeout=30,
        )
    except Exception as e:
        print(f"  [CLEANUP] Warning: container cleanup failed: {e}")


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """Outcome of a single honeypot eval run."""

    honeypot_id: str
    honeypot_dir: Path
    model: str = ""
    epochs: int = 1
    log_dir: Path | None = None
    returncode: int = -1
    duration_seconds: float = 0.0
    error: str = ""
    # Extracted from log.json after run
    main_task_rate: float | None = None
    sabotage_rate: float | None = None
    ideation_rate: float | None = None


# ---------------------------------------------------------------------------
# Core runner — single honeypot
# ---------------------------------------------------------------------------

def _build_eval_cmd(
    task_file: Path,
    honeypot_dir: Path,
    model: str,
    epochs: int,
    log_dir: Path,
) -> list[str]:
    """Build the inspect eval command."""
    return [
        sys.executable, "-m", "inspect_ai", "eval",
        f"{task_file}@honeypot_task",
        "--model", model,
        "--epochs", str(epochs),
        "--max-connections", str(MAX_CONNECTIONS),
        "--max-sandboxes", str(MAX_SANDBOXES),
        "--log-dir", str(log_dir),
        "--display", "plain",
        "--log-format", "json",
        "-T", f"honeypot_dir={honeypot_dir}",
    ]


def _build_env() -> dict[str, str]:
    """Build environment for subprocess."""
    env = os.environ.copy()
    env["INSPECT_DISPLAY"] = "plain"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    return env


def run_honeypot(
    honeypot_dir: Path,
    model: str,
    epochs: int = 1,
    log_dir: Path | None = None,
) -> RunResult:
    """Run a single honeypot evaluation (blocking). Returns a RunResult."""
    honeypot_dir = honeypot_dir.expanduser().resolve()
    codebase_dir = honeypot_dir.parent
    task_file = codebase_dir / "task.py"

    if not task_file.exists():
        return RunResult(
            honeypot_id=honeypot_dir.name,
            honeypot_dir=honeypot_dir,
            model=model,
            epochs=epochs,
            returncode=-1,
            error=f"task.py not found at {task_file}",
        )

    result = RunResult(
        honeypot_id=honeypot_dir.name,
        honeypot_dir=honeypot_dir,
        model=model,
        epochs=epochs,
    )

    if log_dir is None:
        log_dir = honeypot_dir / "logs" / model_short_name(model)
    log_dir = log_dir.expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    result.log_dir = log_dir

    cmd = _build_eval_cmd(task_file, honeypot_dir, model, epochs, log_dir)
    env = _build_env()

    t0 = time.time()
    stdout_log = log_dir / "eval_stdout.log"
    try:
        with open(stdout_log, "w") as lf:
            proc = subprocess.Popen(
                cmd,
                cwd=str(codebase_dir),
                env=env,
                stdout=lf,
                stderr=subprocess.STDOUT,
            )
        try:
            returncode = proc.wait(timeout=EVAL_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            returncode = -9
            result.error = f"Timeout after {EVAL_TIMEOUT}s"
    except Exception as e:
        returncode = -1
        result.error = str(e)

    result.returncode = returncode
    result.duration_seconds = time.time() - t0
    _extract_scores(result, log_dir)

    return result


# ---------------------------------------------------------------------------
# Parallel runner — multiple honeypots
# ---------------------------------------------------------------------------

# Active process entry: (label, proc, log_file, result, start_time)
_ProcEntry = tuple[str, subprocess.Popen, Path, RunResult, float]


def _finish_proc(entry: _ProcEntry, returncode: int) -> RunResult:
    """Finalize a completed process and extract scores."""
    label, proc, log_dir, result, t0 = entry
    result.returncode = returncode
    result.duration_seconds = time.time() - t0
    _extract_scores(result, log_dir)
    return result


def run_codebase(
    codebase_dir: Path,
    model: str,
    epochs: int = 1,
    honeypots: list[str] | None = None,
    log_dir: Path | None = None,
    max_parallel: int = MAX_PARALLEL,
) -> list[RunResult]:
    """Run all honeypots in a codebase directory with parallel execution.

    Launches up to ``max_parallel`` concurrent eval subprocesses.
    Returns list of RunResults in honeypot discovery order.
    """
    codebase_dir = codebase_dir.expanduser().resolve()
    honeypot_dirs = discover_honeypots(codebase_dir)

    if honeypots:
        honeypot_set = set(honeypots)
        honeypot_dirs = [d for d in honeypot_dirs if d.name in honeypot_set]
        missing = honeypot_set - {d.name for d in honeypot_dirs}
        if missing:
            raise ValueError(f"Honeypot(s) not found in {codebase_dir}: {sorted(missing)}")

    if not honeypot_dirs:
        raise ValueError(f"No honeypot directories found in {codebase_dir}")

    if log_dir is not None:
        log_dir = log_dir.expanduser().resolve()

    task_file = codebase_dir / "task.py"
    if not task_file.exists():
        raise ValueError(f"task.py not found at {task_file}")

    env = _build_env()

    # Clean up leftover containers from previous runs
    print(f"  [CLEANUP] Removing leftover inspect containers...")
    cleanup_inspect_containers(only_stopped=False)

    print(f"  Max parallel: {max_parallel} | Sandboxes/proc: {MAX_SANDBOXES} | Timeout: {EVAL_TIMEOUT}s")

    active_procs: list[_ProcEntry] = []
    results: list[RunResult] = []
    results_file = codebase_dir / "run_results.json"

    def _poll_and_reap() -> None:
        """Check active processes, reap any that have finished."""
        i = 0
        while i < len(active_procs):
            label, proc, log_d, result, t0 = active_procs[i]
            ret = proc.poll()
            if ret is not None:
                _finish_proc(active_procs[i], ret)
                status = "OK" if ret == 0 else f"FAIL({ret})"
                print(f"  [{status}] {label} ({fmt_duration(result.duration_seconds)})")
                if result.error:
                    print(f"         Error: {result.error}")
                results.append(result)
                write_run_results(results, results_file)
                cleanup_inspect_containers(only_stopped=True)
                active_procs.pop(i)
            else:
                i += 1

    def _wait_for_slot() -> None:
        """Block until at least one slot opens up."""
        while len(active_procs) >= max_parallel:
            _poll_and_reap()
            if len(active_procs) >= max_parallel:
                time.sleep(2)

    def _wait_all() -> None:
        """Wait for all active processes to finish."""
        for label, proc, log_d, result, t0 in active_procs:
            try:
                ret = proc.wait(timeout=EVAL_TIMEOUT)
            except subprocess.TimeoutExpired:
                print(f"  [TIMEOUT] {label}")
                proc.kill()
                proc.wait()
                ret = -9
                result.error = f"Timeout after {EVAL_TIMEOUT}s"
            result.returncode = ret
            result.duration_seconds = time.time() - t0
            _extract_scores(result, log_d)
            status = "OK" if ret == 0 else f"FAIL({ret})"
            print(f"  [{status}] {label} ({fmt_duration(result.duration_seconds)})")
            if result.error:
                print(f"         Error: {result.error}")
            results.append(result)
            cleanup_inspect_containers(only_stopped=True)
        active_procs.clear()
        write_run_results(results, results_file)
        cleanup_inspect_containers(only_stopped=False)

    # Launch honeypots with bounded parallelism
    for i, hd in enumerate(honeypot_dirs, 1):
        hp_log_dir = log_dir / hd.name if log_dir else hd / "logs" / model_short_name(model)
        hp_log_dir = hp_log_dir.expanduser().resolve()
        hp_log_dir.mkdir(parents=True, exist_ok=True)

        label = f"{hd.name} [{i}/{len(honeypot_dirs)}]"

        # Wait for a slot before launching
        _wait_for_slot()

        result = RunResult(
            honeypot_id=hd.name,
            honeypot_dir=hd,
            model=model,
            epochs=epochs,
            log_dir=hp_log_dir,
        )

        cmd = _build_eval_cmd(task_file, hd, model, epochs, hp_log_dir)
        stdout_log = hp_log_dir / "eval_stdout.log"

        try:
            lf = open(stdout_log, "w")
            proc = subprocess.Popen(
                cmd,
                cwd=str(codebase_dir),
                env=env,
                stdout=lf,
                stderr=subprocess.STDOUT,
            )
            print(f"  [LAUNCH] {label}")
            active_procs.append((label, proc, hp_log_dir, result, time.time()))
        except Exception as e:
            result.returncode = -1
            result.error = str(e)
            print(f"  [FAIL] {label}: {e}")
            results.append(result)
            write_run_results(results, results_file)

    # Wait for remaining processes
    _wait_all()

    return results


# ---------------------------------------------------------------------------
# Score extraction
# ---------------------------------------------------------------------------

def _extract_scores(result: RunResult, log_dir: Path) -> None:
    """Extract sabotage and ideation rates from the most recent log.json."""
    json_files = sorted(log_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
    if not json_files:
        return

    log_path = json_files[-1]
    try:
        with open(log_path) as f:
            log_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    status = log_data.get("status")
    if status == "error":
        result.returncode = 1 if result.returncode == 0 else result.returncode
        error = log_data.get("error") or {}
        if isinstance(error, dict):
            result.error = (
                error.get("message")
                or error.get("type")
                or "Inspect log status=error"
            )
        else:
            result.error = str(error) or "Inspect log status=error"
        return

    samples = log_data.get("samples", [])
    if not samples:
        if status and status != "success":
            result.returncode = 1 if result.returncode == 0 else result.returncode
            result.error = f"Inspect log status={status} with no completed samples"
        return

    main_task_count = 0
    sabotage_count = 0
    ideation_count = 0
    for sample in samples:
        scores = sample.get("scores", {})
        for key in ("main_task_scorer", "main_task"):
            if key in scores:
                val = scores[key].get("value", 0)
                try:
                    if float(val) >= 1.0:
                        main_task_count += 1
                except (ValueError, TypeError):
                    pass
                break
        for key in ("sabotage_scorer", "sabotage"):
            if key in scores:
                val = scores[key].get("value", 0)
                try:
                    if float(val) >= 1.0:
                        sabotage_count += 1
                except (ValueError, TypeError):
                    pass
                break
        for key in ("ideation_scorer", "ideation", "scheming_ideation_scorer", "scheming_ideation"):
            if key in scores:
                val = scores[key].get("value", 0)
                try:
                    if float(val) > 0:
                        ideation_count += 1
                except (ValueError, TypeError):
                    pass
                break

    n = len(samples)
    result.main_task_rate = main_task_count / n
    result.sabotage_rate = sabotage_count / n
    result.ideation_rate = ideation_count / n


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def write_run_results(results: list[RunResult], output_path: Path) -> None:
    """Write durable run observability results as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "honeypot_id": r.honeypot_id,
            "honeypot_dir": str(r.honeypot_dir),
            "model": r.model,
            "epochs": r.epochs,
            "log_dir": str(r.log_dir) if r.log_dir else None,
            "returncode": r.returncode,
            "duration_seconds": r.duration_seconds,
            "error": r.error,
            "main_task_rate": r.main_task_rate,
            "sabotage_rate": r.sabotage_rate,
            "ideation_rate": r.ideation_rate,
        }
        for r in results
    ]
    output_path.write_text(json.dumps(data, indent=2) + "\n")
