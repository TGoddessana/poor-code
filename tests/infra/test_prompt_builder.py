from __future__ import annotations

import pytest

from poor_code.infra.context_loader import LoadedContext
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.system_prompt import SystemPrompt


def _ctx(user_block: str = "", system_block: str = "") -> LoadedContext:
    return LoadedContext(user_block=user_block, system_block=system_block, sources=())


def _sys(text: str = "SYS") -> SystemPrompt:
    return SystemPrompt(text=text, static="", dynamic="")


def test_empty_history_raises():
    with pytest.raises(ValueError, match="at least one message"):
        PromptBuilder().build([], _ctx(), _sys())


def test_first_message_is_system():
    history = [{"role": "user", "content": "hi"}]
    out = PromptBuilder().build(history, _ctx(), _sys(text="SYSTEM!"))
    assert out[0] == {"role": "system", "content": "SYSTEM!"}


def test_prepends_user_and_system_block_to_first_user_message():
    history = [{"role": "user", "content": "hi"}]
    ctx = _ctx(user_block="USER_CTX\n", system_block="SYS_CTX\n")
    out = PromptBuilder().build(history, ctx, _sys())
    assert out[1] == {"role": "user", "content": "USER_CTX\nSYS_CTX\nhi"}


def test_prepend_only_to_first_user_message():
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ]
    ctx = _ctx(user_block="CTX\n")
    out = PromptBuilder().build(history, ctx, _sys())
    assert out[1]["content"] == "CTX\nfirst"
    assert out[3]["content"] == "second"


def test_history_is_not_mutated():
    history = [{"role": "user", "content": "hi"}]
    original = [dict(m) for m in history]
    PromptBuilder().build(history, _ctx(user_block="X"), _sys())
    assert history == original


def test_preserves_tool_call_messages_verbatim():
    history = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "read", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
    ]
    out = PromptBuilder().build(history, _ctx(), _sys())
    assert out[2]["tool_calls"][0]["function"]["name"] == "read"
    assert out[3]["role"] == "tool"
    assert out[3]["tool_call_id"] == "c1"


def test_empty_blocks_do_not_alter_first_user():
    history = [{"role": "user", "content": "hi"}]
    out = PromptBuilder().build(history, _ctx(), _sys())
    assert out[1]["content"] == "hi"
