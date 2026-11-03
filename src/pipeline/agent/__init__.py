"""Agent interface and implementations."""

from pipeline.agent.interface import AgentInterface, AgentResult
from pipeline.agent.claude_agent import ClaudeAgent

__all__ = ["AgentInterface", "AgentResult", "ClaudeAgent"]
