from dataclasses import dataclass, field

from poor_code.slash.base import Arg, ArgKind, ParsedArgs
from poor_code.slash.dispatcher import SlashDispatcher
from poor_code.slash.registry import SlashRegistry
from tests.slash.fakes import FakeSlashContext


@dataclass
class _RecordingCmd:
    name: str = "login"
    description: str = "Sign in"
    args: tuple = ()
    calls: list[ParsedArgs] = field(default_factory=list)

    def execute(self, ctx, parsed: ParsedArgs) -> None:
        self.calls.append(parsed)


def test_dispatch_returns_false_for_non_slash_text():
    d = SlashDispatcher(SlashRegistry([_RecordingCmd()]))
    ctx = FakeSlashContext()
    assert d.dispatch("hello world", ctx) is False
    assert ctx.notifications == []


def test_dispatch_executes_matching_command():
    cmd = _RecordingCmd()
    d = SlashDispatcher(SlashRegistry([cmd]))
    ctx = FakeSlashContext()
    assert d.dispatch("/login", ctx) is True
    assert len(cmd.calls) == 1
    assert cmd.calls[0].values == {}


def test_dispatch_unknown_command_notifies_warning():
    d = SlashDispatcher(SlashRegistry([_RecordingCmd()]))
    ctx = FakeSlashContext()
    assert d.dispatch("/nope", ctx) is True
    assert ctx.notifications == [("warning", "unknown command: /nope")]


def test_dispatch_missing_arg_notifies_usage():
    cmd = _RecordingCmd(name="skill", args=(
        Arg("name", ArgKind.TOKEN),
        Arg("prompt", ArgKind.REST, optional=True),
    ))
    d = SlashDispatcher(SlashRegistry([cmd]))
    ctx = FakeSlashContext()
    assert d.dispatch("/skill", ctx) is True
    assert ctx.notifications == [
        ("warning", "missing arg: name — usage: /skill <name> [prompt]")
    ]
    assert cmd.calls == []


def test_registry_property_exposes_underlying_registry():
    reg = SlashRegistry([_RecordingCmd()])
    d = SlashDispatcher(reg)
    assert d.registry is reg
