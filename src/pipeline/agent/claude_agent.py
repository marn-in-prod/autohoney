"""Claude Agent SDK implementation of AgentInterface."""

from __future__ import annotations

import shutil
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    CLINotFoundError,
    ProcessError,
    CLIJSONDecodeError,
    query,
)

from pipeline.agent.interface import AgentInterface, AgentResult
from pipeline.config import PipelineConfig


class ClaudeAgent(AgentInterface):
    """Agent implementation using the Claude Agent SDK."""

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig()

    async def run(
        self,
        prompt: str,
        cwd: str,
        output_schema: dict[str, Any] | None = None,
        system_prompt: str | None = None,
    ) -> AgentResult:
        """Run a prompt using claude-agent-sdk query()."""
        stderr_lines: list[str] = []
        options = ClaudeAgentOptions(
            cli_path=self.config.agent_cli_path or shutil.which("claude"),
            model=self.config.agent_model,
            max_turns=self.config.agent_max_turns,
            max_budget_usd=self.config.agent_max_budget_usd,
            permission_mode=self.config.agent_permission_mode,  # type: ignore[arg-type]
            allowed_tools=self.config.agent_allowed_tools,
            cwd=cwd,
            stderr=stderr_lines.append,
        )

        if system_prompt:
            options.system_prompt = system_prompt

        if output_schema:
            options.output_format = {
                "type": "json_schema",
                "schema": output_schema,
            }

        try:
            result_message: ResultMessage | None = None
            messages: list[Any] = []

            async for message in query(prompt=prompt, options=options):
                messages.append(message)
                if isinstance(message, ResultMessage):
                    result_message = message

            if result_message is None:
                return AgentResult(
                    success=False,
                    error="No ResultMessage received from agent",
                    stderr="\n".join(stderr_lines),
                    message_count=len(messages),
                )

            if result_message.is_error:
                return AgentResult(
                    success=False,
                    error=result_message.result or "Agent returned an error",
                    num_turns=result_message.num_turns,
                    session_id=result_message.session_id,
                    cost_usd=result_message.total_cost_usd,
                    stderr="\n".join(stderr_lines),
                    message_count=len(messages),
                )

            raw_text = result_message.result or ""

            return AgentResult(
                success=True,
                structured_output=result_message.structured_output,
                raw_text=raw_text,
                num_turns=result_message.num_turns,
                session_id=result_message.session_id,
                cost_usd=result_message.total_cost_usd,
                stderr="\n".join(stderr_lines),
                message_count=len(messages),
            )

        except CLINotFoundError as e:
            return AgentResult(success=False, error=f"Claude CLI not found: {e}")
        except ProcessError as e:
            stderr = "\n".join(stderr_lines) or (e.stderr or "")
            return AgentResult(
                success=False,
                error=f"Process error: {e}",
                stderr=stderr,
                exit_code=e.exit_code,
                message_count=len(messages) if "messages" in locals() else 0,
            )
        except CLIJSONDecodeError as e:
            return AgentResult(success=False, error=f"JSON decode error: {e}")
