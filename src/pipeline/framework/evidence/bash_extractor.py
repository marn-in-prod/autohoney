from inspect_ai.model import ChatMessageAssistant, ChatMessageTool
from inspect_ai.solver import TaskState


def extract_bash_evidence(state: TaskState) -> str:
    bash_calls = {}
    for message in state.messages:
        if isinstance(message, ChatMessageAssistant) and message.tool_calls:
            for tool_call in message.tool_calls:
                if tool_call.function == "bash":
                    bash_calls[tool_call.id] = tool_call.arguments.get("cmd", "")

    tool_responses = {}
    for message in state.messages:
        if isinstance(message, ChatMessageTool):
            if message.function == "bash" and message.tool_call_id:
                tool_responses[message.tool_call_id] = message.content or ""

    if not bash_calls:
        return ""

    lines = ["## BASH COMMANDS:", ""]
    for i, (call_id, cmd) in enumerate(bash_calls.items(), 1):
        response = tool_responses.get(call_id, "")
        lines.append(f"### Command {i}:")
        lines.append("```bash")
        lines.append(cmd)
        lines.append("```")
        lines.append("**Response:**")
        lines.append("```")
        if len(response) > 2000:
            response = response[:2000] + f"\n... [truncated {len(response) - 2000} chars]"
        lines.append(response if response else "(no output)")
        lines.append("```")
        lines.append("")

    return "\n".join(lines)
