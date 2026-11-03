"""Pipeline configuration using Pydantic Settings."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic_settings import BaseSettings


# ---------------------------------------------------------------------------
# Generation ID generation
# ---------------------------------------------------------------------------

GENERATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "generations"


def generate_generation_id(codebase_slug: str, generations_dir: Path = GENERATIONS_DIR) -> str:
    """Generate a generation ID as ``{codebase_slug}-{YYYYMMDD}-{NNN}``.

    NNN auto-increments based on existing directories for the same slug and
    date inside *generations_dir*.
    """
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"{codebase_slug}-{today}-"

    existing: list[int] = []
    if generations_dir.exists():
        for d in generations_dir.iterdir():
            if d.is_dir() and d.name.startswith(prefix):
                suffix = d.name[len(prefix):]
                if suffix.isdigit():
                    existing.append(int(suffix))

    next_seq = max(existing, default=0) + 1
    return f"{prefix}{next_seq:03d}"


def generation_output_dir(generation_id: str, generations_dir: Path = GENERATIONS_DIR) -> Path:
    """Return the output directory for a given generation ID, creating it if needed."""
    d = generations_dir / generation_id
    d.mkdir(parents=True, exist_ok=True)
    return d


class PipelineConfig(BaseSettings):
    """Configuration for the honeypot generation pipeline.

    Settings are loaded from environment variables with the HONEYPOT_ prefix,
    e.g. HONEYPOT_AGENT_MODEL=claude-opus-4-6.
    """

    model_config = {"env_prefix": "HONEYPOT_"}

    # Generation identification
    generation_id: str = ""
    codebase_slug: str = ""

    # Agent settings
    agent_model: str = "claude-opus-4-6"
    agent_max_turns: int = 50
    agent_max_budget_usd: float = 15
    agent_permission_mode: str = "bypassPermissions"
    agent_cli_path: str = ""
    agent_allowed_tools: list[str] = [
        "Read",
        "Glob",
        "Grep",
        "Bash",
        "Task",
    ]

    # Judge model (for validation)
    judge_model: str = "claude-opus-4-6"

    # Workspace
    workspace_path: str = "/workspace"
