"""TextToolParser: text-based tool calling fallback.

When a model does not support OpenAI function calling, this parser
extracts tool invocations from plain-text output.
"""

from __future__ import annotations

import json
import re
from typing import Any

_TOOL_OPEN = "<tool_call>"
_TOOL_CLOSE = "</tool_call>"

_PATTERN = re.compile(
    re.escape(_TOOL_OPEN)
    + r"\s*\n(\w+)\s*\n(\{.*?\})\s*\n"
    + re.escape(_TOOL_CLOSE),
    re.DOTALL,
)


class TextToolParser:
    """Parse tool calls from text output."""

    _counter = 0

    def parse(self, text: str) -> list[dict[str, Any]]:
        """Extract tool calls from model text output."""
        calls: list[dict[str, Any]] = []
        for m in _PATTERN.finditer(text):
            name = m.group(1)
            raw_args = m.group(2)
            try:
                json.loads(raw_args)
            except json.JSONDecodeError:
                continue
            TextToolParser._counter += 1
            calls.append({
                "id": f"text_call_{TextToolParser._counter}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": raw_args,
                },
            })
        return calls


TEXT_TOOL_SYSTEM_PROMPT = (
    "If function calling is not available, use this text format to call tools:\n\n"
    "<tool_call>\n"
    "tool_name\n"
    '{{"arg1": "value1"}}\n'
    "</tool_call>\n\n"
    "Available tools: read_file, write_file, edit_file, run_command.\n"
    "Put ONE tool call per block. Write normal text outside these blocks."
)
