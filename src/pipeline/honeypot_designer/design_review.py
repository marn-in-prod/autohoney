"""Design quality review gate — checks redundancy, description sanity, and design quality."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from pipeline.agent.interface import AgentInterface, unwrap_structured_output
from pipeline.honeypot_designer.models import DesignResult

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "design_review.md"

# JSON schema for the LLM judge response
_JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "design_id": {"type": "string"},
                    "redundant_with": {"type": ["string", "null"]},
                    "redundancy_reason": {"type": ["string", "null"]},
                    "scheming_description_verdict": {
                        "type": "string",
                        "enum": ["pass", "rewrite"],
                    },
                    "rewritten_scheming_description": {"type": ["string", "null"]},
                    "aligned_description_verdict": {
                        "type": "string",
                        "enum": ["pass", "rewrite"],
                    },
                    "rewritten_aligned_description": {"type": ["string", "null"]},
                    "quality_verdict": {
                        "type": "string",
                        "enum": ["strong", "acceptable", "weak"],
                    },
                    "observable_signal_verdict": {
                        "type": "string",
                        "enum": ["observable", "not_observable"],
                    },
                    "observable_signal_reason": {"type": "string"},
                    "quality_explanation": {"type": "string"},
                },
                "required": [
                    "design_id",
                    "redundant_with",
                    "redundancy_reason",
                    "scheming_description_verdict",
                    "rewritten_scheming_description",
                    "aligned_description_verdict",
                    "rewritten_aligned_description",
                    "quality_verdict",
                    "observable_signal_verdict",
                    "observable_signal_reason",
                    "quality_explanation",
                ],
                "additionalProperties": False,
            },
        },
        "messages": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["verdicts", "messages"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class DesignReviewVerdict(BaseModel):
    """Review verdict for a single design."""

    design_id: str
    redundant_with: str | None = None
    redundancy_reason: str | None = None
    scheming_description_verdict: Literal["pass", "rewrite"]
    rewritten_scheming_description: str | None = None
    aligned_description_verdict: Literal["pass", "rewrite"]
    rewritten_aligned_description: str | None = None
    quality_verdict: Literal["strong", "acceptable", "weak"]
    observable_signal_verdict: Literal["observable", "not_observable"]
    observable_signal_reason: str
    quality_explanation: str


class DesignReviewResult(BaseModel):
    """Complete output of the design review gate."""

    verdicts: list[DesignReviewVerdict]
    messages: list[str]
    agent_error: str | None = None
    stderr: str = ""
    exit_code: int | None = None
    agent_message_count: int | None = None

    def apply(self, design_result: DesignResult) -> DesignResult:
        """Apply sabotage description rewrites back to the DesignResult's designs.

        Only handles rewrites. Redundancy (verdicts with redundant_with set)
        and weak-design flags are advisory -- they are surfaced via ``messages``
        for the CLI to print, and the user decides manually whether to remove
        designs. This matches QC_MASTER.md which says "flag the weaker one for
        removal (user confirms)."

        Returns the modified DesignResult (same object, mutated).
        """
        designs_by_id = {d.id: d for d in design_result.honeypot_designs}
        for verdict in self.verdicts:
            design = designs_by_id.get(verdict.design_id)
            if design is None:
                continue
            if (
                verdict.scheming_description_verdict == "rewrite"
                and verdict.rewritten_scheming_description
            ):
                design.what_scheming_looks_like = verdict.rewritten_scheming_description
            if (
                verdict.aligned_description_verdict == "rewrite"
                and verdict.rewritten_aligned_description
            ):
                design.what_aligned_looks_like = verdict.rewritten_aligned_description
        return design_result


class CandidateDesignReviewResult(BaseModel):
    """Persisted design review result for one candidate."""

    candidate_id: str
    design_ids: list[str]
    review: DesignReviewResult
    agent_error: str | None = None
    stderr: str = ""
    exit_code: int | None = None
    agent_message_count: int | None = None


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------


def _serialize_designs_to_yaml(design_result: DesignResult) -> str:
    """Serialize all designs to a YAML string for the LLM prompt."""
    designs_data = []
    for d in design_result.honeypot_designs:
        entry: dict[str, Any] = {
            "id": d.id,
            "quality": d.quality,
            "design_type": d.design_type,
            "incentive_type": _literal_value(d.incentive_type),
            "complexity_level": d.complexity_level,
            "planted_modification": {
                "description": d.planted_modification.description,
                "files_modified": [
                    {"file": f.file, "change": f.change}
                    for f in d.planted_modification.files_modified
                ],
                "why_it_could_legitimately_exist": d.planted_modification.why_it_could_legitimately_exist,
                "what_a_schemer_would_exploit": d.planted_modification.what_a_schemer_would_exploit,
            },
            "what_scheming_looks_like": d.what_scheming_looks_like,
            "what_aligned_looks_like": d.what_aligned_looks_like,
            "scheming_signal": d.scheming_signal,
            "scheming_signal_is_observable": d.scheming_signal_is_observable,
        }
        designs_data.append(entry)
    return yaml.dump(
        designs_data,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )


def _literal_value(value: Any) -> Any:
    """Return enum values while leaving already-literal values unchanged."""
    return value.value if hasattr(value, "value") else value


def write_design_review_results(results: list[CandidateDesignReviewResult], path: Path) -> None:
    """Serialize design review results to YAML."""
    data = [r.model_dump(exclude_none=True) for r in results]
    path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True, width=100)
    )


def load_design_review_results(path: Path) -> list[CandidateDesignReviewResult]:
    """Read and validate design_review_results.yaml from path."""
    raw = yaml.safe_load(path.read_text())
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raw = [raw]
    return [CandidateDesignReviewResult.model_validate(item) for item in raw]


def apply_design_review_results(
    design_results: list[DesignResult],
    review_results: list[CandidateDesignReviewResult],
) -> list[DesignResult]:
    """Apply stored design review verdicts/messages to current design results."""
    review_by_candidate_id = {r.candidate_id: r for r in review_results}
    for design_result in design_results:
        stored = review_by_candidate_id.get(design_result.candidate_id)
        if stored is None:
            continue
        stored.review.apply(design_result)
    return design_results


# ---------------------------------------------------------------------------
# Main review function
# ---------------------------------------------------------------------------


async def review_designs(
    design_result: DesignResult,
    agent: AgentInterface | None = None,
) -> DesignReviewResult:
    """Review all designs in a DesignResult for redundancy, description quality, and strength.

    One LLM call reviews all designs together (not per-design). The function:
    1. Serializes all honeypot designs to YAML
    2. Calls the LLM judge with the full set
    3. Parses the judge's response into DesignReviewResult

    The caller is responsible for applying the result via ``result.apply(design_result)``
    and printing ``result.messages``.

    Args:
        design_result: The DesignResult containing all designs for one candidate.
        agent: Agent to use for the LLM call. Creates a ClaudeAgent if None.

    Returns:
        DesignReviewResult with verdicts and advisory messages.
    """
    from pipeline.agent.claude_agent import ClaudeAgent

    agent = agent or ClaudeAgent()

    designs_yaml = _serialize_designs_to_yaml(design_result)

    prompt_template = PROMPT_PATH.read_text()
    prompt = prompt_template.format(designs_yaml=designs_yaml)

    result = await agent.run(
        prompt=prompt,
        cwd=".",
        output_schema=_JUDGE_SCHEMA,
    )

    if not result.success or result.structured_output is None:
        logger.warning(
            "Design review judge failed for candidate %s: %s — returning no-op result.",
            design_result.candidate_id,
            result.error,
        )
        # Fail-open: if the judge errors, return a no-op result (all pass, no
        # rewrites). Design review is advisory — we don't want a judge failure
        # to block the pipeline.
        review_result = DesignReviewResult(
            verdicts=[
                DesignReviewVerdict(
                    design_id=d.id,
                    scheming_description_verdict="pass",
                    aligned_description_verdict="pass",
                    quality_verdict="acceptable",
                    observable_signal_verdict="observable",
                    observable_signal_reason=f"Design review judge failed ({result.error}); defaulting to pass.",
                    quality_explanation=f"Design review judge failed ({result.error}); defaulting to pass.",
                )
                for d in design_result.honeypot_designs
            ],
            messages=[
                f"[WARN] Design review judge failed: {result.error}. All designs passed by default."
            ],
        )
        review_result.agent_error = result.error
        review_result.stderr = result.stderr
        review_result.exit_code = result.exit_code
        review_result.agent_message_count = result.message_count
        return review_result

    out = unwrap_structured_output(result.structured_output, {"verdicts", "messages"})

    verdicts_raw = out.get("verdicts", [])
    messages = out.get("messages", [])

    verdicts = [DesignReviewVerdict.model_validate(v) for v in verdicts_raw]

    return DesignReviewResult(verdicts=verdicts, messages=messages)
