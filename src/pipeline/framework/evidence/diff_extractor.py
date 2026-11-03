"""Extract git diff evidence by running git diff inside the sandbox."""

import json
import logging
from pathlib import Path

from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

logger = logging.getLogger(__name__)


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "honeypot_config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


async def extract_diff_evidence(state: TaskState) -> str:
    """Extract git diff between setup commit and current sandbox state.

    Uses setup_commit_sha saved during codebase setup to diff only
    the agent's changes (not the honeypot overlay).

    Stages untracked files first so newly created files (e.g. tests)
    appear in the diff.
    """
    config = _load_config()
    workspace_path = config.get("workspace_path", "/workspace")

    ref = (state.metadata or {}).get("setup_commit_sha", "HEAD~1")

    # Stage all files (including new untracked ones) so they appear in the diff
    await sandbox().exec(
        ["git", "-C", workspace_path, "add", "-A"],
    )

    # Diff staged + unstaged changes against the setup commit
    result = await sandbox().exec(
        ["git", "-C", workspace_path, "diff", ref, "--staged", "--", "."],
    )

    if not result.success:
        logger.warning(f"git diff failed: {result.stderr}")
        return ""

    diff_text = result.stdout.strip()

    # Also capture any unstaged changes (belt and suspenders)
    unstaged = await sandbox().exec(
        ["git", "-C", workspace_path, "diff", "--", "."],
    )
    if unstaged.success and unstaged.stdout.strip():
        if diff_text:
            diff_text += "\n\n" + unstaged.stdout.strip()
        else:
            diff_text = unstaged.stdout.strip()

    if not diff_text:
        return ""

    if len(diff_text) > 50_000:
        diff_text = diff_text[:50_000] + "\n\n[TRUNCATED]"

    return f"## CODE DIFFS:\n\n{diff_text}"
