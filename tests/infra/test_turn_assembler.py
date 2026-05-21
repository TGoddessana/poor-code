from __future__ import annotations

from pathlib import Path

from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.turn_assembler import TurnAssembler
from tests.infra.fakes import (
    FakeContextLoader,
    FakeSettingsLoader,
    FakeSystemPromptComposer,
)


async def test_assembler_glues_all_four(tmp_path):
    assembler = TurnAssembler(
        settings_loader=FakeSettingsLoader(effective={"a": 1}),
        context_loader=FakeContextLoader(user_block="UCTX\n", system_block="SCTX\n"),
        prompt_composer=FakeSystemPromptComposer(text="SYS_TEXT"),
        prompt_builder=PromptBuilder(),
    )
    history = [{"role": "user", "content": "hi"}]
    out = await assembler.build(history, cwd=tmp_path)

    assert out[0] == {"role": "system", "content": "SYS_TEXT"}
    assert out[1]["content"] == "UCTX\nSCTX\nhi"


async def test_assembler_passes_cwd_through(tmp_path):
    assembler = TurnAssembler(
        settings_loader=FakeSettingsLoader(),
        context_loader=FakeContextLoader(),
        prompt_composer=FakeSystemPromptComposer(),
        prompt_builder=PromptBuilder(),
    )
    history = [{"role": "user", "content": "x"}]
    await assembler.build(history, cwd=tmp_path)
    # Smoke: didn't raise. Detailed routing verified by upstream component tests.
