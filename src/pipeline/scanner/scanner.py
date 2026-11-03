"""Scanner module — scans a codebase to identify honeypot candidate targets."""

from pathlib import Path

import yaml

from pipeline.agent.interface import AgentInterface
from pipeline.agent.claude_agent import ClaudeAgent
from pipeline.scanner.models import ScanConfig, ScanResult
from pipeline.config import PipelineConfig


PROMPT_PATH = Path(__file__).parent / "prompts" / "scan_codebase.md"


async def scan_codebase(
    scan_config: ScanConfig,
    config: PipelineConfig | None = None,
    agent: AgentInterface | None = None,
    guidance: str = "",
) -> ScanResult:
    """Scan a codebase and return identified candidate targets.

    Args:
        scan_config: Configuration specifying what and where to scan.
        config: Pipeline configuration. Uses defaults if not provided.
        agent: Agent to use. Creates a ClaudeAgent if not provided.

    Returns:
        ScanResult with identified candidates.
    """
    config = config or PipelineConfig()
    agent = agent or ClaudeAgent(config)

    prompt_template = PROMPT_PATH.read_text()

    # Build scope instruction
    if scan_config.focus:
        scope_instruction = (
            f"Focus specifically on: {scan_config.focus}\n"
            "Skip broad exploration and go directly to this feature."
        )
    elif scan_config.scope:
        scope_instruction = f"Focus your scan on: {scan_config.scope}"
    else:
        scope_instruction = "Scan the entire codebase."

    # Build categories list
    categories_text = "\n".join(f"- {cat}" for cat in scan_config.categories)

    prompt = prompt_template.replace("{scope_instruction}", scope_instruction)
    prompt = prompt.replace("{categories}", categories_text)

    if guidance:
        prompt += (
            "\n\n---\nREVIEWER GUIDANCE (apply to this run):\n"
            f"{guidance}\n"
        )

    schema = ScanResult.model_json_schema()

    result = await agent.run(
        prompt=prompt,
        cwd=scan_config.codebase_path,
        output_schema=schema,
    )

    if not result.success:
        raise RuntimeError(f"Scanner agent failed: {result.error}")

    scan_result = ScanResult.model_validate(result.structured_output)

    # Sort candidates: strong first, then moderate, then weak
    priority_order = {"strong": 0, "moderate": 1, "weak": 2}
    scan_result.candidates.sort(key=lambda c: priority_order.get(c.priority, 1))

    return scan_result


def write_scan_yaml(result: ScanResult, output_path: Path) -> None:
    """Write scan result to YAML file."""
    data = result.model_dump(exclude_none=True)
    output_path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True, width=100)
    )


def read_scan_yaml(path: Path) -> ScanResult:
    """Read scan result from YAML file."""
    data = yaml.safe_load(path.read_text())
    return ScanResult.model_validate(data)
