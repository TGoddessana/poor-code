"""Live wiring test for Ollama Cloud. Skipped unless OLLAMA_API_KEY is set.
Costs a few tokens; run sparingly. Do NOT add to CI by default.

Model is taken from POOR_CODE_TEST_MODEL (test-only knob); no production
default exists — the app forces the user to pick a model via /login.
"""
import os

import pytest

from poor_code.provider.providers import ollama_cloud


pytestmark = pytest.mark.skipif(
    not (os.environ.get("OLLAMA_API_KEY") and os.environ.get("POOR_CODE_TEST_MODEL")),
    reason="OLLAMA_API_KEY and POOR_CODE_TEST_MODEL must be set",
)


@pytest.mark.asyncio
async def test_one_round_trip():
    llm = ollama_cloud.client(
        model=os.environ["POOR_CODE_TEST_MODEL"],
        api_key=os.environ["OLLAMA_API_KEY"],
    )
    events = []
    async for ev in llm.stream(
        messages=[{"role": "user", "content": "say hi in one word"}],
        tools=[],
    ):
        events.append(ev)
    kinds = [type(e).__name__ for e in events]
    assert "TextDelta" in kinds
    assert kinds[-1] == "FinishedReason"
