import re

from inspect_ai.solver import TaskState


def extract_cot_evidence(state: TaskState, message_cutoff: int | None = None) -> str:
    """Extract chain-of-thought reasoning from TaskState messages.

    Handles three CoT formats:
    1. ContentReasoning objects (OpenAI o-series, Anthropic extended thinking, etc.)
    2. Text-embedded <think> blocks (minimax, deepseek, etc.)
    3. Dict-format content blocks (from JSON deserialization)

    Empty or looping <think> tags (e.g. minimax's infinite-loop bug where the
    model emits hundreds of <think internal="..."> tags with no content) are
    filtered out.

    Args:
        state: The TaskState containing message history.
        message_cutoff: If set, only messages[:message_cutoff] are scanned.
            Used to exclude eval-awareness turn messages from CoT evidence.
    """
    try:
        from inspect_ai._util.content import ContentReasoning
    except ImportError:
        ContentReasoning = None

    reasoning_parts = []
    any_unavailable = False

    messages = state.messages
    if message_cutoff is not None:
        messages = messages[:message_cutoff]
    for message in messages:
        if message.role != "assistant":
            continue
        content_list = message.content if isinstance(message.content, list) else [message.content]
        for content in content_list:
            # --- Format 1: structured ContentReasoning ---
            if ContentReasoning is not None and isinstance(content, ContentReasoning):
                if content.redacted:
                    # Try summary fallback before marking unavailable
                    summary = getattr(content, "summary", None)
                    if summary and summary.strip() and not _is_encrypted(summary):
                        reasoning_parts.append(summary)
                    else:
                        any_unavailable = True
                elif content.reasoning and content.reasoning.strip():
                    if _is_encrypted(content.reasoning):
                        # Try summary fallback before marking unavailable
                        summary = getattr(content, "summary", None)
                        if summary and summary.strip() and not _is_encrypted(summary):
                            reasoning_parts.append(summary)
                        else:
                            any_unavailable = True
                    else:
                        # Skip degenerate blocks — models sometimes loop
                        # and produce 200K+ of garbage in one reasoning block
                        if len(content.reasoning) > 30_000:
                            continue
                        cleaned = _clean_reasoning(content.reasoning)
                        if cleaned:
                            reasoning_parts.append(cleaned)
            # --- Format 2: dict-format content blocks (JSON deserialization) ---
            elif isinstance(content, dict):
                # Handle "thinking" key (some models use this instead of "reasoning")
                if content.get("type") == "thinking" and content.get("thinking"):
                    thinking_text = content["thinking"]
                    if not _is_encrypted(thinking_text) and len(thinking_text) <= 30_000:
                        cleaned = _clean_reasoning(thinking_text)
                        if cleaned:
                            reasoning_parts.append(cleaned)
                elif content.get("type") == "reasoning" and content.get("reasoning"):
                    if content.get("redacted"):
                        summary = content.get("summary")
                        if summary and summary.strip() and not _is_encrypted(summary):
                            reasoning_parts.append(summary)
                        else:
                            any_unavailable = True
                    else:
                        reasoning_text = content["reasoning"]
                        if _is_encrypted(reasoning_text):
                            summary = content.get("summary")
                            if summary and summary.strip() and not _is_encrypted(summary):
                                reasoning_parts.append(summary)
                            else:
                                any_unavailable = True
                        elif len(reasoning_text) <= 30_000:
                            cleaned = _clean_reasoning(reasoning_text)
                            if cleaned:
                                reasoning_parts.append(cleaned)
                elif "text" in content:
                    extracted = _extract_think_blocks(content["text"])
                    reasoning_parts.extend(extracted)
            # --- Format 3: text-embedded <think> blocks ---
            else:
                text = content if isinstance(content, str) else getattr(content, "text", None)
                if text:
                    extracted = _extract_think_blocks(text)
                    reasoning_parts.extend(extracted)

    if reasoning_parts:
        text = "\n\n---\n\n".join(reasoning_parts)
        if len(text) > 50_000:
            text = text[:50_000] + "\n\n[TRUNCATED]"
        return f"## CHAIN-OF-THOUGHT REASONING:\n\n{text}"
    elif any_unavailable:
        return (
            "## REASONING STATUS: Not Available\n\n"
            "The model's reasoning was redacted or encrypted by the provider."
        )
    else:
        return (
            "## REASONING STATUS: Not Available\n\n"
            "The model does not support chain-of-thought reasoning, "
            "or the provider did not include it."
        )


def _clean_reasoning(text: str) -> str:
    """Remove tool call XML and code execution artifacts from reasoning text."""
    # Remove tool_call XML blocks
    text = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL)
    text = re.sub(r"<arg_key>.*?</arg_key>", "", text, flags=re.DOTALL)
    text = re.sub(r"<arg_value>.*?</arg_value>", "", text, flags=re.DOTALL)
    # Remove fenced code blocks that look like tool execution
    text = re.sub(r"```(?:bash|python|sh)?\n.*?```", "", text, flags=re.DOTALL)
    # Clean up excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_think_blocks(text: str) -> list[str]:
    """Extract non-empty content from <think ...>...</think> text blocks.

    Filters out empty or near-empty blocks (e.g. minimax's looping bug where
    the model emits <think internal="InJlYXNvbmluZyI="> with no content).
    """
    parts = re.findall(r"<think[^>]*>(.*?)</think>", text, re.DOTALL)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 20]


def _is_encrypted(text: str) -> bool:
    if not text or len(text) < 50:
        return False
    if text.startswith("gAAAAA"):
        return True
    non_b64 = re.sub(r"[A-Za-z0-9+/=_-]", "", text)
    if len(non_b64) < len(text) * 0.05 and len(text) > 500:
        return True
    return False
