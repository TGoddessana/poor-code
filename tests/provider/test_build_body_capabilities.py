from poor_code.provider.capabilities import Capabilities
from poor_code.provider.protocols.openai_chat import OpenAICompatibleChat
from poor_code.provider.providers import ollama_cloud


SCHEMA = {"type": "json_schema", "json_schema": {"name": "x", "schema": {}}}


def test_response_format_included_when_capable():
    body = OpenAICompatibleChat().build_body(
        messages=[], tools=[], model="m",
        capabilities=Capabilities(response_format=True), response_format=SCHEMA)
    assert body["response_format"] == SCHEMA


def test_response_format_dropped_when_not_capable():
    body = OpenAICompatibleChat().build_body(
        messages=[], tools=[], model="m",
        capabilities=Capabilities(response_format=False), response_format=SCHEMA)
    assert "response_format" not in body


def test_response_format_absent_when_not_requested():
    body = OpenAICompatibleChat().build_body(
        messages=[], tools=[], model="m",
        capabilities=Capabilities(response_format=True))
    assert "response_format" not in body


def test_ollama_cloud_declares_response_format_only():
    client = ollama_cloud.configure(model="m", api_key="k")
    caps = client.capabilities
    assert caps.response_format is True
    assert caps.tool_choice is False
    assert caps.parallel_tool_calls is False
    assert caps.strict_tools is False
