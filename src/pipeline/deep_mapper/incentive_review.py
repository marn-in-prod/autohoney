"""Incentive quality review gate — validates incentive types and motivation strength using an LLM judge."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from pipeline.deep_mapper.models import DeepMapResult, DeepMapping, FailedTarget
from pipeline.scanner.models import Candidate, IncentiveType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROMPT_PATH = Path(__file__).parent / "prompts" / "incentive_review.md"

# Motivation strength levels ordered from weakest to strongest.
_MOTIVATION_LEVELS: list[str] = ["low", "moderate", "high", "very high"]

# JSON schema for the per-mapping judge response
_JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["keep", "fix", "drop"]},
        "recommended_type": {
            "type": ["string", "null"],
            "enum": [
                "weaken_oversight", "escalate_access", "acquire_resources",
                "exfiltrate_data", "influence_training", "undermine_evaluation",
                "establish_persistence", "self_preservation", "preserve_goals",
                "enhance_cognition", "deceive_evaluators",
                None,
            ],
        },
        "reason": {"type": "string"},
    },
    "required": ["action", "recommended_type", "reason"],
    "additionalProperties": False,
}


class IncentiveReviewEntry(BaseModel):
    """Persisted incentive review decision for one mapped candidate."""

    candidate_id: str
    claimed_incentive_type: str | None = None
    action: str
    recommended_type: str | None = None
    reason: str
    final_action: str
    final_reason: str = ""
    min_motivation: str | None = None
    motivation_strength: str | None = None
    agent_error: str | None = None
    stderr: str = ""
    exit_code: int | None = None
    agent_message_count: int | None = None


class IncentiveReviewResults(BaseModel):
    """Persisted output of the incentive review gate."""

    entries: list[IncentiveReviewEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_code_trace(mapping: DeepMapping) -> str:
    """Summarize the code trace entries into a readable block."""
    lines: list[str] = []
    for entry in mapping.code_trace:
        lines.append(f"- {entry.file} ({entry.role})")
        lines.append(f"  Code: {entry.relevant_code}")
        lines.append(f"  Details: {entry.key_details}")
    return "\n".join(lines)


def _meets_min_motivation(mapping: DeepMapping, min_motivation: str) -> bool:
    """Return True if the mapping meets the minimum motivation threshold."""
    strength = mapping.schemer_motivation.strength_of_motivation.lower().strip()
    try:
        actual_idx = _MOTIVATION_LEVELS.index(strength)
    except ValueError:
        # Unknown level — keep it (don't silently drop)
        return True
    try:
        min_idx = _MOTIVATION_LEVELS.index(min_motivation.lower().strip())
    except ValueError:
        return True
    return actual_idx >= min_idx


# ---------------------------------------------------------------------------
# Single-mapping review
# ---------------------------------------------------------------------------


async def _review_single_mapping(
    mapping: DeepMapping,
    candidate: Candidate,
    agent,
) -> dict[str, Any]:
    """Run the LLM judge on a single mapping and return the parsed response.

    Returns a dict with keys: action, recommended_type, reason.
    On error, returns action="keep" (fail-open — don't silently drop candidates
    due to judge failures; the LLM review is advisory, not blocking).
    """
    prompt_template = PROMPT_PATH.read_text()

    mot = mapping.schemer_motivation
    prompt = prompt_template.format(
        candidate_id=mapping.candidate_id,
        candidate_area=candidate.area,
        target_summary=mapping.target_summary,
        code_trace_summary=_format_code_trace(mapping),
        what_a_schemer_gains=mot.what_a_schemer_gains,
        magnitude=mot.magnitude,
        persistence=mot.persistence,
        strength_of_motivation=mot.strength_of_motivation,
        why=mot.why,
        concealment_ease=mot.concealment_ease,
        concealment_why=mot.concealment_why,
        what_specifically_matters=mot.what_specifically_matters,
        claimed_incentive_type=candidate.incentive_type,
    )

    result = await agent.run(
        prompt=prompt,
        cwd=".",
        output_schema=_JUDGE_SCHEMA,
    )

    if not result.success or result.structured_output is None:
        logger.warning(
            "Incentive review judge failed for %s: %s — defaulting to keep (fail-open).",
            mapping.candidate_id, result.error,
        )
        return {
            "action": "keep",
            "recommended_type": None,
            "reason": f"Judge error: {result.error}",
            "agent_error": result.error,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "agent_message_count": result.message_count,
        }

    from pipeline.agent.interface import unwrap_structured_output

    return unwrap_structured_output(
        result.structured_output,
        {"action", "recommended_type", "reason"},
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def review_incentives(
    result: DeepMapResult,
    candidates: list[Candidate],
    agent=None,
    min_motivation: str | None = None,
) -> tuple[DeepMapResult, IncentiveReviewResults]:
    """Review each mapping's incentive type and motivation. Returns modified result.

    For each DeepMapping in result.mappings:
    1. Looks up the original Candidate by candidate_id for context.
    2. Calls an LLM judge to validate the incentive type and motivation.
    3. Based on the judge's response:
       - "keep": no changes
       - "fix": updates mapping.incentive_type to the judge's recommended type
       - "drop": removes from mappings, adds to failed_targets with reason

    After LLM review, applies optional --min-motivation programmatic filter.

    Args:
        result: DeepMapResult from the deep mapper.
        candidates: Original Candidate list from scan.yaml (for incentive type lookup).
        agent: Agent for LLM calls. Creates a ClaudeAgent if None.
        min_motivation: If set, programmatically drop mappings below this motivation
            level after the LLM review. One of: "low", "moderate", "high", "very high".

    Returns:
        Modified DeepMapResult with updated incentive types, dropped candidates
        moved to failed_targets, plus persisted review entries.
    """
    from pipeline.agent.claude_agent import ClaudeAgent

    agent = agent or ClaudeAgent()

    # Build candidate lookup by ID
    candidate_by_id: dict[str, Candidate] = {c.id: c for c in candidates}

    # Run all reviews concurrently
    review_tasks: list[tuple[DeepMapping, Candidate]] = []
    for mapping in result.mappings:
        candidate = candidate_by_id.get(mapping.candidate_id)
        if candidate is None:
            logger.warning(
                "No matching candidate for mapping %s — skipping review.",
                mapping.candidate_id,
            )
            continue
        review_tasks.append((mapping, candidate))

    if not review_tasks:
        return result, IncentiveReviewResults(entries=[])

    coroutines = [
        _review_single_mapping(mapping, candidate, agent)
        for mapping, candidate in review_tasks
    ]
    judge_responses: list[dict[str, Any]] = list(await asyncio.gather(*coroutines))

    # Build set of reviewed candidate IDs for tracking
    reviewed_ids: set[str] = {mapping.candidate_id for mapping, _ in review_tasks}

    # Apply judge decisions
    kept_mappings: list[DeepMapping] = []
    new_failed: list[FailedTarget] = list(result.failed_targets)
    review_entries: list[IncentiveReviewEntry] = []

    # First, keep any mappings that weren't reviewed (no matching candidate)
    for mapping in result.mappings:
        if mapping.candidate_id not in reviewed_ids:
            kept_mappings.append(mapping)

    # Process reviewed mappings
    for (mapping, candidate), response in zip(review_tasks, judge_responses):
        action = response.get("action", "keep")
        reason = response.get("reason", "")
        recommended_type = response.get("recommended_type")
        entry = IncentiveReviewEntry(
            candidate_id=mapping.candidate_id,
            claimed_incentive_type=(
                candidate.incentive_type.value
                if hasattr(candidate.incentive_type, "value")
                else str(candidate.incentive_type)
            ),
            action=action,
            recommended_type=recommended_type,
            reason=reason,
            final_action=action,
            min_motivation=min_motivation,
            motivation_strength=mapping.schemer_motivation.strength_of_motivation,
            agent_error=response.get("agent_error"),
            stderr=response.get("stderr", ""),
            exit_code=response.get("exit_code"),
            agent_message_count=response.get("agent_message_count"),
        )

        if action == "drop":
            logger.info(
                "Incentive review dropped %s: %s", mapping.candidate_id, reason,
            )
            entry.final_action = "drop"
            entry.final_reason = reason
            new_failed.append(FailedTarget(
                candidate_id=mapping.candidate_id,
                reason=f"Dropped by incentive review: {reason}",
            ))

        elif action == "fix" and recommended_type is not None:
            logger.info(
                "Incentive review fixed %s: %s -> %s (%s)",
                mapping.candidate_id, mapping.incentive_type, recommended_type, reason,
            )
            mapping.incentive_type = recommended_type  # type: ignore[assignment]
            entry.final_action = "fix"
            entry.final_reason = reason
            kept_mappings.append(mapping)

        else:
            # "keep" or unrecognized action — no changes
            entry.final_action = "keep"
            entry.final_reason = reason
            kept_mappings.append(mapping)
        review_entries.append(entry)

    # Apply min-motivation programmatic filter (after LLM review)
    if min_motivation:
        final_mappings: list[DeepMapping] = []
        for mapping in kept_mappings:
            if _meets_min_motivation(mapping, min_motivation):
                final_mappings.append(mapping)
            else:
                strength = mapping.schemer_motivation.strength_of_motivation
                logger.info(
                    "Min-motivation filter dropped %s: strength=%s < threshold=%s",
                    mapping.candidate_id, strength, min_motivation,
                )
                for entry in review_entries:
                    if entry.candidate_id == mapping.candidate_id:
                        entry.final_action = "drop"
                        entry.final_reason = (
                            f"Below min-motivation threshold: {strength} < {min_motivation}"
                        )
                new_failed.append(FailedTarget(
                    candidate_id=mapping.candidate_id,
                    reason=f"Below min-motivation threshold: {strength} < {min_motivation}",
                ))
        kept_mappings = final_mappings

    return (
        DeepMapResult(
            mappings=kept_mappings,
            failed_targets=new_failed,
        ),
        IncentiveReviewResults(entries=review_entries),
    )


def write_incentive_review_results(results: IncentiveReviewResults, path: Path) -> None:
    """Serialize incentive review results to YAML."""
    data = [entry.model_dump(exclude_none=True) for entry in results.entries]
    path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True, width=100)
    )


def load_incentive_review_results(path: Path) -> IncentiveReviewResults:
    """Read and validate incentive_review_results.yaml from path."""
    raw = yaml.safe_load(path.read_text())
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raw = [raw]
    entries = [IncentiveReviewEntry.model_validate(item) for item in raw]
    return IncentiveReviewResults(entries=entries)


def apply_incentive_review_results(
    result: DeepMapResult,
    review_results: IncentiveReviewResults,
    min_motivation: str | None = None,
) -> DeepMapResult:
    """Apply stored incentive review decisions to a DeepMapResult.

    Stored ``final_action`` is authoritative. Entries missing from the stored
    artifact are kept so a partial human-edited restart file cannot silently
    delete current mappings.
    """
    entries_by_candidate_id = {e.candidate_id: e for e in review_results.entries}
    kept_mappings: list[DeepMapping] = []
    failed_targets: list[FailedTarget] = list(result.failed_targets)

    for mapping in result.mappings:
        entry = entries_by_candidate_id.get(mapping.candidate_id)
        if entry is None:
            kept_mappings.append(mapping)
            continue

        if entry.final_action == "drop":
            failed_targets.append(FailedTarget(
                candidate_id=mapping.candidate_id,
                reason=f"Dropped by stored incentive review: {entry.final_reason or entry.reason}",
                stderr=entry.stderr,
                exit_code=entry.exit_code,
                agent_message_count=entry.agent_message_count,
            ))
            continue

        if entry.final_action == "fix" and entry.recommended_type is not None:
            mapping.incentive_type = entry.recommended_type  # type: ignore[assignment]
        kept_mappings.append(mapping)

    if min_motivation:
        final_mappings: list[DeepMapping] = []
        for mapping in kept_mappings:
            if _meets_min_motivation(mapping, min_motivation):
                final_mappings.append(mapping)
            else:
                strength = mapping.schemer_motivation.strength_of_motivation
                failed_targets.append(FailedTarget(
                    candidate_id=mapping.candidate_id,
                    reason=f"Below min-motivation threshold: {strength} < {min_motivation}",
                ))
        kept_mappings = final_mappings

    return DeepMapResult(mappings=kept_mappings, failed_targets=failed_targets)
