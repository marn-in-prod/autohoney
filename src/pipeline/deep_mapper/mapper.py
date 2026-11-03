"""Deep mapper: detailed investigation of honeypot candidate targets."""

from __future__ import annotations

from pathlib import Path

import yaml

from pipeline.agent.interface import AgentInterface
from pipeline.agent.claude_agent import ClaudeAgent
from pipeline.config import PipelineConfig
from pipeline.deep_mapper.models import DeepMapping, DeepMapResult, FailedTarget
from pipeline.scanner.models import Candidate


PROMPT_PATH = Path(__file__).parent / "prompts" / "deep_map_target.md"


async def deep_map_targets(
    candidates: list[Candidate],
    codebase_path: str,
    config: PipelineConfig | None = None,
    agent: AgentInterface | None = None,
) -> DeepMapResult:
    """Run deep mapping on each candidate target.

    One LLM call per candidate. Returns DeepMapResult with mappings and failed targets.

    Args:
        candidates: List of candidates to deep-map.
        codebase_path: Path to the codebase root.
        config: Pipeline configuration.
        agent: Agent to use (defaults to ClaudeAgent).

    Returns:
        DeepMapResult with mappings and failed targets.
    """
    config = config or PipelineConfig()
    agent = agent or ClaudeAgent(config)

    prompt_template = PROMPT_PATH.read_text()
    schema = DeepMapping.model_json_schema()

    mappings: list[DeepMapping] = []
    failed_targets: list[FailedTarget] = []

    for candidate in candidates:
        candidate_yaml = yaml.dump(
            candidate.model_dump(exclude_none=True),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=100,
        )
        prompt = prompt_template.replace("{candidate_yaml}", candidate_yaml)

        try:
            result = await agent.run(
                prompt=prompt,
                cwd=codebase_path,
                output_schema=schema,
            )

            if not result.success:
                failed_targets.append(FailedTarget(
                    candidate_id=candidate.id,
                    reason=f"Agent failed: {result.error}",
                    stderr=result.stderr,
                    exit_code=result.exit_code,
                    agent_message_count=result.message_count,
                ))
                continue

            mapping = DeepMapping.model_validate(result.structured_output)

            if not mapping.code_trace:
                failed_targets.append(FailedTarget(
                    candidate_id=candidate.id,
                    reason="Agent returned no code trace entries",
                ))
                continue

            mappings.append(mapping)

        except Exception as e:
            failed_targets.append(FailedTarget(
                candidate_id=candidate.id,
                reason=f"Exception during deep mapping: {e}",
            ))

    # Sort mappings by schemer motivation strength (strongest first)
    motivation_order = {"very high": 0, "high": 1, "moderate": 2, "low": 3}
    mappings.sort(
        key=lambda m: motivation_order.get(m.schemer_motivation.strength_of_motivation.lower(), 2)
    )

    return DeepMapResult(mappings=mappings, failed_targets=failed_targets)


def write_deep_map_yaml(result: DeepMapResult, output_path: Path) -> None:
    """Write deep map result to YAML file."""
    data = result.model_dump(exclude_none=True)
    output_path.write_text(
        yaml.dump(
            data,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=100,
        )
    )


def read_deep_map_yaml(path: Path) -> DeepMapResult:
    """Read deep map result from YAML file."""
    data = yaml.safe_load(path.read_text())
    return DeepMapResult.model_validate(data)
