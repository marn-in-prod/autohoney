"""Pydantic models for the QC gate (task distinctness check)."""

from typing import Literal

from pydantic import BaseModel


class HoneypotQCEntry(BaseModel):
    """QC result for a single (design_id, task_id) pair."""

    design_id: str
    task_id: str
    task_title: str
    uses_no_overlay_precondition: bool
    verdict: Literal["pass", "fail", "skipped"]
    reason: str
    failing_pairs: list[str]  # empty if verdict != "fail"
    overlap_score: int | None  # None if verdict == "skipped"
    agent_error: str | None = None
    stderr: str = ""
    exit_code: int | None = None
    agent_message_count: int | None = None


class QCResults(BaseModel):
    """Collection of QC entries for one package run."""

    entries: list[HoneypotQCEntry]


class RejectedTask(BaseModel):
    """A task that was rejected by the QC gate (convenience for CLI logging)."""

    design_id: str
    task_id: str
    task_title: str
    overlap_score: int | None
    reason: str
    failing_pairs: list[str]
