"""poor-code entrypoint.

Builds the real Agent (LLMClient + ToolRegistry) and hands it to the
Textual app. Fails fast at startup if OLLAMA_API_KEY is missing.
"""
from __future__ import annotations

import os
import sys

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.auth import MissingApiKey
from poor_code.provider.providers import ollama_cloud


DEFAULT_MODEL = os.environ.get("POOR_CODE_MODEL", "qwen2.5-coder:7b")


def main() -> None:
    try:
        llm = ollama_cloud.client(model=DEFAULT_MODEL)
    except MissingApiKey as e:
        print(f"error: {e}", file=sys.stderr)
        print(
            "Set OLLAMA_API_KEY in your environment, or override the model with POOR_CODE_MODEL.",
            file=sys.stderr,
        )
        sys.exit(2)

    tools = ToolRegistry([ReadTool()])
    PoorCodeApp(agent=Agent(llm=llm, tools=tools)).run()
