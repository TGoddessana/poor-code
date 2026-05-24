from dataclasses import dataclass

import pytest

from poor_code.slash.base import Arg, ArgKind, ParsedArgs
from poor_code.slash.parser import MissingArg, UnknownCommand, parse
from poor_code.slash.registry import SlashRegistry


@dataclass
class _Cmd:
    name: str
    description: str = "fake"
    args: tuple = ()
    def execute(self, ctx, parsed): pass


def _registry(*cmds) -> SlashRegistry:
    return SlashRegistry(list(cmds))


def test_parse_no_args():
    r = _registry(_Cmd(name="login"))
    name, parsed = parse("/login", r)
    assert name == "login"
    assert parsed.values == {}
    assert parsed.raw == ""


def test_parse_no_args_with_trailing_garbage_is_dropped():
    r = _registry(_Cmd(name="login"))
    name, parsed = parse("/login foo bar", r)
    assert parsed.values == {}
    assert parsed.raw == "foo bar"


def test_parse_single_token():
    r = _registry(_Cmd(name="model", args=(Arg("name", ArgKind.TOKEN),)))
    _, parsed = parse("/model gpt-4", r)
    assert parsed.values == {"name": "gpt-4"}


def test_parse_token_then_rest():
    r = _registry(_Cmd(name="skill", args=(
        Arg("name", ArgKind.TOKEN),
        Arg("prompt", ArgKind.REST),
    )))
    _, parsed = parse("/skill foo do the thing now", r)
    assert parsed.values == {"name": "foo", "prompt": "do the thing now"}
    assert parsed.raw == "foo do the thing now"


def test_parse_rest_only():
    r = _registry(_Cmd(name="explain", args=(Arg("prompt", ArgKind.REST),)))
    _, parsed = parse("/explain how does X work", r)
    assert parsed.values == {"prompt": "how does X work"}


def test_parse_optional_rest_missing_yields_empty():
    r = _registry(_Cmd(name="skill", args=(
        Arg("name", ArgKind.TOKEN),
        Arg("prompt", ArgKind.REST, optional=True),
    )))
    _, parsed = parse("/skill foo", r)
    assert parsed.values == {"name": "foo", "prompt": ""}


def test_parse_missing_required_token_raises():
    cmd = _Cmd(name="model", args=(Arg("name", ArgKind.TOKEN),))
    r = _registry(cmd)
    with pytest.raises(MissingArg) as ei:
        parse("/model", r)
    assert ei.value.arg.name == "name"
    assert ei.value.cmd is cmd


def test_parse_unknown_command_raises():
    with pytest.raises(UnknownCommand) as ei:
        parse("/nope", _registry(_Cmd(name="login")))
    assert ei.value.name == "nope"


def test_parse_collapses_extra_whitespace_between_tokens():
    r = _registry(_Cmd(name="model", args=(Arg("name", ArgKind.TOKEN),)))
    _, parsed = parse("/model    gpt-4", r)
    assert parsed.values == {"name": "gpt-4"}
