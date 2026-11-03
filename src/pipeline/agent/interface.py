"""Abstract agent interface for the honeypot generation pipeline."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class AgentResult:
    """Result from an agent invocation."""

    success: bool
    structured_output: Any = None
    raw_text: str = ""
    num_turns: int = 0
    session_id: str = ""
    cost_usd: float | None = None
    error: str | None = None
    stderr: str = ""
    exit_code: int | None = None
    message_count: int = 0

    def parse_json(self) -> dict | list | None:
        """Parse structured_output as JSON if it's a string."""
        if self.structured_output is None:
            return None
        if isinstance(self.structured_output, str):
            return json.loads(self.structured_output)
        return self.structured_output


def unwrap_structured_output(structured_output: Any, expected_keys: set[str]) -> Any:
    """Return schema payload from common Claude SDK structured-output envelopes."""
    if isinstance(structured_output, str):
        structured_output = json.loads(structured_output)
    if not isinstance(structured_output, dict):
        return structured_output
    if expected_keys.intersection(structured_output):
        return structured_output
    for key in ("response", "output", "result"):
        value = structured_output.get(key)
        if isinstance(value, dict) and expected_keys.intersection(value):
            return value
    return structured_output


class AgentInterface(ABC):
    """Abstract interface for coding agents used in the pipeline.

    Implementations should wrap a specific agent SDK (e.g., claude-agent-sdk)
    and provide a uniform interface for running prompts with structured output.
    """

    @abstractmethod
    async def run(
        self,
        prompt: str,
        cwd: str,
        output_schema: dict[str, Any] | None = None,
        system_prompt: str | None = None,
    ) -> AgentResult:
        """Run the agent with a prompt and return structured output.

        Args:
            prompt: The task prompt for the agent.
            cwd: Working directory for the agent.
            output_schema: Optional JSON Schema for structured output.
            system_prompt: Optional system prompt override.

        Returns:
            AgentResult with structured output and metadata.
        """
        ...
