"""Live wiring test for Ollama Cloud. Skipped unless OLLAMA_API_KEY is set.
Costs a few tokens; run sparingly. Do NOT add to CI by default.
"""
import os

import pytest

from poor_code.provider.providers import ollama_cloud


pytestmark = pytest.mark.skipif(
    not os.environ.get("OLLAMA_API_KEY"),
    reason="OLLAMA_API_KEY not set",
)


@pytest.mark.asyncio
async def test_one_round_trip():
    model = os.environ.get("POOR_CODE_MODEL", "qwen2.5-coder:7b")
    llm = ollama_cloud.client(model=model)
    events = []
    async for ev in llm.stream(
        messages=[{"role": "user", "content": "say hi in one word"}],
        tools=[],
    ):
        events.append(ev)
    kinds = [type(e).__name__ for e in events]
    assert "TextDelta" in kinds
    assert kinds[-1] == "FinishedReason"
