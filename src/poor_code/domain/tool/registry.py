"""ToolRegistry — maps tool ids to Tool instances, emits the OpenAI-format
function-tool schema list that `LLMClient.stream(tools=...)` consumes.
"""
from __future__ import annotations

from typing import Any

from poor_code.domain.tool.base import Tool


class DuplicateToolId(ValueError):
    def __init__(self, tool_id: str) -> None:
        super().__init__(f"duplicate tool id: {tool_id!r}")
        self.tool_id = tool_id


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools:
            if t.id in self._tools:
                raise DuplicateToolId(t.id)
            self._tools[t.id] = t

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.id,
                    "description": t.description,
                    "parameters": t.params.model_json_schema(),
                },
            }
            for t in self._tools.values()
        ]
