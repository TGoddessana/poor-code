from dataclasses import dataclass

import pytest

from poor_code.slash.base import Arg, ArgKind
from poor_code.slash.registry import DuplicateSlashName, SlashRegistry


@dataclass
class _Fake:
    name: str
    description: str = "fake"
    def execute(self, ctx, parsed):  # pragma: no cover
        pass


def test_get_returns_command_by_name():
    r = SlashRegistry([_Fake("login"), _Fake("help")])
    assert r.get("login").name == "login"
    assert r.get("help").name == "help"


def test_get_unknown_returns_none():
    assert SlashRegistry([]).get("nope") is None


def test_duplicate_names_raise():
    with pytest.raises(DuplicateSlashName, match="login"):
        SlashRegistry([_Fake("login"), _Fake("login")])


@dataclass
class _CmdWithArgs:
    name: str
    args: tuple
    description: str = "fake"
    def execute(self, ctx, parsed): pass


def test_rest_must_be_last_arg():
    bad = _CmdWithArgs(name="x", args=(
        Arg("body", ArgKind.REST),
        Arg("after", ArgKind.TOKEN),
    ))
    with pytest.raises(ValueError, match="REST.*last"):
        SlashRegistry([bad])


def test_rest_as_last_is_ok():
    ok = _CmdWithArgs(name="x", args=(
        Arg("name", ArgKind.TOKEN),
        Arg("body", ArgKind.REST),
    ))
    SlashRegistry([ok])  # no raise
