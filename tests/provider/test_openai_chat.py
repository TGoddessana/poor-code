from poor_code.provider.protocols.openai_chat import OpenAIChat


def test_build_body_minimal():
    proto = OpenAIChat()
    body = proto.build_body(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="qwen2.5-coder:7b",
    )
    assert body == {
        "model": "qwen2.5-coder:7b",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }


def test_build_body_with_tools_includes_tools_key():
    proto = OpenAIChat()
    tools_schema = [
        {
            "type": "function",
            "function": {"name": "read", "description": "d", "parameters": {}},
        }
    ]
    body = proto.build_body(
        messages=[{"role": "user", "content": "hi"}],
        tools=tools_schema,
        model="m",
    )
    assert body["tools"] == tools_schema


def test_build_body_omits_tools_when_empty():
    proto = OpenAIChat()
    body = proto.build_body(messages=[], tools=[], model="m")
    assert "tools" not in body
