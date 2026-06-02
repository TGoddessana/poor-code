from poor_code.provider.protocols.openai_chat import (
    OpenAICompatibleChat, _repair_args,
)


def test_repair_valid_args_preserved():
    assert _repair_args('{"path":"a"}') == '{"path":"a"}'


def test_repair_concatenated_takes_first_object():
    assert _repair_args('{"path":"a"}{"path":"b"}') == '{"path":"a"}'


def test_repair_truncated_falls_back_to_empty():
    assert _repair_args('{"path":"a') == "{}"


def _assistant_msg(args: str):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "read", "arguments": args}}]}


def test_build_body_repairs_broken_tool_call_args():
    msgs = [_assistant_msg('{"path":"a"}{"path":"b"}')]
    body = OpenAICompatibleChat().build_body(messages=msgs, tools=[], model="m")
    assert body["messages"][0]["tool_calls"][0]["function"]["arguments"] == '{"path":"a"}'


def test_build_body_preserves_valid_args_and_does_not_mutate_input():
    msgs = [_assistant_msg('{"path":"a"}')]
    body = OpenAICompatibleChat().build_body(messages=msgs, tools=[], model="m")
    assert body["messages"][0]["tool_calls"][0]["function"]["arguments"] == '{"path":"a"}'
    # original input object untouched
    assert msgs[0]["tool_calls"][0]["function"]["arguments"] == '{"path":"a"}'
