from dataclasses import dataclass

import pytest

from poor_code.slash.registry import DuplicateSlashName, SlashRegistry


@dataclass
class _Fake:
    name: str
    description: str = "fake"
    def execute(self, ctx, args):  # pragma: no cover
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
