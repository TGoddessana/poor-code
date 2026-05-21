"""PromptBuilder — pure function that produces the per-turn API messages.

Combines the conversation history (user/assistant/tool) with the transient
SystemPrompt and LoadedContext into a list[dict] ready for LLMClient.stream().
self.history is never mutated; only the first user message gets the context
prepended.
"""
from __future__ import annotations

from typing import Any

from poor_code.infra.context_loader import LoadedContext
from poor_code.infra.system_prompt import SystemPrompt


class PromptBuilder:
    def build(
        self,
        history: list[dict[str, Any]],
        ctx: LoadedContext,
        system: SystemPrompt,
    ) -> list[dict[str, Any]]:
        if not history:
            raise ValueError("history must contain at least one message")

        prepend = ctx.user_block + ctx.system_block

        out: list[dict[str, Any]] = [
            {"role": "system", "content": system.text}
        ]
        injected = False
        for msg in history:
            if not injected and msg.get("role") == "user":
                copy = dict(msg)
                copy["content"] = prepend + msg.get("content", "")
                out.append(copy)
                injected = True
            else:
                out.append(dict(msg))
        return out
